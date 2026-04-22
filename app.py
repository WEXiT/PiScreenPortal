#!/usr/bin/env python3
"""
PiScreenPortal: Web-Interface zum Steuern mehrerer Chromium-Kiosk-Fenster
auf einem Raspberry Pi mit mehreren Monitoren.
"""
import io
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from functools import wraps
from pathlib import Path

from flask import (Flask, Response, jsonify, render_template, request,
                   send_file)

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


# ---------------------- Auth ---------------------- #
def check_auth(u: str, p: str) -> bool:
    cfg = load_config().get("auth", {})
    return u == cfg.get("username") and p == cfg.get("password")


def requires_auth(f):
    @wraps(f)
    def deco(*a, **kw):
        cfg = load_config().get("auth", {})
        if not cfg.get("enabled"):
            return f(*a, **kw)
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response("Login erforderlich", 401,
                            {"WWW-Authenticate": 'Basic realm="PiScreenPortal"'})
        return f(*a, **kw)
    return deco


# ---------------------- Routes ---------------------- #
@app.route("/")
@requires_auth
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET", "POST"])
@requires_auth
def api_config():
    if request.method == "GET":
        return jsonify(load_config())
    new_cfg = request.get_json(force=True)
    if not isinstance(new_cfg, dict) or "screens" not in new_cfg:
        return jsonify({"ok": False, "error": "Ungültige Config"}), 400
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


@app.route("/api/status")
@requires_auth
def api_status():
    return jsonify({
        "processes": manager.status(),
        "monitors": detect_monitors(),
        "system": system_info(),
    })


@app.route("/api/action/<name>", methods=["POST"])
@requires_auth
def api_action(name):
    if name == "start":
        manager.start_all()
    elif name == "stop":
        manager.stop_all()
    elif name == "restart":
        manager.restart_all()
    elif name == "reload":
        env = self_env()
        subprocess.call(["xdotool", "search", "--class", "chromium",
                         "key", "--window", "%@", "F5"], env=env)
    elif name == "reboot":
        subprocess.Popen(["sudo", "reboot"])
    elif name == "shutdown":
        subprocess.Popen(["sudo", "shutdown", "-h", "now"])
    elif name == "screen-off":
        subprocess.call(["xset", "dpms", "force", "off"], env=self_env())
    elif name == "screen-on":
        subprocess.call(["xset", "dpms", "force", "on"], env=self_env())
    else:
        return jsonify({"ok": False, "error": "Unbekannt"}), 400
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
