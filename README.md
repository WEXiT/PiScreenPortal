# PiScreenPortal

> Web-based multi-monitor kiosk controller with AirPlay presentation mode for Raspberry Pi.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](#license)
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi-red)](https://www.raspberrypi.com/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)

PiScreenPortal turns a Raspberry Pi into a configurable digital signage and meeting-room appliance. Every monitor can show a different URL in full-screen Chromium kiosk mode, controlled entirely from a clean browser interface on any device in the network. A built-in AirPlay receiver (UxPlay) lets anyone mirror an iPhone, iPad or Mac to the display for ad-hoc presentations.

---

## Features

- **Multi-screen kiosk** – one URL per HDMI output, with rotation, zoom, auto-reload and cursor-hiding
- **Web interface on port 2411** – manage everything from your phone or laptop
- **AirPlay receiver** – iPhone/iPad/Mac users tap *Screen Mirroring* → presentation in seconds
- **Wi-Fi management** – scan, connect, manually add hidden SSIDs, list and remove saved profiles
- **System monitoring** – CPU temperature, load, RAM, disk, logs, running processes
- **Auto-start on boot**, Chromium crash-recovery, configurable Chromium flags
- **Bilingual UI** – English (default) and German, switchable in the header
- **Password protection** (HTTP Basic Auth) for the web interface
- **Import / export configuration** as JSON

## Requirements

- Raspberry Pi 4 or 5
- Raspberry Pi OS 64-bit (Bookworm or Trixie), *with desktop*
- X11 session (Wayland is **not** supported – instructions below)
- One or more HDMI monitors

---

## 1. Prepare the Raspberry Pi

Flash the SD card with the official **Raspberry Pi Imager**, choose *Raspberry Pi OS (64-bit) with desktop*. In the imager's *advanced settings*:

- Hostname: `pi-kiosk` (or any name you like)
- Enable SSH with password
- Configure Wi-Fi (SSID + password)
- Username: `admin`, set a password

Boot the Pi.

On the Pi, run once:

```bash
sudo raspi-config
```

Set these two options (both are mandatory):

1. **System Options → Boot / Auto Login → Desktop Autologin**
2. **Advanced Options → Wayland → X11**

Choose *Finish* → reboot.

---

## 2. Copy the project to the Pi

### macOS / Linux

```bash
scp -r /path/to/rasp/ admin@<PI-IP>:~/
```

### Windows

**WinSCP (graphical):**

1. Install [WinSCP](https://winscp.net)
2. New session → protocol **SCP**, host = Pi IP, user `admin`, password
3. Drag the local `rasp` folder to the Pi's home directory

**PowerShell:** Windows 10/11 ships with `scp`:

```powershell
scp -r C:\path\to\rasp admin@<PI-IP>:~/
```

---

## 3. Install

SSH into the Pi and run the installer:

```bash
ssh admin@<PI-IP>
cd ~/rasp
chmod +x install.sh
./install.sh
```

The installer handles everything:

- Chromium (kiosk browser)
- `unclutter`, `xrandr`, `xdotool`, Avahi
- UxPlay (AirPlay receiver) – from apt or built from source
- Python virtual environment + Flask
- Sudo rules for `reboot`, `shutdown`, `nmcli`
- systemd service (autostart at boot)
- Desktop shortcut on the Pi

---

## 4. Start and open the web interface

```bash
sudo systemctl start pi-kiosk
```

Open in a browser:

- **From another device on the same network:** `http://<PI-IP>:2411`
- **Directly on the Pi:** double-click the *PiScreenPortal* icon on the desktop

That's it. Configure your screens under the *Screens* tab and hit *Save and apply*.

---

## Using presentation mode

1. Open the **Presentation** tab → *Start presentation*
2. On **iPhone / iPad / Mac**: Control Center → *Screen Mirroring* → select `PiScreenPortal`
3. When done, click *Stop presentation* – the kiosk resumes automatically

For Windows or Android (no native AirPlay) use [Deskreen](https://www.deskreen.com) as an alternative receiver.

---

## Updates

After changing project files on your machine, just re-upload and restart the service:

```bash
scp -r /path/to/rasp/ admin@<PI-IP>:~/
ssh admin@<PI-IP> "sudo systemctl restart pi-kiosk"
```

## Service management

```bash
sudo systemctl status pi-kiosk      # is it running?
sudo systemctl restart pi-kiosk     # restart
sudo systemctl stop pi-kiosk        # stop
sudo systemctl disable pi-kiosk     # disable auto-start
journalctl -u pi-kiosk -f           # live logs
tail -f ~/rasp/kiosk.log            # application log
```

## Configuration file

Stored at `~/rasp/config.json`. You can also export/import it via the *Settings* tab.

## Troubleshooting

| Problem | Fix |
|---|---|
| Web interface not reachable | `sudo systemctl status pi-kiosk`; check `journalctl -u pi-kiosk -n 50` |
| No monitors detected | Make sure X11 is active: `echo $XDG_SESSION_TYPE` should print `x11` |
| Chromium on wrong monitor | In *Screens* tab, set the output explicitly (`HDMI-1`, `HDMI-2`) |
| AirPlay device not visible | `systemctl status avahi-daemon` must be running; check firewall |
| Lost password | Edit `~/rasp/config.json` → set `auth.enabled` to `false`, restart service |

## Uninstall

```bash
sudo systemctl disable --now pi-kiosk
sudo rm /etc/systemd/system/pi-kiosk.service
sudo rm /etc/sudoers.d/pi-kiosk
sudo systemctl daemon-reload
rm -rf ~/rasp ~/Desktop/PiScreenPortal.desktop
```

---

## Technology stack

- **Backend:** Python 3 + Flask (single-file `app.py`)
- **Frontend:** vanilla JS, no build step, custom lightweight i18n
- **Kiosk:** Chromium with `--kiosk` and `--window-position`
- **AirPlay:** [UxPlay](https://github.com/FDH2/UxPlay)
- **Monitor layout:** `xrandr`
- **Wi-Fi:** `nmcli` (NetworkManager)

## Project structure

```
rasp/
├── app.py              # Flask backend + kiosk manager
├── requirements.txt
├── install.sh          # one-shot installer
├── pi-kiosk.service    # systemd unit template
├── static/
│   ├── app.js          # frontend logic
│   ├── i18n.js         # translations (en, de)
│   └── style.css
└── templates/
    └── index.html
```

## License

MIT © Dennis Reuther 2026
