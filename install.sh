#!/usr/bin/env bash
# PiScreenPortal Installer für Raspberry Pi OS 64-bit (Bookworm)
# Installiert ALLES was fehlt automatisch.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"

echo "=========================================="
echo " PiScreenPortal Installer"
echo " Verzeichnis: $DIR"
echo " Benutzer:    $USER_NAME"
echo "=========================================="

need_cmd() {
    command -v "$1" >/dev/null 2>&1
}

apt_install() {
    local pkgs=()
    for pkg in "$@"; do
        if ! dpkg -s "$pkg" >/dev/null 2>&1; then
            pkgs+=("$pkg")
        fi
    done
    if [ ${#pkgs[@]} -gt 0 ]; then
        echo ">>> Installiere: ${pkgs[*]}"
        sudo apt install -y "${pkgs[@]}"
    else
        echo ">>> Bereits installiert: $*"
    fi
}

# --------------------------------------------------
# 1. System aktualisieren
# --------------------------------------------------
echo ">>> [1/7] apt update"
sudo apt update

# --------------------------------------------------
# 2. Basispakete
# --------------------------------------------------
echo ">>> [2/7] Basispakete"
apt_install python3 python3-venv python3-pip python3-dev \
            git curl wget ca-certificates

# --------------------------------------------------
# 3. X11 & Kiosk-Tools
# --------------------------------------------------
echo ">>> [3/7] Kiosk-Werkzeuge"
# Basiswerkzeuge zuerst (ohne Chromium)
apt_install x11-xserver-utils xdotool unclutter fonts-dejavu \
            network-manager avahi-daemon avahi-utils

# Chromium: verschiedene Paketnamen je nach Distribution durchprobieren
CHROMIUM_PKG=""
for cand in chromium chromium-browser; do
    if sudo apt-get install -y "$cand" 2>/dev/null; then
        CHROMIUM_PKG="$cand"
        echo ">>> Chromium installiert als Paket '$cand'"
        break
    fi
done
if [ -z "$CHROMIUM_PKG" ]; then
    echo "!!! Chromium konnte nicht aus den Paketquellen installiert werden."
    echo "!!! Bitte manuell installieren, z. B.: sudo apt install chromium"
    exit 1
fi

# --------------------------------------------------
# 4. UxPlay (AirPlay-Empfänger) - optional
# --------------------------------------------------
echo ">>> [4/7] UxPlay (AirPlay)"
if need_cmd uxplay; then
    echo ">>> uxplay bereits vorhanden."
elif apt-cache show uxplay >/dev/null 2>&1 && \
     apt-cache policy uxplay | grep -q "Candidate: [^(]"; then
    sudo apt install -y uxplay || echo ">>> uxplay-Paket verfügbar aber Installation fehlgeschlagen."
else
    echo ">>> uxplay nicht in Paketquellen. Versuche Bau aus Quellcode..."
    BUILD_DEPS=(cmake build-essential pkg-config libssl-dev libplist-dev
                libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev
                gstreamer1.0-plugins-base gstreamer1.0-plugins-good
                gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly
                gstreamer1.0-libav gstreamer1.0-tools
                libavahi-compat-libdnssd-dev libdbus-1-dev)
    apt_install "${BUILD_DEPS[@]}"
    TMP="$(mktemp -d)"
    if git clone --depth=1 https://github.com/FDH2/UxPlay.git "$TMP/UxPlay"; then
        cd "$TMP/UxPlay"
        if cmake . && make -j"$(nproc)" && sudo make install; then
            echo ">>> uxplay aus Quellcode erfolgreich installiert."
        else
            echo "!!! UxPlay-Build fehlgeschlagen. AirPlay ist deaktiviert."
            echo "!!! Installation kann später nachgeholt werden; Kiosk funktioniert trotzdem."
        fi
        cd "$DIR"
        rm -rf "$TMP"
    else
        echo "!!! UxPlay-Bau übersprungen (kein Internet?). AirPlay deaktiviert."
    fi
fi

# --------------------------------------------------
# 5. Python venv + Flask + qrcode
# --------------------------------------------------
echo ">>> [5/7] Python-Umgebung"
if [ ! -d "$DIR/venv" ]; then
    python3 -m venv "$DIR/venv"
fi
"$DIR/venv/bin/pip" install --upgrade pip --quiet
"$DIR/venv/bin/pip" install -r "$DIR/requirements.txt"

# --------------------------------------------------
# 6. Sudo-Rechte (reboot, shutdown, nmcli)
# --------------------------------------------------
echo ">>> [6/7] Sudo-Rechte"
SUDO_FILE="/etc/sudoers.d/pi-kiosk"
# Hinweis: sudo folgt Symlinks bei der Pfadprüfung NICHT. Auf Bookworm+ liegen
# reboot/shutdown unter /usr/sbin/, auf älteren Systemen unter /sbin/.
# Wir listen beide Pfade explizit, damit die Quick Actions zuverlässig laufen.
sudo tee "$SUDO_FILE" >/dev/null <<EOF
$USER_NAME ALL=(ALL) NOPASSWD: /sbin/reboot, /usr/sbin/reboot, /sbin/shutdown, /usr/sbin/shutdown, /usr/bin/nmcli
EOF
sudo chmod 440 "$SUDO_FILE"
# Syntax der sudoers-Datei pruefen, damit wir uns nicht selbst aussperren
if ! sudo visudo -cf "$SUDO_FILE" >/dev/null; then
    echo "!!! sudoers-Datei fehlerhaft, wird entfernt."
    sudo rm -f "$SUDO_FILE"
    exit 1
fi

# --------------------------------------------------
# 7. systemd-Service
# --------------------------------------------------
echo ">>> [7/7] systemd-Service"
SERVICE_SRC="$DIR/pi-kiosk.service"
SERVICE_DST="/etc/systemd/system/pi-kiosk.service"
sudo sed -e "s|__USER__|$USER_NAME|g" -e "s|__DIR__|$DIR|g" \
    "$SERVICE_SRC" | sudo tee "$SERVICE_DST" >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable pi-kiosk.service

# GNOME-Keyring-Dialog (Chromium-Passwort-Prompt) komplett deaktivieren
# --------------------------------------------------
# Vorhandenen Keyring löschen, damit Chromium nie wieder danach fragt
rm -rf "$USER_HOME/.local/share/keyrings" 2>/dev/null || true
# gnome-keyring Autostarts unterdrücken
KR_AUTOSTART_DIR="$USER_HOME/.config/autostart"
mkdir -p "$KR_AUTOSTART_DIR"
for f in gnome-keyring-pkcs11 gnome-keyring-secrets gnome-keyring-ssh; do
    cat > "$KR_AUTOSTART_DIR/${f}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$f (disabled)
Hidden=true
X-GNOME-Autostart-enabled=false
EOF
done
chown -R "$USER_NAME":"$USER_NAME" "$KR_AUTOSTART_DIR"

# Desktop-Icon anlegen (öffnet das Webinterface im Chromium)
DESKTOP_DIR="$USER_HOME/Desktop"
if [ ! -d "$DESKTOP_DIR" ]; then
    mkdir -p "$DESKTOP_DIR"
    chown "$USER_NAME":"$USER_NAME" "$DESKTOP_DIR"
fi
DESKTOP_FILE="$DESKTOP_DIR/PiScreenPortal.desktop"
# xdg-open nutzt automatisch den registrierten Default-Browser und
# funktioniert darum unabhaengig davon, ob das Paket "chromium" oder
# "chromium-browser" heisst.
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=PiScreenPortal
Comment=Webinterface der PiScreenPortal-Steuerung öffnen
Exec=xdg-open http://localhost:2411
Icon=chromium
Terminal=false
Categories=Utility;
StartupNotify=true
EOF
chmod +x "$DESKTOP_FILE"
chown "$USER_NAME":"$USER_NAME" "$DESKTOP_FILE"
# Auf manchen Desktops muss die Datei als "vertrauenswürdig" markiert werden
if command -v gio >/dev/null 2>&1; then
    sudo -u "$USER_NAME" gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
fi

# --------------------------------------------------
# 24/7-Kiosk-Modus: WLAN-Powersave und Screen-Blanking dauerhaft aus.
# Sonst trennt der Pi im Idle den AP oder schaltet nach 10 min den
# Bildschirm ab - beides toedlich fuer Dauerbetrieb.
# --------------------------------------------------
echo ">>> 24/7-Modus: WLAN-Powersave dauerhaft aus"
NM_CONF_DIR="/etc/NetworkManager/conf.d"
NM_CONF="$NM_CONF_DIR/99-pi-kiosk-powersave.conf"
sudo mkdir -p "$NM_CONF_DIR"
sudo tee "$NM_CONF" >/dev/null <<'EOF'
# Deaktiviert WLAN-Powersaving fuer alle Verbindungen.
# 2 = disable, 3 = enable (NM-Default ist 3 auf Bookworm+).
# Von PiScreenPortal automatisch angelegt - nicht aendern wenn du im
# 24/7-Betrieb kein zufaelliges Disconnect willst.
[connection]
wifi.powersave = 2
EOF
if systemctl is-active --quiet NetworkManager; then
    sudo systemctl reload NetworkManager || sudo systemctl restart NetworkManager
fi

echo ">>> 24/7-Modus: Bildschirmschoner / DPMS dauerhaft aus (X11 LXDE autostart)"
AUTOSTART_DIR="$USER_HOME/.config/lxsession/LXDE-pi"
AUTOSTART="$AUTOSTART_DIR/autostart"
if [ -d "$AUTOSTART_DIR" ] && [ -f "$AUTOSTART" ]; then
    if ! grep -q "xset s off" "$AUTOSTART"; then
        echo "@xset s off"     | sudo -u "$USER_NAME" tee -a "$AUTOSTART" >/dev/null
        echo "@xset -dpms"     | sudo -u "$USER_NAME" tee -a "$AUTOSTART" >/dev/null
        echo "@xset s noblank" | sudo -u "$USER_NAME" tee -a "$AUTOSTART" >/dev/null
    fi
fi

# Wayfire (Wayland unter Pi OS Bookworm+): Idle-Timeout auf 0
WAYFIRE_INI="$USER_HOME/.config/wayfire.ini"
if [ -f "$WAYFIRE_INI" ]; then
    if ! grep -q "^\[idle\]" "$WAYFIRE_INI"; then
        echo "" | sudo -u "$USER_NAME" tee -a "$WAYFIRE_INI" >/dev/null
        echo "[idle]"                | sudo -u "$USER_NAME" tee -a "$WAYFIRE_INI" >/dev/null
        echo "toggle = none"         | sudo -u "$USER_NAME" tee -a "$WAYFIRE_INI" >/dev/null
        echo "screensaver_timeout = 0" | sudo -u "$USER_NAME" tee -a "$WAYFIRE_INI" >/dev/null
        echo "dpms_timeout = 0"      | sudo -u "$USER_NAME" tee -a "$WAYFIRE_INI" >/dev/null
    fi
fi

# labwc (Wayland auf Trixie+): kanshi / swayidle deaktivieren falls aktiv
# Hinweis: labwc nutzt wlopm/swayidle-aehnliche Mechanik; auf Pi OS wird
# defaultmaessig nichts gestartet, darum kein Eingriff noetig.

# --------------------------------------------------
# Fertig
# --------------------------------------------------
IP="$(hostname -I | awk '{print $1}')"
PORT=2411

# --------------------------------------------------
# Dienst automatisch starten / neu starten
# --------------------------------------------------
echo ">>> Starte pi-kiosk.service..."
if sudo systemctl is-active --quiet pi-kiosk; then
    sudo systemctl restart pi-kiosk
else
    sudo systemctl start pi-kiosk
fi
sleep 1
sudo systemctl --no-pager --lines=0 status pi-kiosk || true

echo ""
echo "=========================================="
echo " Installation abgeschlossen."
echo "=========================================="
echo ""
echo " Webinterface im Browser:"
echo "   http://$IP:$PORT"
echo ""
echo " Dienst-Status:  sudo systemctl status pi-kiosk"
echo " Live-Log:       journalctl -u pi-kiosk -f"
echo ""
