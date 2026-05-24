#!/usr/bin/env python3
"""
PiScreenPortal: Web-Interface zum Steuern mehrerer Chromium-Kiosk-Fenster
auf einem Raspberry Pi mit mehreren Monitoren.
"""
from __future__ import annotations

import hmac
import io
import json
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import threading
import time
import zlib
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, send_file, session, url_for)

try:
    import qrcode
except ImportError:
    qrcode = None

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
LOG_FILE = BASE_DIR / "kiosk.log"
MAINTENANCE_STATE_FILE = BASE_DIR / "maintenance_state.json"
VERSION_FILE = BASE_DIR / "VERSION"
GIT_REMOTE_URL = "https://github.com/WEXiT/PiScreenPortal.git"


def default_xauthority() -> str:
    return str(Path.home() / ".Xauthority")

DEFAULT_CONFIG = {
    "port": 2411,
    "auth": {"enabled": False, "username": "admin", "password": "admin"},
    "screens": [
        {
            "name": "Links",
            "enabled": True,
            "url": "https://www.raspberrypi.com",
            "output": "",
            "rotation": "normal",
            "hide_cursor": True,
            "reload_interval": 0,
            "zoom": 1.0,
        },
        {
            "name": "Rechts",
            "enabled": True,
            "url": "https://www.google.com",
            "output": "",
            "rotation": "normal",
            "hide_cursor": True,
            "reload_interval": 0,
            "zoom": 1.0,
        },
    ],
    "chromium_flags": [
        "--noerrdialogs",
        "--disable-infobars",
        "--disable-session-crashed-bubble",
        "--disable-features=TranslateUI",
        "--overscroll-history-navigation=0",
        "--check-for-update-interval=31536000",
        "--password-store=basic",
        "--use-mock-keychain",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-translate",
        "--disable-sync",
        "--disable-notifications",
        "--disable-popup-blocking",
        # Begrenzt den Disk-Cache pro Profil auf ca. 100 MB, damit die
        # Verzeichnisse chromium-profile-* auf der SD-Karte nicht ueber
        # Monate unbegrenzt wachsen.
        "--disk-cache-size=104857600",
    ],
    "auto_start": True,
    "restart_on_crash": True,
    "auto_reboot": {
        "enabled": False,
        "mode": "daily",            # daily | interval
        "interval_minutes": 1440,
        "time": "06:00",
    },
    "presentation": {
        "airplay_name": "PiScreenPortal",
        "output": "",               # xrandr-Name; leer = primary
        "resolution": "1920x1080",
        "extra_flags": [],
        "stop_kiosk_while_active": True,
    },
}


# ---------------------- Config ---------------------- #
REQUIRED_FLAGS = [
    "--noerrdialogs",
    "--disable-infobars",
    "--disable-session-crashed-bubble",
    "--disable-features=TranslateUI",
    "--overscroll-history-navigation=0",
    "--check-for-update-interval=31536000",
    "--password-store=basic",
    "--use-mock-keychain",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-translate",
    "--disable-sync",
    "--disable-notifications",
    "--disable-popup-blocking",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-domain-reliability",
    "--disable-save-password-bubble",
]
FLAG_PREFIXES_SINGLE = (
    "--password-store=",
    "--user-data-dir=",
)


def _clone_default(value):
    return json.loads(json.dumps(value))


def _merge_defaults(cfg: dict, defaults: dict) -> None:
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = _clone_default(v)
        elif isinstance(v, dict) and isinstance(cfg.get(k), dict):
            _merge_defaults(cfg[k], v)


def _valid_hhmm(value: str) -> str | None:
    parts = str(value or "").strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def normalize_auto_reboot(value) -> dict:
    default = _clone_default(DEFAULT_CONFIG["auto_reboot"])
    src = value if isinstance(value, dict) else {}
    mode = src.get("mode") if src.get("mode") in ("daily", "interval") else default["mode"]
    try:
        interval = int(float(src.get("interval_minutes", default["interval_minutes"])))
    except (TypeError, ValueError):
        interval = default["interval_minutes"]
    interval = max(1, min(interval, 43200))
    hhmm = _valid_hhmm(src.get("time")) or default["time"]
    return {
        "enabled": bool(src.get("enabled", default["enabled"])),
        "mode": mode,
        "interval_minutes": interval,
        "time": hhmm,
    }


def normalize_config(cfg: dict) -> dict:
    _merge_defaults(cfg, DEFAULT_CONFIG)
    cfg["auto_reboot"] = normalize_auto_reboot(cfg.get("auto_reboot"))
    cfg["chromium_flags"] = normalize_chromium_flags(cfg.get("chromium_flags"))
    return cfg


def normalize_chromium_flags(flags) -> list[str]:
    src = flags if isinstance(flags, list) else []
    out = []
    for flag in src:
        flag = str(flag or "").strip()
        if not flag:
            continue
        if any(flag.startswith(prefix) for prefix in FLAG_PREFIXES_SINGLE):
            continue
        if flag not in out and flag not in REQUIRED_FLAGS:
            out.append(flag)
    out.extend(REQUIRED_FLAGS)
    return out


def validate_config_payload(cfg: dict) -> tuple[dict | None, str | None]:
    if not isinstance(cfg, dict) or "screens" not in cfg:
        return None, "Ungültige Config"
    auth = (cfg.get("auth") or {})
    if auth.get("enabled") and (not auth.get("username") or not auth.get("password")):
        return None, ("Wenn der Zugangsschutz aktiv ist, müssen Benutzername "
                      "und Passwort gesetzt sein.")
    return normalize_config(cfg), None


def json_payload() -> tuple[dict | None, str | None]:
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return None, "Ungültige JSON-Daten"
    return data, None


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            normalize_config(cfg)
            return cfg
        except Exception as e:
            log(f"Config-Fehler, lade Defaults: {e}")
    return normalize_config(_clone_default(DEFAULT_CONFIG))


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def logs_for_language(text: str, lang: str) -> str:
    if lang != "en":
        return text
    replacements = [
        ("Config-Fehler, lade Defaults:", "Config error, loading defaults:"),
        ("xrandr fehlgeschlagen:", "xrandr failed:"),
        ("Auto-Reboot Scheduler Fehler:", "Auto-reboot scheduler error:"),
        ("Maintenance-State konnte nicht gespeichert werden:",
         "Could not save maintenance state:"),
        ("Auto-Reboot Scheduler aktiviert/aktualisiert",
         "Auto-reboot scheduler enabled/updated"),
        ("Auto-Reboot: Raspberry wird neu gestartet",
         "Auto-reboot: Raspberry is rebooting"),
        ("Update-Scan fehlgeschlagen:", "Update scan failed:"),
        ("Git-Update fehlgeschlagen:", "Git update failed:"),
        ("Git-Update erfolgreich", "Git update successful"),
        ("Reboot geplant", "reboot scheduled"),
        ("Git-Update Fehler:", "Git update error:"),
        ("Boot-Desktop-Optimierung angewendet",
         "Boot desktop optimization applied"),
        ("Reboot fehlgeschlagen:", "Reboot failed:"),
        ("fehlgeschlagen:", "failed:"),
        ("Fehler:", "error:"),
        ("Starte Präsentation", "Starting presentation"),
        ("Starte PrÃ¤sentation", "Starting presentation"),
        ("Präsentation gestartet", "Presentation started"),
        ("PrÃ¤sentation gestartet", "Presentation started"),
        ("UxPlay Stop-Fehler:", "UxPlay stop error:"),
        ("unclutter nicht installiert - Mauszeiger bleibt sichtbar",
         "unclutter is not installed - cursor remains visible"),
        ("Sitzungstyp ist Wayland - unclutter kann den Cursor nicht ausblenden, wird übersprungen. Cursor-Ausblenden erfordert eine X11-Sitzung.",
         "Session type is Wayland - unclutter cannot hide the cursor and is skipped. Cursor hiding requires an X11 session."),
        ("Sitzungstyp ist Wayland - unclutter kann den Cursor nicht ausblenden, wird Ã¼bersprungen. Cursor-Ausblenden erfordert eine X11-Sitzung.",
         "Session type is Wayland - unclutter cannot hide the cursor and is skipped. Cursor hiding requires an X11 session."),
        ("unclutter gestartet (Mauszeiger verborgen)",
         "unclutter started (cursor hidden)"),
        ("unclutter-Start fehlgeschlagen:", "unclutter start failed:"),
        ("Rotate-Fehler", "Rotation error"),
        ("Auto-Reload Bildschirm", "Auto-reload screen"),
        ("Reload-Fehler", "Reload error"),
        ("Kein Monitor für Bildschirm", "No monitor for screen"),
        ("Kein Monitor fÃ¼r Bildschirm", "No monitor for screen"),
        ("Starte Bildschirm", "Starting screen"),
        (" auf ", " on "),
        ("Chromium nicht gefunden – sudo apt install chromium-browser",
         "Chromium not found - sudo apt install chromium-browser"),
        ("Chromium nicht gefunden â€“ sudo apt install chromium-browser",
         "Chromium not found - sudo apt install chromium-browser"),
        ("Stop-Fehler", "Stop error"),
        ("Erkannte Monitore:", "Detected monitors:"),
        ("Respawn Bildschirm", "Respawn screen"),
        ("Konnte SECRET_KEY nicht speichern:",
         "Could not save SECRET_KEY:"),
        ("Login erfolgreich:", "Login successful:"),
        ("Login fehlgeschlagen:", "Login failed:"),
        (" von ", " from "),
        ("(leer)", "(empty)"),
        ("Config gespeichert", "Config saved"),
        ("Reload: xdotool ist nicht installiert",
         "Reload: xdotool is not installed"),
        ("xdotool search", "xdotool search"),
        ("Keine Chromium-Fenster gefunden", "no Chromium windows found"),
        ("Fenster gesendet", "windows"),
        ("ist nicht installiert", "is not installed"),
        ("nicht installiert", "not installed"),
        ("Kommando gestartet", "Command started"),
        ("Unbekannt", "Unknown"),
        ("Das System kann die angegebene Datei nicht finden",
         "The system cannot find the file specified"),
        ("Datei nicht finden", "file not found"),
    ]
    out = text
    for old, new in replacements:
        out = out.replace(old, new)
    out = re.sub(r"Reload: F5 an ([0-9]+)/([0-9]+) windows",
                 r"Reload: F5 sent to \1/\2 windows", out)
    return out


# ---------------------- Monitor-Erkennung ---------------------- #
def detect_monitors() -> list:
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XAUTHORITY", default_xauthority())
    try:
        out = subprocess.check_output(
            ["xrandr", "--query"], env=env, stderr=subprocess.STDOUT, timeout=5
        ).decode("utf-8", errors="ignore")
    except Exception as e:
        log(f"xrandr fehlgeschlagen: {e}")
        return []

    monitors = []
    for line in out.splitlines():
        if " connected" in line:
            parts = line.split()
            name = parts[0]
            primary = "primary" in parts
            geom = ""
            for p in parts:
                if "x" in p and "+" in p and p[0].isdigit():
                    geom = p
                    break
            w = h = x = y = 0
            if geom:
                try:
                    wh, xs, ys = geom.split("+")
                    w, h = map(int, wh.split("x"))
                    x, y = int(xs), int(ys)
                except Exception:
                    pass
            monitors.append({"name": name, "primary": primary,
                             "x": x, "y": y, "width": w, "height": h,
                             "geometry": geom})
    monitors.sort(key=lambda m: m["x"])
    return monitors


# ---------------------- System-Info ---------------------- #
def get_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "?"


def cpu_temp() -> str:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return f"{int(f.read().strip()) / 1000:.1f} °C"
    except Exception:
        return "?"


def _run(cmd: list, timeout: int = 5) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL,
                                       timeout=timeout).decode().strip()
    except Exception:
        return ""


def _mem() -> dict:
    d = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith(("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")):
                    k, v = line.split(":")
                    # in MB umrechnen
                    kb = int(v.strip().split()[0])
                    d[k.strip()] = f"{kb/1024:.0f} MB"
    except Exception:
        pass
    return d


def _disk() -> dict:
    try:
        out = subprocess.check_output(["df", "-h", "/"], timeout=3).decode().splitlines()
        if len(out) >= 2:
            parts = out[1].split()
            return {"total": parts[1], "used": parts[2], "free": parts[3], "percent": parts[4]}
    except Exception:
        pass
    return {}


def _load_avg() -> str:
    try:
        with open("/proc/loadavg") as f:
            return " ".join(f.read().split()[:3])
    except Exception:
        return ""


def _pi_model() -> str:
    try:
        with open("/proc/device-tree/model") as f:
            return f.read().strip().rstrip("\x00")
    except Exception:
        return ""


def _kernel() -> str:
    return _run(["uname", "-srm"])


def _cpu_percent() -> str:
    # einfacher Snapshot via /proc/stat über 0.3s
    try:
        def read():
            with open("/proc/stat") as f:
                parts = f.readline().split()[1:]
                vals = list(map(int, parts))
                idle = vals[3]
                total = sum(vals)
                return idle, total
        i1, t1 = read(); time.sleep(0.3); i2, t2 = read()
        dt = t2 - t1
        if dt <= 0: return ""
        return f"{(1 - (i2 - i1) / dt) * 100:.0f}%"
    except Exception:
        return ""


def session_type() -> str:
    """Gibt "x11", "wayland" oder "unknown" zurück."""
    env_val = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    if env_val in ("x11", "wayland"):
        return env_val
    # Fallback via loginctl: grafische Session des Users ermitteln und
    # dann deren Typ abfragen. Funktioniert auch, wenn der systemd-Service
    # nicht direkt aus der grafischen Sitzung heraus gestartet wurde.
    try:
        user = os.environ.get("USER") or "pi"
        sess_id = subprocess.check_output(
            ["loginctl", "show-user", "--value", "-p", "Display", user],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
        if sess_id:
            typ = subprocess.check_output(
                ["loginctl", "show-session", sess_id, "--value", "-p", "Type"],
                stderr=subprocess.DEVNULL, timeout=3,
            ).decode().strip().lower()
            if typ in ("x11", "wayland"):
                return typ
    except Exception:
        pass
    # Letzter Fallback ueber Environment
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def _which_any(*names: str) -> str | None:
    """Gibt den ersten Treffer aus shutil.which fuer eine Liste von
    Kandidaten zurueck. Nuetzlich, wenn ein Tool unter unterschiedlichen
    Paketnamen installiert sein kann (chromium vs. chromium-browser)."""
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


# Welche Tools/Dienste die Anwendung braucht. Wird vom Dashboard genutzt,
# um auf einen Blick zu zeigen was läuft und was fehlt.
# target = Liste von Kandidaten (erster Treffer zählt). Bei "process" wird
# zusätzlich pgrep -f auf den ersten Namen ausgeführt.
_SERVICE_SPEC = [
    # key,        type,      targets,                     label,                      kind,       note
    ("chromium",  "process", ("chromium", "chromium-browser"), "Chromium",             "kiosk",    ""),
    ("unclutter", "process", ("unclutter",),              "unclutter",                "cursor",
        "Blendet den Mauszeiger aus (benötigt X11)."),
    ("xdotool",   "binary",  ("xdotool",),                "xdotool",                  "tool",
        "Wird für die Reload-Aktion benötigt."),
    ("xrandr",    "binary",  ("xrandr",),                 "xrandr",                   "tool",
        "Wird für die Monitor-Erkennung benötigt."),
    ("uxplay",    "process", ("uxplay",),                 "UxPlay (AirPlay)",         "airplay",
        "Nur aktiv während eine Präsentation läuft."),
    ("nmcli",     "binary",  ("nmcli",),                  "NetworkManager (nmcli)",   "wifi",
        "Wird für die WLAN-Verwaltung benötigt."),
    ("avahi",     "systemd", ("avahi-daemon",),           "avahi-daemon",             "airplay",
        "mDNS-Dienst damit AirPlay-Geräte den Pi finden."),
    ("nm_service","systemd", ("NetworkManager",),         "NetworkManager (systemd)", "wifi", ""),
    ("pi_kiosk",  "systemd", ("pi-kiosk",),               "pi-kiosk.service",         "system",
        "Eigener Autostart-Dienst."),
]


def _pgrep(name: str) -> list[int]:
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", name], stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip().splitlines()
        return [int(x) for x in out if x.strip().isdigit()]
    except Exception:
        return []


def _systemd_state(unit: str) -> tuple[bool, bool]:
    """(active, enabled)"""
    active = False
    enabled = False
    try:
        r = subprocess.run(["systemctl", "is-active", unit],
                           capture_output=True, timeout=3)
        active = r.stdout.decode().strip() == "active"
    except Exception:
        pass
    try:
        r = subprocess.run(["systemctl", "is-enabled", unit],
                           capture_output=True, timeout=3)
        enabled = r.stdout.decode().strip() in ("enabled", "alias", "static",
                                                "enabled-runtime")
    except Exception:
        pass
    return active, enabled


# ---------------------- Energie / 24/7-Modus ---------------------- #
NM_POWERSAVE_CONF = Path("/etc/NetworkManager/conf.d/99-pi-kiosk-powersave.conf")


def _wifi_powersave_state() -> dict:
    """Status des WLAN-Powersaving: on / off / unknown."""
    if not shutil.which("iw"):
        return {"available": False, "reason": "iw nicht installiert"}
    # Primäres WLAN-Interface ermitteln
    iface = None
    try:
        out = subprocess.check_output(["iw", "dev"], stderr=subprocess.DEVNULL,
                                      timeout=3).decode()
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("Interface "):
                iface = s.split()[-1]
                break
    except Exception as e:
        return {"available": False, "reason": str(e)}
    if not iface:
        return {"available": False, "reason": "kein WLAN-Interface"}
    try:
        out = subprocess.check_output(
            ["iw", "dev", iface, "get", "power_save"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip().lower()
        # z.B. "Power save: off" oder "Power save: on"
        state = "on" if "power save: on" in out else \
                "off" if "power save: off" in out else "unknown"
        return {"available": True, "iface": iface, "state": state}
    except Exception as e:
        return {"available": False, "reason": str(e)}


def _nm_powersave_config() -> dict:
    """Liest unsere NetworkManager-Powersave-Konfigurations-Datei."""
    if not NM_POWERSAVE_CONF.exists():
        return {"configured": False}
    try:
        content = NM_POWERSAVE_CONF.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            s = line.strip().lower().replace(" ", "")
            if s.startswith("wifi.powersave="):
                val = s.split("=", 1)[1]
                return {"configured": True, "value": val,
                        "disabled": val in ("2", "false", "no")}
        return {"configured": True, "value": None}
    except Exception:
        return {"configured": False}


def _xset_blanking_state() -> dict:
    """Liest Screensaver + DPMS via `xset q`."""
    if not shutil.which("xset"):
        return {"available": False, "reason": "xset nicht installiert"}
    try:
        out = subprocess.check_output(
            ["xset", "q"], env=self_env(),
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode()
    except Exception as e:
        return {"available": False, "reason": str(e)}

    ss_timeout = 0
    dpms_enabled = False
    dpms_seen = False
    for raw in out.splitlines():
        line = raw.strip()
        if line.lower().startswith("timeout:"):
            parts = line.split()
            try:
                ss_timeout = int(parts[1])
            except Exception:
                pass
        elif "DPMS is Enabled" in line:
            dpms_enabled, dpms_seen = True, True
        elif "DPMS is Disabled" in line:
            dpms_enabled, dpms_seen = False, True

    return {
        "available": True,
        "screensaver_timeout": ss_timeout,
        "dpms_enabled": dpms_enabled,
        "dpms_reported": dpms_seen,
        # "24/7 ok" heißt: kein Screensaver-Timeout + DPMS aus
        "blanking_off": (ss_timeout == 0 and not dpms_enabled),
    }


def power_status() -> dict:
    """Aggregierter Energie-Status fuer das Dashboard."""
    wifi = _wifi_powersave_state()
    wifi_persistent = _nm_powersave_config()
    blanking = _xset_blanking_state()

    # Gesamtbewertung
    wifi_ok = (wifi.get("state") == "off") and wifi_persistent.get("disabled", False)
    blanking_ok = blanking.get("available") and blanking.get("blanking_off", False)
    overall = "ok" if (wifi_ok and blanking_ok) else "warn"
    # Wenn eine Komponente gar nicht verfuegbar ist (z.B. iw fehlt) -> idle
    if (not wifi.get("available")) and (not blanking.get("available")):
        overall = "idle"

    return {
        "overall": overall,
        "wifi_powersave": {
            **wifi,
            "persistent_disabled": wifi_persistent.get("disabled", False),
            "persistent_config_file": str(NM_POWERSAVE_CONF),
        },
        "screen_blanking": blanking,
        "session": session_type(),
    }


def _force_disable_power_save() -> dict:
    """Erzwingt 24/7-Modus: Live-Settings + persistent.
    Gibt ein Dict mit Einzelschritten zurueck, damit das Frontend zeigen
    kann was funktioniert hat und was nicht."""
    results = {"steps": []}

    # 1) Live: xset - kein root noetig
    if shutil.which("xset"):
        try:
            for args in (["xset", "s", "off"],
                         ["xset", "-dpms"],
                         ["xset", "s", "noblank"]):
                r = subprocess.run(args, env=self_env(),
                                   capture_output=True, timeout=5)
                ok = r.returncode == 0
                results["steps"].append({
                    "step": " ".join(args), "ok": ok,
                    "msg": (r.stderr + r.stdout).decode("utf-8", "ignore").strip()
                           or ("OK" if ok else f"exit {r.returncode}"),
                })
        except Exception as e:
            results["steps"].append({"step": "xset", "ok": False, "msg": str(e)})
    else:
        results["steps"].append({"step": "xset", "ok": False,
                                 "msg": "xset nicht installiert"})

    # 2) Live: WLAN-Powersave via NetworkManager auf aktive Verbindung
    if shutil.which("nmcli"):
        try:
            # aktuelle verbundene Wifi-Verbindung ermitteln
            out = subprocess.check_output(
                ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show",
                 "--active"], stderr=subprocess.DEVNULL, timeout=5,
            ).decode()
            wifi_con = None
            for line in out.splitlines():
                parts = nmcli_split(line)
                if len(parts) >= 2 and "wireless" in parts[1]:
                    wifi_con = parts[0]
                    break
            if wifi_con:
                r = subprocess.run(
                    ["sudo", "-n", "nmcli", "connection", "modify",
                     wifi_con, "wifi.powersave", "2"],
                    capture_output=True, timeout=10,
                )
                results["steps"].append({
                    "step": f"nmcli modify '{wifi_con}' wifi.powersave=2",
                    "ok": r.returncode == 0,
                    "msg": (r.stderr + r.stdout).decode("utf-8", "ignore").strip()
                           or ("OK" if r.returncode == 0 else f"exit {r.returncode}"),
                })
                # Verbindung neu aktivieren, damit powersave sofort greift
                subprocess.run(["sudo", "-n", "nmcli", "connection", "up", wifi_con],
                               capture_output=True, timeout=15)
            else:
                results["steps"].append({
                    "step": "nmcli modify powersave",
                    "ok": False,
                    "msg": "Keine aktive WLAN-Verbindung gefunden",
                })
        except Exception as e:
            results["steps"].append({"step": "nmcli", "ok": False, "msg": str(e)})
    else:
        results["steps"].append({"step": "nmcli", "ok": False,
                                 "msg": "nmcli nicht installiert"})

    # 3) Status nach den Aenderungen neu einsammeln
    results["status"] = power_status()
    return results


def services_status() -> dict:
    """Zustand aller relevanten Tools und Dienste für das Dashboard."""
    sess = session_type()
    items = []
    for key, typ, targets, label, kind, note in _SERVICE_SPEC:
        primary = targets[0]
        entry = {"key": key, "label": label, "kind": kind,
                 "type": typ, "target": primary, "note": note}
        if typ == "binary":
            entry["installed"] = _which_any(*targets) is not None
            entry["running"] = None          # "nicht zutreffend"
        elif typ == "process":
            entry["installed"] = _which_any(*targets) is not None
            # pgrep auf den ersten Kandidaten; bei Chromium matcht die
            # gemeinsame Substring-Suche automatisch auch chromium-browser.
            pids = _pgrep(primary)
            entry["running"] = len(pids) > 0
            entry["pids"] = pids
        elif typ == "systemd":
            # installed heißt hier: unit-Datei existiert
            try:
                r = subprocess.run(["systemctl", "list-unit-files",
                                    primary + ".service"],
                                   capture_output=True, timeout=3)
                entry["installed"] = (primary + ".service") in r.stdout.decode()
            except Exception:
                entry["installed"] = False
            active, enabled = _systemd_state(primary)
            entry["running"] = active
            entry["enabled"] = enabled

        # Warnungen
        warn = None
        if key == "unclutter" and sess == "wayland" and entry.get("installed"):
            warn = ("unclutter ist installiert, hat aber auf Wayland keine "
                    "Wirkung. Für Cursor-Ausblenden bitte eine X11-Sitzung "
                    "verwenden (raspi-config → Advanced → Wayland → X11).")
        elif (typ in ("binary", "process")) and not entry.get("installed"):
            warn = f"'{primary}' ist nicht installiert."
        entry["warn"] = warn
        items.append(entry)

    return {
        "session": sess,
        "user": os.environ.get("USER", ""),
        "display": os.environ.get("DISPLAY", ""),
        "wayland_display": os.environ.get("WAYLAND_DISPLAY", ""),
        "items": items,
    }


def system_info() -> dict:
    return {
        "hostname": socket.gethostname(),
        "ip": get_ip(),
        "model": _pi_model(),
        "kernel": _kernel(),
        "cpu_temp": cpu_temp(),
        "cpu_percent": _cpu_percent(),
        "uptime": _run(["uptime", "-p"]) or "",
        "load_avg": _load_avg(),
        "memory": _mem(),
        "disk": _disk(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------------------- Wartung / Auto-Reboot ---------------------- #
class MaintenanceManager:
    def __init__(self):
        self._started = False
        self._lock = threading.Lock()
        self._update_lock = threading.Lock()
        self._system_update_lock = threading.Lock()
        self._system_update_state_lock = threading.Lock()
        self._system_update_state = {
            "running": False,
            "mode": "",
            "ok": None,
            "error": "",
            "packages": [],
            "count": 0,
            "checked_at": None,
            "installed_at": None,
            "output": "",
            "reboot_required": False,
        }

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                self._tick()
            except Exception as e:
                log(f"Auto-Reboot Scheduler Fehler: {e}")
            time.sleep(30)

    def _load_state(self) -> dict:
        if not MAINTENANCE_STATE_FILE.exists():
            return {}
        try:
            with open(MAINTENANCE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_state(self, state: dict) -> None:
        try:
            with open(MAINTENANCE_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log(f"Maintenance-State konnte nicht gespeichert werden: {e}")

    def _signature(self, cfg: dict) -> str:
        return json.dumps({
            "enabled": cfg.get("enabled"),
            "mode": cfg.get("mode"),
            "interval_minutes": cfg.get("interval_minutes"),
            "time": cfg.get("time"),
        }, sort_keys=True)

    def _daily_target(self, cfg: dict, now: datetime | None = None) -> datetime:
        now = now or datetime.now()
        hour, minute = map(int, cfg.get("time", "06:00").split(":"))
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def _mark_schedule_seen(self, cfg: dict, state: dict, now: datetime) -> None:
        state["schedule_signature"] = self._signature(cfg)
        if cfg.get("mode") == "interval":
            state["last_interval_reboot_at"] = time.time()
        else:
            target = self._daily_target(cfg, now)
            if now >= target:
                state["last_daily_reboot_date"] = now.strftime("%Y-%m-%d")
        self._save_state(state)

    def _mark_reboot(self, cfg: dict, state: dict, now: datetime) -> None:
        state["last_auto_reboot_at"] = int(time.time())
        if cfg.get("mode") == "interval":
            state["last_interval_reboot_at"] = time.time()
        else:
            state["last_daily_reboot_date"] = now.strftime("%Y-%m-%d")
        state["schedule_signature"] = self._signature(cfg)
        self._save_state(state)

    def _tick(self) -> None:
        cfg = normalize_auto_reboot(load_config().get("auto_reboot"))
        if not cfg.get("enabled"):
            state = self._load_state()
            if state.get("schedule_signature") != self._signature(cfg):
                state["schedule_signature"] = self._signature(cfg)
                self._save_state(state)
            return
        now = datetime.now()
        state = self._load_state()
        if state.get("schedule_signature") != self._signature(cfg):
            self._mark_schedule_seen(cfg, state, now)
            log("Auto-Reboot Scheduler aktiviert/aktualisiert")
            return

        due = False
        if cfg.get("mode") == "interval":
            if not state.get("last_interval_reboot_at"):
                state["last_interval_reboot_at"] = time.time()
                self._save_state(state)
                return
            last = float(state.get("last_interval_reboot_at"))
            due = (time.time() - last) >= (cfg["interval_minutes"] * 60)
        else:
            target = self._daily_target(cfg, now)
            today = now.strftime("%Y-%m-%d")
            due = now >= target and state.get("last_daily_reboot_date") != today

        if due:
            self._mark_reboot(cfg, state, now)
            log("Auto-Reboot: Raspberry wird neu gestartet")
            self._reboot_later("auto-reboot", delay=2)

    def _next_reboot_ts(self, cfg: dict, state: dict) -> float | None:
        if not cfg.get("enabled"):
            return None
        now = datetime.now()
        if cfg.get("mode") == "interval":
            last = float(state.get("last_interval_reboot_at") or time.time())
            return last + cfg["interval_minutes"] * 60

        target = self._daily_target(cfg, now)
        today = now.strftime("%Y-%m-%d")
        if now < target and state.get("last_daily_reboot_date") != today:
            return target.timestamp()
        return (target + timedelta(days=1)).timestamp()

    def status(self) -> dict:
        cfg = normalize_auto_reboot(load_config().get("auto_reboot"))
        state = self._load_state()
        next_ts = self._next_reboot_ts(cfg, state)
        last_ts = state.get("last_auto_reboot_at")
        return {
            "auto_reboot": cfg,
            "running": self._started,
            "next_reboot_at": (
                datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d %H:%M:%S")
                if next_ts else None
            ),
            "next_reboot_in_seconds": (
                max(0, int(next_ts - time.time())) if next_ts else None
            ),
            "last_auto_reboot_at": (
                datetime.fromtimestamp(float(last_ts)).strftime("%Y-%m-%d %H:%M:%S")
                if last_ts else None
            ),
            "version": self.current_version(),
            "git": self.git_info(),
        }

    def current_version(self) -> str:
        try:
            return VERSION_FILE.read_text(encoding="utf-8").strip() or "0"
        except Exception:
            return "0"

    def _version_parts(self, version: str) -> list:
        clean = str(version or "0").strip().lstrip("vV")
        parts = []
        for piece in re.split(r"[.+_-]", clean):
            if piece.isdigit():
                parts.append(int(piece))
            elif piece:
                parts.append(piece)
        return parts or [0]

    def _compare_versions(self, local: str, remote: str) -> int:
        left = self._version_parts(local)
        right = self._version_parts(remote)
        max_len = max(len(left), len(right))
        left.extend([0] * (max_len - len(left)))
        right.extend([0] * (max_len - len(right)))
        for a, b in zip(left, right):
            if a == b:
                continue
            if isinstance(a, int) and isinstance(b, int):
                return -1 if a < b else 1
            return -1 if str(a) < str(b) else 1
        return 0

    def _origin_setup_cmd(self) -> list[str]:
        if self._git_text(["remote", "get-url", "origin"]):
            return ["git", "remote", "set-url", "origin", GIT_REMOTE_URL]
        return ["git", "remote", "add", "origin", GIT_REMOTE_URL]

    def _run_git(self, cmd: list[str], env: dict | None = None,
                 timeout: int = 60) -> tuple[bool, str]:
        try:
            r = subprocess.run(cmd, cwd=BASE_DIR, env=env,
                               capture_output=True, timeout=timeout)
            out = (r.stdout + r.stderr).decode("utf-8", "ignore").strip()
            if r.returncode != 0:
                return False, out or f"Exit-Code {r.returncode}"
            return True, out
        except subprocess.TimeoutExpired:
            return False, "Git-Kommando hat zu lange gedauert."
        except Exception as e:
            return False, str(e)

    def check_for_updates(self) -> dict:
        local_version = self.current_version()
        if not shutil.which("git"):
            return {"ok": False, "error": "git ist nicht installiert.",
                    "current_version": local_version}
        if not (BASE_DIR / ".git").exists():
            return {"ok": False, "error": "Dieses Verzeichnis ist kein Git-Repository.",
                    "current_version": local_version}
        if not self._update_lock.acquire(blocking=False):
            return {"ok": False, "error": "Ein Update oder Scan laeuft bereits.",
                    "current_version": local_version}
        try:
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["LC_ALL"] = "C"
            env["LANG"] = "C"
            outputs = []
            for cmd in (self._origin_setup_cmd(),
                        ["git", "fetch", "--prune", "origin", "main"]):
                ok, out = self._run_git(cmd, env=env, timeout=90)
                outputs.append(f"$ {' '.join(cmd)}\n{out}".strip())
                if not ok:
                    log(f"Update-Scan fehlgeschlagen: {out}")
                    return {"ok": False, "error": out,
                            "current_version": local_version,
                            "output": "\n\n".join(outputs)}

            remote_version = self._git_text(["show", "origin/main:VERSION"],
                                            timeout=20).strip()
            if not remote_version:
                current_head = self._git_text(["rev-parse", "--short", "HEAD"])
                remote_head = self._git_text(["rev-parse", "--short", "origin/main"])
                return {
                    "ok": True,
                    "current_version": local_version,
                    "remote_version": remote_head or "origin/main",
                    "update_available": bool(
                        current_head and remote_head and current_head != remote_head),
                    "local_newer": False,
                    "version_missing": True,
                    "current_head": current_head,
                    "remote_head": remote_head,
                    "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "output": "\n\n".join(outputs),
                }

            cmp = self._compare_versions(local_version, remote_version)
            return {
                "ok": True,
                "current_version": local_version,
                "remote_version": remote_version,
                "update_available": cmp < 0,
                "local_newer": cmp > 0,
                "current_head": self._git_text(["rev-parse", "--short", "HEAD"]),
                "remote_head": self._git_text(["rev-parse", "--short", "origin/main"]),
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        finally:
            self._update_lock.release()

    def git_info(self) -> dict:
        if not (BASE_DIR / ".git").exists():
            return {"available": False, "remote": "", "branch": ""}
        return {
            "available": shutil.which("git") is not None,
            "remote": self._git_text(["config", "--get", "remote.origin.url"]),
            "branch": self._git_text(["rev-parse", "--abbrev-ref", "HEAD"]),
            "head": self._git_text(["rev-parse", "--short", "HEAD"]),
        }

    def _git_text(self, args: list[str], timeout: int = 10) -> str:
        if not shutil.which("git"):
            return ""
        try:
            r = subprocess.run(["git", *args], cwd=BASE_DIR,
                               capture_output=True, timeout=timeout)
            if r.returncode != 0:
                return ""
            return r.stdout.decode("utf-8", "ignore").strip()
        except Exception:
            return ""

    def update_from_git_and_reboot(self) -> dict:
        if not shutil.which("git"):
            return {"ok": False, "error": "git ist nicht installiert."}
        if not (BASE_DIR / ".git").exists():
            return {"ok": False, "error": "Dieses Verzeichnis ist kein Git-Repository."}
        if not self._update_lock.acquire(blocking=False):
            return {"ok": False, "error": "Ein Update laeuft bereits."}
        try:
            before = self._git_text(["rev-parse", "--short", "HEAD"])
            before_version = self.current_version()
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["LC_ALL"] = "C"
            env["LANG"] = "C"
            cmds = [
                self._origin_setup_cmd(),
                ["git", "fetch", "--prune", "origin", "main"],
                ["git", "pull", "--ff-only", "origin", "main"],
            ]
            outputs = []
            for cmd in cmds:
                ok, out = self._run_git(cmd, env=env, timeout=120)
                outputs.append(f"$ {' '.join(cmd)}\n{out}".strip())
                if not ok:
                    log(f"Git-Update fehlgeschlagen: {out}")
                    return {"ok": False, "error": out, "output": "\n\n".join(outputs)}

            after = self._git_text(["rev-parse", "--short", "HEAD"])
            after_version = self.current_version()
            log(f"Git-Update erfolgreich ({before} -> {after}), Reboot geplant")
            self._reboot_later("git-update", delay=3)
            return {
                "ok": True,
                "before": before,
                "after": after,
                "before_version": before_version,
                "after_version": after_version,
                "changed": before != after,
                "output": "\n\n".join(outputs),
                "reboot_scheduled": True,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Git-Update hat zu lange gedauert."}
        except Exception as e:
            log(f"Git-Update Fehler: {e}")
            return {"ok": False, "error": str(e)}
        finally:
            self._update_lock.release()

    def _system_state(self) -> dict:
        with self._system_update_state_lock:
            return _clone_default(self._system_update_state)

    def _set_system_state(self, **updates) -> dict:
        with self._system_update_state_lock:
            self._system_update_state.update(updates)
            return _clone_default(self._system_update_state)

    def _run_system_cmd(self, cmd: list[str], timeout: int = 120) -> tuple[bool, str]:
        env = os.environ.copy()
        env["DEBIAN_FRONTEND"] = "noninteractive"
        env["APT_LISTCHANGES_FRONTEND"] = "none"
        try:
            r = subprocess.run(cmd, env=env, capture_output=True, timeout=timeout)
            out = (r.stdout + r.stderr).decode("utf-8", "ignore").strip()
            if r.returncode != 0:
                return False, out or f"Exit-Code {r.returncode}"
            return True, out
        except subprocess.TimeoutExpired:
            return False, f"{cmd[0]} timed out."
        except Exception as e:
            return False, str(e)

    def _parse_upgradable_packages(self, output: str) -> list[dict]:
        packages = []
        for raw in (output or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("Listing...") or "/" not in line:
                continue
            name, rest = line.split("/", 1)
            parts = rest.split()
            if len(parts) < 2:
                continue
            current = ""
            m = re.search(r"\[upgradable from:\s*([^\]]+)\]", line)
            if m:
                current = m.group(1).strip()
            packages.append({
                "name": name,
                "source": parts[0],
                "candidate_version": parts[1],
                "current_version": current,
            })
        return packages

    def _apt_list_upgradable(self) -> tuple[bool, str, list[dict]]:
        apt = shutil.which("apt")
        if not apt:
            return False, "apt is not installed.", []
        ok, out = self._run_system_cmd([apt, "list", "--upgradable"], timeout=90)
        return ok, out, self._parse_upgradable_packages(out if ok else "")

    def check_system_updates(self) -> dict:
        if not shutil.which("apt-get"):
            state = self._set_system_state(
                running=False, mode="scan", ok=False,
                error="apt-get is not installed.", packages=[], count=0)
            return {"ok": False, **state}
        if not self._system_update_lock.acquire(blocking=False):
            return {**self._system_state(), "ok": False,
                    "error": "A Raspberry update scan or install is already running."}
        try:
            self._set_system_state(
                running=True, mode="scan", ok=None, error="", output="")
            apt_get = shutil.which("apt-get") or "apt-get"
            ok, update_out = self._run_system_cmd(
                ["sudo", "-n", apt_get, "update"], timeout=180)
            if not ok:
                state = self._set_system_state(
                    running=False, ok=False, error=update_out,
                    output=update_out)
                return {"ok": False, **state}

            list_ok, list_out, packages = self._apt_list_upgradable()
            if not list_ok:
                state = self._set_system_state(
                    running=False, ok=False, error=list_out,
                    output=f"{update_out}\n\n{list_out}".strip())
                return {"ok": False, **state}

            state = self._set_system_state(
                running=False, mode="scan", ok=True, error="",
                packages=packages, count=len(packages),
                checked_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                output=f"{update_out}\n\n{list_out}".strip(),
                reboot_required=Path("/var/run/reboot-required").exists())
            return {"ok": True, **state}
        finally:
            self._system_update_lock.release()

    def system_update_status(self) -> dict:
        return {"ok": True, **self._system_state()}

    def install_system_updates(self) -> dict:
        if not shutil.which("apt-get"):
            state = self._set_system_state(
                running=False, mode="install", ok=False,
                error="apt-get is not installed.")
            return {"ok": False, **state}
        if not self._system_update_lock.acquire(blocking=False):
            return {**self._system_state(), "ok": False,
                    "error": "A Raspberry update scan or install is already running."}

        apt_get = shutil.which("apt-get") or "apt-get"
        self._set_system_state(
            running=True, mode="install", ok=None, error="", output="")

        def worker():
            outputs = []
            try:
                for cmd, timeout in (
                    (["sudo", "-n", apt_get, "update"], 180),
                    (["sudo", "-n", apt_get, "-y", "upgrade"], 1800),
                    (["sudo", "-n", apt_get, "-y", "autoremove"], 600),
                ):
                    ok, out = self._run_system_cmd(cmd, timeout=timeout)
                    outputs.append(f"$ {' '.join(cmd)}\n{out}".strip())
                    if not ok:
                        self._set_system_state(
                            running=False, ok=False, error=out,
                            output="\n\n".join(outputs))
                        return

                list_ok, list_out, packages = self._apt_list_upgradable()
                if list_out:
                    outputs.append(f"$ apt list --upgradable\n{list_out}".strip())
                self._set_system_state(
                    running=False, mode="install", ok=list_ok,
                    error="" if list_ok else list_out,
                    packages=packages if list_ok else [],
                    count=len(packages) if list_ok else 0,
                    installed_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                    checked_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                    output="\n\n".join(outputs),
                    reboot_required=Path("/var/run/reboot-required").exists())
            finally:
                self._system_update_lock.release()

        threading.Thread(target=worker, daemon=True).start()
        return {**self._system_state(), "ok": True, "started": True}

    def optimize_boot_view(self) -> dict:
        """Best-effort: Desktop beim Boot optisch in den Hintergrund schieben.

        Bleibt absichtlich im normalen User-Kontext: keine sudo-Aenderungen an
        Desktop- oder Systemdiensten, damit der Button gefahrlos nutzbar ist.
        """
        home = Path(os.path.expanduser("~"))
        share_dir = home / ".local" / "share" / "piscreenportal"
        bin_dir = home / ".local" / "bin"
        cache_dir = home / ".cache" / "piscreenportal"
        steps = []

        def step(name: str, fn):
            try:
                msg = fn()
                steps.append({"step": name, "ok": True, "msg": msg or "OK"})
            except Exception as e:
                steps.append({"step": name, "ok": False, "msg": str(e)})

        step("assets", lambda: self._write_boot_assets(home, share_dir, bin_dir, cache_dir))
        step("pcmanfm", lambda: self._configure_pcmanfm(home, share_dir))
        step("lxpanel", lambda: self._configure_lxpanel(home))
        step("autostart", lambda: self._configure_boot_autostart(home, bin_dir))
        step("wayland-autostart", lambda: self._configure_wayland_autostart(home, bin_dir))
        step("keyring", lambda: self._disable_keyring_prompts(home))

        ok = any(s["ok"] for s in steps) and not all(not s["ok"] for s in steps)
        if ok:
            log("Boot-Desktop-Optimierung angewendet")
        return {"ok": ok, "steps": steps}

    def _write_boot_assets(self, home: Path, share_dir: Path, bin_dir: Path,
                           cache_dir: Path) -> str:
        share_dir.mkdir(parents=True, exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        wallpaper = share_dir / "black-wallpaper.png"
        self._write_black_png(wallpaper)

        cover = share_dir / "boot-cover.html"
        cover.write_text(
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>PiScreenPortal</title>"
            "<style>html,body{margin:0;width:100%;height:100%;"
            "background:#000;cursor:none;overflow:hidden}</style>"
            "</head><body></body></html>\n",
            encoding="utf-8",
        )

        script = bin_dir / "piscreenportal-boot-cover.sh"
        script.write_text(self._boot_cover_script(), encoding="utf-8")
        os.chmod(script, 0o755)
        return f"{wallpaper}, {cover}, {script}"

    def _write_black_png(self, path: Path, size: int = 16) -> None:
        raw = b"".join(b"\x00" + (b"\x00\x00\x00" * size) for _ in range(size))

        def chunk(kind: bytes, data: bytes) -> bytes:
            body = kind + data
            return (struct.pack(">I", len(data)) + body
                    + struct.pack(">I", zlib.crc32(body) & 0xffffffff))

        data = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )
        path.write_bytes(data)

    def _boot_cover_script(self) -> str:
        return """#!/bin/sh
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
export GNOME_KEYRING_CONTROL=
export GNOME_KEYRING_PID=
export SSH_AUTH_SOCK=

LOCK="$HOME/.cache/piscreenportal/boot-cover.pid"
mkdir -p "$HOME/.cache/piscreenportal"
if [ -r "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
  exit 0
fi
echo "$$" > "$LOCK"

xsetroot -solid black >/dev/null 2>&1 || true
pcmanfm --desktop-off >/dev/null 2>&1 || true
lxpanelctl exit >/dev/null 2>&1 || true
pkill -f lxpanel >/dev/null 2>&1 || true
pkill -f wf-panel-pi >/dev/null 2>&1 || true

if command -v unclutter >/dev/null 2>&1; then
  unclutter -idle 0.1 -root >/dev/null 2>&1 &
fi

if pgrep -f "chromium.*chromium-profile-" >/dev/null 2>&1; then
  exit 0
fi

BROWSER=""
for cand in chromium chromium-browser google-chrome; do
  if command -v "$cand" >/dev/null 2>&1; then
    BROWSER="$cand"
    break
  fi
done

if [ -n "$BROWSER" ]; then
  exec "$BROWSER" \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --disable-background-networking \
    --disable-component-update \
    --disable-default-apps \
    --disable-domain-reliability \
    --disable-save-password-bubble \
    --disable-sync \
    --disable-translate \
    --disable-notifications \
    --disable-popup-blocking \
    --no-first-run \
    --no-default-browser-check \
    --password-store=basic \
    --use-mock-keychain \
    --user-data-dir="$HOME/.cache/piscreenportal/boot-cover-profile" \
    --app="file://$HOME/.local/share/piscreenportal/boot-cover.html"
fi
exit 0
"""

    def _configure_pcmanfm(self, home: Path, share_dir: Path) -> str:
        wallpaper = share_dir / "black-wallpaper.png"
        targets = [
            home / ".config" / "pcmanfm" / "LXDE-pi" / "desktop-items-0.conf",
            home / ".config" / "pcmanfm" / "default" / "desktop-items-0.conf",
        ]
        values = {
            "wallpaper": str(wallpaper),
            "wallpaper_mode": "stretch",
            "desktop_bg": "#000000",
            "desktop_fg": "#000000",
            "desktop_shadow": "#000000",
            "show_wm_menu": "0",
            "show_trash": "0",
            "show_mounts": "0",
            "show_documents": "0",
        }
        for target in targets:
            self._set_ini_values(target, "*", values)
        return ", ".join(str(t) for t in targets)

    def _configure_lxpanel(self, home: Path) -> str:
        targets = [
            home / ".config" / "lxpanel" / "LXDE-pi" / "panels" / "panel",
            home / ".config" / "lxpanel" / "default" / "panels" / "panel",
        ]
        for target in targets:
            self._set_lxpanel_values(target)
        return ", ".join(str(t) for t in targets)

    def _configure_boot_autostart(self, home: Path, bin_dir: Path) -> str:
        script = bin_dir / "piscreenportal-boot-cover.sh"

        xdg_dir = home / ".config" / "autostart"
        xdg_dir.mkdir(parents=True, exist_ok=True)
        desktop = xdg_dir / "piscreenportal-boot-cover.desktop"
        desktop.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=PiScreenPortal Boot Cover\n"
            f"Exec={script}\n"
            "NoDisplay=true\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )

        lxsession = home / ".config" / "lxsession" / "LXDE-pi" / "autostart"
        self._append_unique_line(lxsession, f"@{script}")
        return f"{desktop}, {lxsession}"

    def _configure_wayland_autostart(self, home: Path, bin_dir: Path) -> str:
        script = bin_dir / "piscreenportal-boot-cover.sh"
        wayfire = home / ".config" / "wayfire.ini"
        self._set_ini_values(wayfire, "autostart", {
            "piscreenportal_boot_cover": str(script),
        })

        labwc = home / ".config" / "labwc" / "autostart"
        self._append_unique_line(labwc, f"{script} &")
        return f"{wayfire}, {labwc}"

    def _disable_keyring_prompts(self, home: Path) -> str:
        autostart = home / ".config" / "autostart"
        autostart.mkdir(parents=True, exist_ok=True)
        disabled = []
        for name in ("gnome-keyring-pkcs11", "gnome-keyring-secrets",
                     "gnome-keyring-ssh"):
            target = autostart / f"{name}.desktop"
            target.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={name} (disabled)\n"
                "Hidden=true\n"
                "X-GNOME-Autostart-enabled=false\n",
                encoding="utf-8",
            )
            disabled.append(str(target))
        return ", ".join(disabled)

    def _set_ini_values(self, path: Path, section: str, values: dict[str, str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        lines = text.splitlines()
        header = f"[{section}]"
        try:
            start = next(i for i, line in enumerate(lines) if line.strip() == header)
        except StopIteration:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(header)
            start = len(lines) - 1

        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].strip().startswith("[") and lines[i].strip().endswith("]"):
                end = i
                break

        section_lines = lines[start + 1:end]
        seen = set()
        for idx, raw in enumerate(section_lines):
            if "=" not in raw or raw.lstrip().startswith(("#", ";")):
                continue
            key = raw.split("=", 1)[0].strip()
            if key in values:
                section_lines[idx] = f"{key}={values[key]}"
                seen.add(key)
        for key, value in values.items():
            if key not in seen:
                section_lines.append(f"{key}={value}")
        lines = lines[:start + 1] + section_lines + lines[end:]
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _set_lxpanel_values(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        if "Global {" not in text:
            text = "Global {\n}\n" + ("\n" + text if text.strip() else "")

        def replace_global(match):
            body = match.group(1)
            for key, value in {"autohide": "1", "heightwhenhidden": "0"}.items():
                if re.search(rf"(?m)^\s*{re.escape(key)}\s*=", body):
                    body = re.sub(rf"(?m)^(\s*){re.escape(key)}\s*=.*$",
                                  rf"\1{key}={value}", body)
                else:
                    body = body.rstrip() + f"\n    {key}={value}\n"
            return "Global {" + body + "}"

        text = re.sub(r"Global\s*\{(.*?)\}", replace_global, text,
                      count=1, flags=re.S)
        path.write_text(text, encoding="utf-8")

    def _append_unique_line(self, path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        if line not in text.splitlines():
            if text and not text.endswith("\n"):
                text += "\n"
            text += "# PiScreenPortal boot cover\n" + line + "\n"
            path.write_text(text, encoding="utf-8")

    def _reboot_later(self, reason: str, delay: int = 2) -> None:
        def run():
            time.sleep(delay)
            ok, msg = _run_privileged(["sudo", "-n", "reboot"])
            if not ok:
                log(f"Reboot ({reason}) fehlgeschlagen: {msg}")

        threading.Thread(target=run, daemon=True).start()


# ---------------------- WLAN (nmcli) ---------------------- #
def wifi_available() -> bool:
    return shutil.which("nmcli") is not None


def nmcli_split(line: str) -> list[str]:
    """Split nmcli -t output while preserving escaped colons in fields."""
    return [p.replace("\x00", ":") for p in str(line).replace("\\:", "\x00").split(":")]


def wifi_current() -> dict:
    if not wifi_available():
        return {"available": False}
    # aktive Wi-Fi-Verbindung
    ssid = _run(["nmcli", "-t", "-f", "active,ssid,signal", "device", "wifi", "list"])
    active = None
    for line in ssid.splitlines():
        # Format: yes:SSID:Signal
        parts = nmcli_split(line)
        if parts and parts[0] == "yes" and len(parts) >= 2:
            active = {"ssid": parts[1], "signal": parts[2] if len(parts) > 2 else ""}
            break
    device_status = _run(["nmcli", "-t", "-f", "device,type,state,connection",
                          "device", "status"])
    ifaces = []
    for line in device_status.splitlines():
        p = nmcli_split(line)
        if len(p) >= 4:
            ifaces.append({"device": p[0], "type": p[1],
                           "state": p[2], "connection": p[3]})
    return {"available": True, "active": active, "devices": ifaces}


def wifi_scan() -> list:
    if not wifi_available():
        return []
    _run(["nmcli", "device", "wifi", "rescan"], timeout=8)
    out = _run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE",
                "device", "wifi", "list"], timeout=10)
    nets = {}
    for line in out.splitlines():
        parts = nmcli_split(line)
        if len(parts) < 3 or not parts[0]:
            continue
        ssid = parts[0]
        sig = parts[1]
        sec = parts[2] or "offen"
        inuse = (parts[3].strip() == "*") if len(parts) > 3 else False
        # bestes Signal pro SSID behalten
        if ssid not in nets or int(sig or 0) > int(nets[ssid]["signal"] or 0):
            nets[ssid] = {"ssid": ssid, "signal": sig, "security": sec, "in_use": inuse}
    return sorted(nets.values(), key=lambda n: int(n["signal"] or 0), reverse=True)


def wifi_connect(ssid: str, password: str = "") -> tuple:
    if not wifi_available():
        return False, "nmcli nicht verfügbar"
    cmd = ["sudo", "-n", "nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=30)
        ok = out.returncode == 0
        msg = (out.stdout + out.stderr).decode().strip()
        return ok, msg
    except Exception as e:
        return False, str(e)


def wifi_add(ssid: str, password: str, hidden: bool = False,
             autoconnect: bool = True) -> tuple:
    """Fügt ein WLAN-Profil dauerhaft hinzu (verbindet beim nächsten Boot)."""
    if not wifi_available():
        return False, "nmcli nicht verfügbar"
    if not ssid:
        return False, "SSID fehlt"
    con_name = f"pisp-{ssid}"
    # Vorhandenes Profil mit gleichem Namen entfernen
    subprocess.run(["sudo", "-n", "nmcli", "connection", "delete", con_name],
                   capture_output=True, timeout=10)
    cmd = ["sudo", "-n", "nmcli", "connection", "add",
           "type", "wifi", "con-name", con_name,
           "ifname", "*", "ssid", ssid,
           "connection.autoconnect", "yes" if autoconnect else "no"]
    if hidden:
        cmd += ["802-11-wireless.hidden", "yes"]
    if password:
        cmd += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        if r.returncode != 0:
            return False, (r.stderr + r.stdout).decode().strip()
        # Jetzt versuchen hochzuziehen
        up = subprocess.run(["sudo", "-n", "nmcli", "connection", "up", con_name],
                            capture_output=True, timeout=30)
        if up.returncode != 0:
            return True, ("Profil gespeichert. Verbindungsaufbau fehlgeschlagen: "
                          + (up.stderr + up.stdout).decode().strip())
        return True, "WLAN gespeichert und verbunden."
    except Exception as e:
        return False, str(e)


def wifi_saved() -> list:
    """Liste der gespeicherten WLAN-Profile."""
    if not wifi_available():
        return []
    out = _run(["nmcli", "-t", "-f", "NAME,TYPE,AUTOCONNECT",
                "connection", "show"])
    profiles = []
    for line in out.splitlines():
        p = nmcli_split(line)
        if len(p) >= 3 and ("wireless" in p[1] or p[1] == "802-11-wireless"):
            profiles.append({"name": p[0], "autoconnect": p[2] == "yes"})
    return profiles


def wifi_forget(con_name: str) -> tuple:
    if not wifi_available():
        return False, "nmcli nicht verfügbar"
    r = subprocess.run(["sudo", "-n", "nmcli", "connection", "delete", con_name],
                       capture_output=True, timeout=10)
    return r.returncode == 0, (r.stderr + r.stdout).decode().strip()


def wifi_disconnect() -> tuple:
    if not wifi_available():
        return False, "nmcli nicht verfügbar"
    try:
        out = subprocess.run(["nmcli", "radio", "wifi", "off"],
                             capture_output=True, timeout=10)
        subprocess.run(["nmcli", "radio", "wifi", "on"],
                       capture_output=True, timeout=10)
        return out.returncode == 0, "WLAN aus- und wieder eingeschaltet"
    except Exception as e:
        return False, str(e)


# ---------------------- Präsentation (UxPlay AirPlay) ---------------------- #
class PresentationManager:
    """Startet UxPlay als AirPlay-Receiver."""
    def __init__(self):
        self.proc = None
        self.started_at = 0

    def _env(self):
        env = os.environ.copy()
        env.setdefault("DISPLAY", ":0")
        env.setdefault("XAUTHORITY", default_xauthority())
        return env

    def available(self) -> bool:
        return shutil.which("uxplay") is not None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, cfg: dict):
        if not self.available():
            return False, "uxplay ist nicht installiert. Bitte: sudo apt install uxplay"
        if self.is_running():
            return True, "Präsentation läuft bereits"
        pcfg = cfg.get("presentation", {})
        name = pcfg.get("airplay_name") or "PiScreenPortal"
        res = pcfg.get("resolution") or ""
        raw_flags = pcfg.get("extra_flags") or []
        flags = raw_flags if isinstance(raw_flags, list) else []

        cmd = ["uxplay", "-n", name, "-fs"]
        if res and "x" in res:
            try:
                w, h = res.split("x")
                cmd += ["-s", f"{int(w)}x{int(h)}"]
            except Exception:
                pass
        cmd += [str(flag) for flag in flags if str(flag).strip()]

        log(f"Starte Präsentation (UxPlay): {' '.join(cmd)}")
        try:
            self.proc = subprocess.Popen(cmd, env=self._env(),
                                         stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
            self.started_at = int(time.time())
            return True, "Präsentation gestartet"
        except Exception as e:
            log(f"UxPlay Fehler: {e}")
            return False, str(e)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            except Exception as e:
                log(f"UxPlay Stop-Fehler: {e}")
        subprocess.call(["pkill", "-f", "uxplay"], env=self._env())
        self.proc = None
        self.started_at = 0

    def status(self) -> dict:
        return {
            "available": self.available(),
            "running": self.is_running(),
            "started_at": self.started_at,
            "pid": self.proc.pid if self.is_running() else None,
        }


# ---------------------- Kiosk-Manager ---------------------- #
class KioskManager:
    def __init__(self):
        self.processes = {}     # idx -> Popen
        self.reload_threads = {}  # idx -> (thread, stop_event)
        self.unclutter_proc = None
        self.lock = threading.Lock()
        self._watcher_started = False
        self._desired_running = False

    def _start_unclutter(self) -> None:
        if self.unclutter_proc and self.unclutter_proc.poll() is None:
            return
        if not shutil.which("unclutter"):
            log("unclutter nicht installiert - Mauszeiger bleibt sichtbar")
            return
        # unclutter ist ein reines X11-Tool. Unter Wayland hat es keinen
        # Zugriff auf den Cursor der nativen Wayland-Clients und bleibt
        # wirkungslos. Wir starten es dann nicht.
        if session_type() == "wayland":
            log("Sitzungstyp ist Wayland - unclutter kann den Cursor nicht "
                "ausblenden, wird übersprungen. Cursor-Ausblenden erfordert "
                "eine X11-Sitzung.")
            return
        try:
            self.unclutter_proc = subprocess.Popen(
                ["unclutter", "-idle", "0", "-root"],
                env=self._env(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log("unclutter gestartet (Mauszeiger verborgen)")
        except Exception as e:
            log(f"unclutter-Start fehlgeschlagen: {e}")

    def _stop_unclutter(self) -> None:
        if self.unclutter_proc and self.unclutter_proc.poll() is None:
            try:
                self.unclutter_proc.terminate()
            except Exception:
                pass
        self.unclutter_proc = None
        subprocess.call(["pkill", "-f", "unclutter"], env=self._env())

    def _env(self) -> dict:
        env = os.environ.copy()
        env.setdefault("DISPLAY", ":0")
        env.setdefault("XAUTHORITY", default_xauthority())
        env["GNOME_KEYRING_CONTROL"] = ""
        env["GNOME_KEYRING_PID"] = ""
        env["SSH_AUTH_SOCK"] = ""
        return env

    def _apply_rotation(self, output: str, rotation: str) -> None:
        if not output or rotation == "normal":
            return
        try:
            subprocess.run(["xrandr", "--output", output, "--rotate", rotation],
                           env=self._env(), check=False, timeout=5)
        except Exception as e:
            log(f"Rotate-Fehler {output}: {e}")

    def _pick_output(self, screen: dict, monitors: list, idx: int):
        if not monitors:
            return None
        if screen.get("output"):
            for m in monitors:
                if m["name"] == screen["output"]:
                    return m
        return monitors[idx] if idx < len(monitors) else monitors[0]

    def _profile_dir(self, idx: int) -> str:
        d = BASE_DIR / f"chromium-profile-{idx}"
        d.mkdir(exist_ok=True)
        return str(d)

    def _chromium_bin(self) -> str:
        for c in ("chromium-browser", "chromium", "google-chrome"):
            if shutil.which(c):
                return c
        return "chromium-browser"

    def _start_reload_thread(self, idx: int, interval: int, pid: int):
        self._stop_reload_thread(idx)
        if interval <= 0:
            return
        stop = threading.Event()

        def loop():
            while not stop.wait(interval):
                try:
                    subprocess.call(
                        ["xdotool", "search", "--pid", str(pid), "key", "F5"],
                        env=self._env(), stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=5)
                    log(f"Auto-Reload Bildschirm {idx}")
                except Exception as e:
                    log(f"Reload-Fehler {idx}: {e}")

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        self.reload_threads[idx] = (t, stop)

    def _stop_reload_thread(self, idx: int):
        entry = self.reload_threads.pop(idx, None)
        if entry:
            entry[1].set()

    def start_screen(self, idx: int, screen: dict, monitor: dict, flags: list):
        self.stop_screen(idx)
        if not screen.get("enabled", True):
            return
        if not monitor:
            log(f"Kein Monitor für Bildschirm {idx} ({screen.get('name')})")
            return

        self._apply_rotation(monitor["name"], screen.get("rotation", "normal"))

        cmd = [
            self._chromium_bin(),
            "--kiosk",
            f"--user-data-dir={self._profile_dir(idx)}",
            f"--window-position={monitor['x']},{monitor['y']}",
            f"--window-size={monitor['width']},{monitor['height']}",
            f"--app={screen['url']}",
            f"--force-device-scale-factor={screen.get('zoom', 1.0)}",
        ]
        raw_flags = flags if isinstance(flags, list) else []
        cmd.extend([str(flag) for flag in raw_flags if str(flag).strip()])

        log(f"Starte Bildschirm {idx} ({screen.get('name')}) auf {monitor['name']}: {screen['url']}")
        try:
            p = subprocess.Popen(cmd, env=self._env(),
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            with self.lock:
                self.processes[idx] = p
            self._start_reload_thread(idx, int(screen.get("reload_interval", 0) or 0), p.pid)
        except FileNotFoundError:
            log("Chromium nicht gefunden – sudo apt install chromium-browser")

    def stop_screen(self, idx: int):
        self._stop_reload_thread(idx)
        with self.lock:
            p = self.processes.pop(idx, None)
        if p and p.poll() is None:
            try:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
            except Exception as e:
                log(f"Stop-Fehler {idx}: {e}")

    def stop_all(self, keep_desired: bool = False):
        if not keep_desired:
            with self.lock:
                self._desired_running = False
        for idx in list(self.processes.keys()):
            self.stop_screen(idx)
        subprocess.call(["pkill", "-f", "chromium"], env=self._env())
        self._stop_unclutter()

    def start_all(self, cfg: dict | None = None):
        cfg = cfg or load_config()
        with self.lock:
            self._desired_running = True
        monitors = detect_monitors()
        log(f"Erkannte Monitore: {[m['name'] for m in monitors]}")
        # Zuerst alte Prozesse aufräumen, die zu entfernten/deaktivierten
        # Screens gehören (sonst bleiben Zombie-Einträge in self.processes,
        # wenn der User z.B. 3 Screens auf 2 reduziert).
        valid_indices = {i for i, s in enumerate(cfg["screens"])
                         if s.get("enabled", True)}
        with self.lock:
            stale = [i for i in self.processes.keys() if i not in valid_indices]
        for idx in stale:
            self.stop_screen(idx)
        # Mauszeiger ausblenden, wenn mind. ein Screen es verlangt
        if any(s.get("hide_cursor") and s.get("enabled") for s in cfg["screens"]):
            self._start_unclutter()
        else:
            self._stop_unclutter()
        for idx, screen in enumerate(cfg["screens"]):
            mon = self._pick_output(screen, monitors, idx)
            self.start_screen(idx, screen, mon, cfg.get("chromium_flags", []))
        self._ensure_watcher()

    def restart_all(self):
        self.stop_all(keep_desired=True)
        time.sleep(1)
        self.start_all()

    def status(self) -> dict:
        out = {}
        with self.lock:
            for idx, p in self.processes.items():
                out[str(idx)] = {"pid": p.pid, "running": p.poll() is None}
        return out

    def _ensure_watcher(self):
        if self._watcher_started:
            return
        self._watcher_started = True

        def watch():
            while True:
                time.sleep(5)
                c = load_config()
                if not c.get("restart_on_crash"):
                    continue
                with self.lock:
                    desired = self._desired_running
                if not desired:
                    continue
                monitors = detect_monitors()
                for idx, screen in enumerate(c["screens"]):
                    with self.lock:
                        p = self.processes.get(idx)
                    if screen.get("enabled") and (p is None or p.poll() is not None):
                        log(f"Respawn Bildschirm {idx}")
                        mon = self._pick_output(screen, monitors, idx)
                        self.start_screen(idx, screen, mon, c.get("chromium_flags", []))

        threading.Thread(target=watch, daemon=True).start()


manager = KioskManager()
presentation = PresentationManager()
maintenance = MaintenanceManager()
app = Flask(__name__, template_folder=str(BASE_DIR / "templates"),
            static_folder=str(BASE_DIR / "static"))


# ---------------------- Auth (cookie-based session) ---------------------- #
SECRET_FILE = BASE_DIR / ".secret_key"


def _load_secret_key() -> bytes:
    """Persistente SECRET_KEY, damit Sessions Neustarts überleben."""
    if SECRET_FILE.exists():
        try:
            data = SECRET_FILE.read_bytes()
            if len(data) >= 32:
                return data
        except Exception:
            pass
    key = secrets.token_bytes(48)
    try:
        SECRET_FILE.write_bytes(key)
        os.chmod(SECRET_FILE, 0o600)
    except Exception as e:
        log(f"Konnte SECRET_KEY nicht speichern: {e}")
    return key


app.secret_key = _load_secret_key()
app.config.update(
    SESSION_COOKIE_NAME="pisp_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,   # 14 Tage
)


def _auth_cfg() -> dict:
    return load_config().get("auth", {}) or {}


def auth_enabled() -> bool:
    return bool(_auth_cfg().get("enabled"))


def _credentials_match(username: str, password: str) -> bool:
    """Zeitkonstanter Vergleich der Anmeldedaten.

    Wichtig: ein leer gespeichertes Passwort wird NIE akzeptiert - sonst
    könnte sich jeder mit dem Username und leerem PW einloggen.
    """
    cfg = _auth_cfg()
    exp_u = cfg.get("username") or ""
    exp_p = cfg.get("password") or ""
    if not exp_u or not exp_p:
        return False
    return (hmac.compare_digest(exp_u.encode(), (username or "").encode())
            and hmac.compare_digest(exp_p.encode(), (password or "").encode()))


def is_logged_in() -> bool:
    if not auth_enabled():
        return True
    return session.get("user") == _auth_cfg().get("username")


def _wants_json() -> bool:
    """Heuristik: wurde der Request vom JS-Frontend abgesetzt?"""
    if request.path.startswith("/api/"):
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def requires_auth(f):
    @wraps(f)
    def deco(*a, **kw):
        if is_logged_in():
            return f(*a, **kw)
        if _wants_json():
            return jsonify({"ok": False, "error": "auth_required"}), 401
        return redirect(url_for("login", next=request.full_path or "/"))
    return deco


# ---------------------- Routes ---------------------- #
@app.route("/")
@requires_auth
def index():
    return render_template("index.html")


# ------- Login / Logout -------
def _safe_next(target: str) -> str:
    """Nur lokale Pfade als next= akzeptieren (Open-Redirect verhindern)."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return url_for("index")
    return target


@app.route("/login", methods=["GET", "POST"])
def login():
    # Falls Auth aus ist, gibt es keinen Login – direkt weiter
    if not auth_enabled():
        return redirect(url_for("index"))
    if is_logged_in():
        return redirect(_safe_next(request.args.get("next", "")))

    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if _credentials_match(username, password):
            session.clear()
            session.permanent = True
            session["user"] = _auth_cfg().get("username")
            session["login_at"] = int(time.time())
            log(f"Login erfolgreich: {username} von {request.remote_addr}")
            return redirect(_safe_next(request.form.get("next") or
                                       request.args.get("next", "")))
        # Minimal delay gegen Brute-Force
        time.sleep(0.8)
        log(f"Login fehlgeschlagen: {username or '(leer)'} von {request.remote_addr}")
        error = "invalid"

    return render_template(
        "login.html",
        error=error,
        next=request.args.get("next", ""),
        username=_auth_cfg().get("username") or "",
    )


@app.route("/logout", methods=["GET", "POST"])
def logout():
    user = session.get("user")
    session.clear()
    if user:
        log(f"Logout: {user}")
    if _wants_json():
        return jsonify({"ok": True})
    return redirect(url_for("login"))


@app.route("/api/auth/status")
def api_auth_status():
    return jsonify({
        "enabled": auth_enabled(),
        "logged_in": is_logged_in(),
        "user": session.get("user") if is_logged_in() else None,
    })


@app.route("/api/config", methods=["GET", "POST"])
@requires_auth
def api_config():
    if request.method == "GET":
        return jsonify(load_config())
    new_cfg, error = json_payload()
    if error:
        return jsonify({"ok": False, "error": error}), 400
    new_cfg, error = validate_config_payload(new_cfg)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    save_config(new_cfg)
    log("Config gespeichert")
    return jsonify({"ok": True})


@app.route("/api/config/export")
@requires_auth
def api_config_export():
    payload = json.dumps(load_config(), indent=2, ensure_ascii=False)
    buf = io.BytesIO(payload.encode("utf-8"))
    return send_file(buf, as_attachment=True, mimetype="application/json",
                     download_name="piscreenportal-config.json")


@app.route("/api/config/import", methods=["POST"])
@requires_auth
def api_config_import():
    try:
        data, error = json_payload()
        if error:
            raise ValueError(error)
        data, error = validate_config_payload(data)
        if error:
            raise ValueError(error)
        save_config(data)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/monitors")
@requires_auth
def api_monitors():
    return jsonify(detect_monitors())


@app.route("/api/services")
@requires_auth
def api_services():
    return jsonify(services_status())


@app.route("/api/power")
@requires_auth
def api_power():
    return jsonify(power_status())


@app.route("/api/power/disable-all", methods=["POST"])
@requires_auth
def api_power_disable_all():
    result = _force_disable_power_save()
    ok = all(s.get("ok") for s in result.get("steps", [])) or False
    return jsonify({"ok": ok, **result})


@app.route("/api/maintenance/status")
@requires_auth
def api_maintenance_status():
    return jsonify(maintenance.status())


@app.route("/api/maintenance/update", methods=["POST"])
@requires_auth
def api_maintenance_update():
    result = maintenance.update_from_git_and_reboot()
    status = 200 if result.get("ok") else 500
    return jsonify(result), status


@app.route("/api/maintenance/check-updates", methods=["POST"])
@requires_auth
def api_maintenance_check_updates():
    result = maintenance.check_for_updates()
    status = 200 if result.get("ok") else 500
    return jsonify(result), status


@app.route("/api/maintenance/system-updates/status")
@requires_auth
def api_maintenance_system_updates_status():
    return jsonify(maintenance.system_update_status())


@app.route("/api/maintenance/system-updates/check", methods=["POST"])
@requires_auth
def api_maintenance_system_updates_check():
    result = maintenance.check_system_updates()
    status = 200 if result.get("ok") else 500
    return jsonify(result), status


@app.route("/api/maintenance/system-updates/install", methods=["POST"])
@requires_auth
def api_maintenance_system_updates_install():
    result = maintenance.install_system_updates()
    status = 200 if result.get("ok") else 500
    return jsonify(result), status


@app.route("/api/maintenance/optimize-boot", methods=["POST"])
@requires_auth
def api_maintenance_optimize_boot():
    result = maintenance.optimize_boot_view()
    status = 200 if result.get("ok") else 500
    return jsonify(result), status


@app.route("/api/status")
@requires_auth
def api_status():
    return jsonify({
        "processes": manager.status(),
        "monitors": detect_monitors(),
        "system": system_info(),
    })


def _reload_chromium_windows() -> bool:
    """F5 an jedes Chromium-Fenster senden. Gibt True zurück, wenn mindestens
    ein Fenster angetriggert wurde."""
    if not shutil.which("xdotool"):
        log("Reload: xdotool ist nicht installiert")
        return False
    env = self_env()
    win_ids = []
    # Mehrere Klassen durchprobieren (verschiedene Chromium-Varianten)
    for cls in ("chromium", "chromium-browser", "Chromium", "Google-chrome"):
        try:
            out = subprocess.check_output(
                ["xdotool", "search", "--class", cls],
                env=env, stderr=subprocess.DEVNULL, timeout=5,
            ).decode().strip()
            for line in out.splitlines():
                line = line.strip()
                if line and line not in win_ids:
                    win_ids.append(line)
        except subprocess.CalledProcessError:
            # xdotool exitet != 0 wenn nichts gefunden - kein Fehler
            pass
        except Exception as e:
            log(f"xdotool search {cls} Fehler: {e}")

    if not win_ids:
        log("Reload: Keine Chromium-Fenster gefunden")
        return False

    sent = 0
    for wid in win_ids:
        try:
            r = subprocess.run(
                ["xdotool", "key", "--window", wid, "F5"],
                env=env, capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                sent += 1
        except Exception as e:
            log(f"xdotool key {wid} Fehler: {e}")
    log(f"Reload: F5 an {sent}/{len(win_ids)} Fenster gesendet")
    return sent > 0


def _run_privileged(cmd: list) -> tuple[bool, str]:
    """Führt ein privilegiertes Kommando aus und gibt (ok, msg) zurück."""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        if r.returncode != 0:
            err = (r.stderr + r.stdout).decode("utf-8", "ignore").strip()
            return False, err or f"Exit-Code {r.returncode}"
        return True, ""
    except FileNotFoundError as e:
        return False, f"Programm nicht gefunden: {e.filename}"
    except subprocess.TimeoutExpired:
        # Bei reboot/shutdown ist ein Timeout normal - die Maschine geht runter
        return True, "Kommando gestartet"
    except Exception as e:
        return False, str(e)


@app.route("/api/action/<name>", methods=["POST"])
@requires_auth
def api_action(name):
    try:
        if name == "start":
            manager.start_all()
        elif name == "stop":
            manager.stop_all()
        elif name == "restart":
            manager.restart_all()
        elif name == "reload":
            ok = _reload_chromium_windows()
            if not ok:
                return jsonify({"ok": False,
                                "error": "Kein Chromium-Fenster gefunden. "
                                         "Läuft der Kiosk und ist xdotool "
                                         "installiert?"}), 500
        elif name == "reboot":
            ok, msg = _run_privileged(["sudo", "-n", "reboot"])
            if not ok:
                return jsonify({"ok": False,
                                "error": f"Reboot fehlgeschlagen: {msg}"}), 500
        elif name == "shutdown":
            ok, msg = _run_privileged(["sudo", "-n", "shutdown", "-h", "now"])
            if not ok:
                return jsonify({"ok": False,
                                "error": f"Shutdown fehlgeschlagen: {msg}"}), 500
        elif name in ("screen-off", "screen-on"):
            ok, msg = set_monitor_power(name == "screen-on")
            if not ok:
                return jsonify({"ok": False, "error": msg}), 500
            return jsonify({"ok": True, "method": msg})
        else:
            return jsonify({"ok": False, "error": "Unbekannt"}), 400
    except Exception as e:
        log(f"api_action {name}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


def self_env():
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XAUTHORITY", default_xauthority())
    return env


def _run_monitor_power_cmd(cmd: list[str], env: dict | None = None) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, timeout=8)
        msg = (r.stdout + r.stderr).decode("utf-8", "ignore").strip()
        if r.returncode != 0:
            return False, msg or f"exit code {r.returncode}"
        return True, msg
    except FileNotFoundError:
        return False, f"{cmd[0]} is not installed"
    except subprocess.TimeoutExpired:
        return False, f"{cmd[0]} timed out"
    except Exception as e:
        return False, str(e)


def _monitor_power_xset(power_on: bool) -> tuple[bool, str]:
    env = self_env()
    commands = (
        [["xset", "dpms", "force", "on"],
         ["xset", "s", "off"],
         ["xset", "-dpms"],
         ["xset", "s", "noblank"]]
        if power_on else
        [["xset", "+dpms"],
         ["xset", "dpms", "force", "off"]]
    )
    messages = []
    for cmd in commands:
        ok, msg = _run_monitor_power_cmd(cmd, env=env)
        if msg:
            messages.append(msg)
        if not ok:
            return False, msg
    return True, "; ".join(messages)


def _monitor_power_vcgencmd(power_on: bool) -> tuple[bool, str]:
    value = "1" if power_on else "0"
    return _run_monitor_power_cmd(["vcgencmd", "display_power", value])


def set_monitor_power(power_on: bool) -> tuple[bool, str]:
    attempts = []
    sess = session_type()
    methods = []
    if sess == "x11" and shutil.which("xset"):
        methods.append(("xset", _monitor_power_xset))
    if shutil.which("vcgencmd"):
        methods.append(("vcgencmd", _monitor_power_vcgencmd))
    if shutil.which("xset") and not any(name == "xset" for name, _ in methods):
        methods.append(("xset", _monitor_power_xset))

    if not methods:
        return False, "No monitor power tool found (xset or vcgencmd)."

    for name, fn in methods:
        ok, msg = fn(power_on)
        if ok:
            return True, name
        attempts.append(f"{name}: {msg}")
    return False, " | ".join(attempts)


@app.route("/api/wifi")
@requires_auth
def api_wifi():
    return jsonify({
        "current": wifi_current(),
        "networks": wifi_scan(),
        "saved": wifi_saved(),
    })


@app.route("/api/wifi/add", methods=["POST"])
@requires_auth
def api_wifi_add():
    data, error = json_payload()
    if error:
        return jsonify({"ok": False, "error": error}), 400
    ssid = (data.get("ssid") or "").strip()
    password = data.get("password") or ""
    hidden = bool(data.get("hidden"))
    autoconnect = data.get("autoconnect", True)
    ok, msg = wifi_add(ssid, password, hidden, autoconnect)
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/wifi/forget", methods=["POST"])
@requires_auth
def api_wifi_forget():
    data, error = json_payload()
    if error:
        return jsonify({"ok": False, "error": error}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name fehlt"}), 400
    ok, msg = wifi_forget(name)
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/wifi/connect", methods=["POST"])
@requires_auth
def api_wifi_connect():
    data, error = json_payload()
    if error:
        return jsonify({"ok": False, "error": error}), 400
    ssid = (data.get("ssid") or "").strip()
    password = data.get("password") or ""
    if not ssid:
        return jsonify({"ok": False, "error": "SSID fehlt"}), 400
    ok, msg = wifi_connect(ssid, password)
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/wifi/reset", methods=["POST"])
@requires_auth
def api_wifi_reset():
    ok, msg = wifi_disconnect()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/qrcode")
@requires_auth
def api_qrcode():
    if qrcode is None:
        return Response("qrcode-Paket fehlt", 500)
    cfg = load_config()
    text = request.args.get("text") or f"http://{get_ip()}:{cfg.get('port', 2411)}"
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


@app.route("/api/presentation/status")
@requires_auth
def api_presentation_status():
    return jsonify(presentation.status())


@app.route("/api/presentation/start", methods=["POST"])
@requires_auth
def api_presentation_start():
    cfg = load_config()
    pcfg = cfg.get("presentation", {})
    if pcfg.get("stop_kiosk_while_active", True):
        manager.stop_all()
        time.sleep(0.5)
    ok, msg = presentation.start(cfg)
    return jsonify({"ok": ok, "message": msg, "status": presentation.status()})


@app.route("/api/presentation/stop", methods=["POST"])
@requires_auth
def api_presentation_stop():
    presentation.stop()
    cfg = load_config()
    pcfg = cfg.get("presentation", {})
    if pcfg.get("stop_kiosk_while_active", True):
        # Kiosk wieder anwerfen
        time.sleep(0.3)
        manager.start_all(cfg)
    return jsonify({"ok": True, "status": presentation.status()})


@app.route("/api/logs")
@requires_auth
def api_logs():
    if not LOG_FILE.exists():
        return ""
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        text = f.read()[-20000:]
    return logs_for_language(text, request.args.get("lang", ""))


# ---------------------- Boot ---------------------- #
def boot_start():
    cfg = load_config()
    if cfg.get("auto_start"):
        for _ in range(30):
            if detect_monitors():
                break
            time.sleep(1)
        # Entfernt ggf. den sehr frueh gestarteten schwarzen Boot-Cover-Browser,
        # bevor die echten Kiosk-Fenster aufgebaut werden.
        manager.stop_all()
        time.sleep(0.3)
        manager.start_all(cfg)


if __name__ == "__main__":
    cfg = load_config()
    if not CONFIG_FILE.exists():
        save_config(cfg)
    threading.Thread(target=boot_start, daemon=True).start()
    maintenance.start()
    app.run(host="0.0.0.0", port=cfg.get("port", 2411),
            debug=False, threaded=True)
