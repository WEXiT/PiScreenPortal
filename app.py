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
import secrets
import shutil
import socket
import subprocess
import threading
import time
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
    "--password-store=basic",
    "--use-mock-keychain",
    "--no-first-run",
]


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            # Kritische Flags sicherstellen (Keyring-Dialog, First-Run usw.)
            flags = cfg.get("chromium_flags") or []
            for req in REQUIRED_FLAGS:
                if req not in flags:
                    flags.append(req)
            cfg["chromium_flags"] = flags
            return cfg
        except Exception as e:
            log(f"Config-Fehler, lade Defaults: {e}")
    return json.loads(json.dumps(DEFAULT_CONFIG))


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


# ---------------------- Monitor-Erkennung ---------------------- #
def detect_monitors() -> list:
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XAUTHORITY", f"/home/{os.environ.get('USER', 'pi')}/.Xauthority")
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
                parts = line.split(":")
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


# ---------------------- WLAN (nmcli) ---------------------- #
def wifi_available() -> bool:
    return shutil.which("nmcli") is not None


def wifi_current() -> dict:
    if not wifi_available():
        return {"available": False}
    # aktive Wi-Fi-Verbindung
    ssid = _run(["nmcli", "-t", "-f", "active,ssid,signal", "device", "wifi", "list"])
    active = None
    for line in ssid.splitlines():
        # Format: yes:SSID:Signal
        parts = line.split(":")
        if parts and parts[0] == "yes" and len(parts) >= 2:
            active = {"ssid": parts[1], "signal": parts[2] if len(parts) > 2 else ""}
            break
    device_status = _run(["nmcli", "-t", "-f", "device,type,state,connection",
                          "device", "status"])
    ifaces = []
    for line in device_status.splitlines():
        p = line.split(":")
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
        # Escapes in nmcli -t: ":" in feldern als "\:"
        parts = line.replace("\\:", "\x00").split(":")
        parts = [p.replace("\x00", ":") for p in parts]
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
           "ifname", "wlan0", "ssid", ssid,
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
        p = line.split(":")
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
        env.setdefault("XAUTHORITY", f"/home/{os.environ.get('USER', 'pi')}/.Xauthority")
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
        flags = pcfg.get("extra_flags") or []

        cmd = ["uxplay", "-n", name, "-fs"]
        if res and "x" in res:
            try:
                w, h = res.split("x")
                cmd += ["-s", f"{int(w)}x{int(h)}"]
            except Exception:
                pass
        cmd += list(flags)

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
        env.setdefault("XAUTHORITY", f"/home/{os.environ.get('USER', 'pi')}/.Xauthority")
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
        cmd.extend(flags or [])

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

    def stop_all(self):
        for idx in list(self.processes.keys()):
            self.stop_screen(idx)
        subprocess.call(["pkill", "-f", "chromium"], env=self._env())
        self._stop_unclutter()

    def start_all(self, cfg: dict | None = None):
        cfg = cfg or load_config()
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
        self.stop_all()
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
    new_cfg = request.get_json(force=True)
    if not isinstance(new_cfg, dict) or "screens" not in new_cfg:
        return jsonify({"ok": False, "error": "Ungültige Config"}), 400
    # Sicherheitscheck: Auth darf nicht mit leerem Passwort aktiviert werden
    auth = (new_cfg.get("auth") or {})
    if auth.get("enabled") and (not auth.get("username") or not auth.get("password")):
        return jsonify({
            "ok": False,
            "error": "Wenn der Zugangsschutz aktiv ist, müssen Benutzername "
                     "und Passwort gesetzt sein.",
        }), 400
    save_config(new_cfg)
    log("Config gespeichert")
    return jsonify({"ok": True})


@app.route("/api/config/export")
@requires_auth
def api_config_export():
    if not CONFIG_FILE.exists():
        save_config(load_config())
    return send_file(CONFIG_FILE, as_attachment=True,
                     download_name="pi-kiosk-config.json")


@app.route("/api/config/import", methods=["POST"])
@requires_auth
def api_config_import():
    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict) or "screens" not in data:
            raise ValueError("Invalid")
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
            if not shutil.which("xset"):
                return jsonify({"ok": False,
                                "error": "xset ist nicht installiert."}), 500
            # Hinweis: xset funktioniert nur unter X11 bzw. XWayland. Unter
            # reinem Wayland hat DPMS-Steuerung auf diese Weise keinen Effekt.
            state = "off" if name == "screen-off" else "on"
            try:
                subprocess.check_call(["xset", "dpms", "force", state],
                                      env=self_env(),
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL,
                                      timeout=5)
            except subprocess.CalledProcessError as e:
                return jsonify({"ok": False,
                                "error": f"xset: Exit-Code {e.returncode}. "
                                         "Unter Wayland evtl. nicht "
                                         "unterstützt."}), 500
        else:
            return jsonify({"ok": False, "error": "Unbekannt"}), 400
    except Exception as e:
        log(f"api_action {name}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


def self_env():
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XAUTHORITY", f"/home/{os.environ.get('USER', 'pi')}/.Xauthority")
    return env


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
    data = request.get_json(force=True) or {}
    ssid = (data.get("ssid") or "").strip()
    password = data.get("password") or ""
    hidden = bool(data.get("hidden"))
    autoconnect = data.get("autoconnect", True)
    ok, msg = wifi_add(ssid, password, hidden, autoconnect)
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/wifi/forget", methods=["POST"])
@requires_auth
def api_wifi_forget():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name fehlt"}), 400
    ok, msg = wifi_forget(name)
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/wifi/connect", methods=["POST"])
@requires_auth
def api_wifi_connect():
    data = request.get_json(force=True) or {}
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
        return f.read()[-20000:]


# ---------------------- Boot ---------------------- #
def boot_start():
    cfg = load_config()
    if cfg.get("auto_start"):
        for _ in range(30):
            if detect_monitors():
                break
            time.sleep(1)
        manager.start_all(cfg)


if __name__ == "__main__":
    cfg = load_config()
    if not CONFIG_FILE.exists():
        save_config(cfg)
    threading.Thread(target=boot_start, daemon=True).start()
    app.run(host="0.0.0.0", port=cfg.get("port", 2411),
            debug=False, threaded=True)
