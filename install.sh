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
                libgstreamer1.0-dev gstreamer1.0-plugins-base
                gstreamer1.0-plugins-good gstreamer1.0-plugins-bad
                gstreamer1.0-plugins-ugly gstreamer1.0-libav
                gstreamer1.0-tools
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
sudo tee "$SUDO_FILE" >/dev/null <<EOF
$USER_NAME ALL=(ALL) NOPASSWD: /sbin/reboot, /sbin/shutdown, /usr/bin/nmcli
EOF
sudo chmod 440 "$SUDO_FILE"

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
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=PiScreenPortal
Comment=Webinterface der PiScreenPortal-Steuerung öffnen
Exec=chromium --new-window http://localhost:2411
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

# Bildschirmschoner im Desktop-Autostart deaktivieren (X11 LXDE)
AUTOSTART_DIR="$USER_HOME/.config/lxsession/LXDE-pi"
AUTOSTART="$AUTOSTART_DIR/autostart"
if [ -d "$AUTOSTART_DIR" ] && [ -f "$AUTOSTART" ]; then
    if ! grep -q "xset s off" "$AUTOSTART"; then
        echo "@xset s off"     | sudo -u "$USER_NAME" tee -a "$AUTOSTART" >/dev/null
        echo "@xset -dpms"     | sudo -u "$USER_NAME" tee -a "$AUTOSTART" >/dev/null
        echo "@xset s noblank" | sudo -u "$USER_NAME" tee -a "$AUTOSTART" >/dev/null
    fi
fi

# --------------------------------------------------
# Fertig
# --------------------------------------------------
IP="$(hostname -I | awk '{print $1}')"
PORT=2411

echo ""
echo "=========================================="
echo " Installation abgeschlossen."
echo "=========================================="
echo ""
echo " Dienst starten:"
echo "   sudo systemctl start pi-kiosk"
echo ""
echo " Dienst-Status:"
echo "   sudo systemctl status pi-kiosk"
echo ""
echo " Webinterface im Browser:"
echo "   http://$IP:$PORT"
echo ""
echo " WICHTIG: Wenn X11 noch nicht aktiv ist:"
echo "   sudo raspi-config -> Advanced -> Wayland -> X11"
echo ""
