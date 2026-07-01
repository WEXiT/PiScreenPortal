#!/usr/bin/env bash
# PiScreenPortal installer for Raspberry Pi OS 64-bit (Bookworm)
# Automatically installs all missing dependencies.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
USER_GROUP="$(id -gn "$USER_NAME")"
if [ -z "$USER_HOME" ] || [ -z "$USER_GROUP" ]; then
    echo "!!! Could not fully resolve user '$USER_NAME'."
    exit 1
fi

echo "=========================================="
echo " PiScreenPortal Installer"
echo " Directory: $DIR"
echo " User:      $USER_NAME"
echo " Group:     $USER_GROUP"
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
        echo ">>> Installing: ${pkgs[*]}"
        sudo apt install -y "${pkgs[@]}"
    else
        echo ">>> Already installed: $*"
    fi
}

# --------------------------------------------------
# 1. Update package index
# --------------------------------------------------
echo ">>> [1/7] apt update"
sudo apt update

# --------------------------------------------------
# 2. Base packages
# --------------------------------------------------
echo ">>> [2/7] Base packages"
apt_install python3 python3-venv python3-pip python3-dev \
            git curl wget ca-certificates

# --------------------------------------------------
# 3. X11 and kiosk tools
# --------------------------------------------------
echo ">>> [3/7] Kiosk tools"
# Install base tools first (without Chromium).
apt_install x11-xserver-utils xdotool unclutter fonts-dejavu \
            network-manager avahi-daemon avahi-utils

# Chromium package names differ between distributions.
CHROMIUM_PKG=""
for cand in chromium chromium-browser; do
    if sudo apt-get install -y "$cand" 2>/dev/null; then
        CHROMIUM_PKG="$cand"
        echo ">>> Chromium installed as package '$cand'"
        break
    fi
done
if [ -z "$CHROMIUM_PKG" ]; then
    echo "!!! Chromium could not be installed from the package repositories."
    echo "!!! Please install it manually, for example: sudo apt install chromium"
    exit 1
fi

# --------------------------------------------------
# 4. UxPlay (AirPlay receiver) - optional
# --------------------------------------------------
echo ">>> [4/7] UxPlay (AirPlay)"
if need_cmd uxplay; then
    echo ">>> uxplay is already installed."
elif apt-cache show uxplay >/dev/null 2>&1 && \
     apt-cache policy uxplay | grep -q "Candidate: [^(]"; then
    sudo apt install -y uxplay || echo ">>> uxplay package is available, but installation failed."
else
    echo ">>> uxplay is not in the package repositories. Trying source build..."
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
            echo ">>> uxplay was built and installed successfully."
        else
            echo "!!! UxPlay build failed. AirPlay is disabled."
            echo "!!! You can install it later; the kiosk still works without it."
        fi
        cd "$DIR"
        rm -rf "$TMP"
    else
        echo "!!! Skipped UxPlay build (network unavailable?). AirPlay is disabled."
    fi
fi

# --------------------------------------------------
# 5. Python venv + Flask + qrcode
# --------------------------------------------------
echo ">>> [5/7] Python environment"
if [ ! -d "$DIR/venv" ]; then
    python3 -m venv "$DIR/venv"
fi
"$DIR/venv/bin/pip" install --upgrade pip --quiet
"$DIR/venv/bin/pip" install -r "$DIR/requirements.txt"
"$DIR/venv/bin/python" -c "import flask, qrcode; print('>>> Python deps ok')"

# --------------------------------------------------
# 6. Sudo permissions (reboot, shutdown, nmcli, apt updates)
# --------------------------------------------------
echo ">>> [6/7] Sudo permissions"
SUDO_FILE="/etc/sudoers.d/pi-kiosk"
# sudo does not follow symlinks while checking command paths. Bookworm+ uses
# /usr/sbin for reboot/shutdown; older systems may use /sbin. Keep both.
sudo tee "$SUDO_FILE" >/dev/null <<EOF
$USER_NAME ALL=(ALL) NOPASSWD: /sbin/reboot, /usr/sbin/reboot, /sbin/shutdown, /usr/sbin/shutdown, /usr/bin/nmcli, /usr/bin/apt, /usr/bin/apt-get
EOF
sudo chmod 440 "$SUDO_FILE"
# Validate sudoers syntax before continuing.
if ! sudo visudo -cf "$SUDO_FILE" >/dev/null; then
    echo "!!! sudoers file is invalid and will be removed."
    sudo rm -f "$SUDO_FILE"
    exit 1
fi

# --------------------------------------------------
# 7. systemd service
# --------------------------------------------------
echo ">>> [7/7] systemd service"
SERVICE_SRC="$DIR/pi-kiosk.service"
SERVICE_DST="/etc/systemd/system/pi-kiosk.service"
sudo sed -e "s|__USER__|$USER_NAME|g" -e "s|__DIR__|$DIR|g" \
    -e "s|__GROUP__|$USER_GROUP|g" -e "s|__HOME__|$USER_HOME|g" \
    "$SERVICE_SRC" | sudo tee "$SERVICE_DST" >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable pi-kiosk.service

# Disable the GNOME keyring dialog (Chromium password prompt).
# --------------------------------------------------
# Remove existing keyrings so Chromium does not prompt for them.
rm -rf "$USER_HOME/.local/share/keyrings" 2>/dev/null || true
# Disable gnome-keyring autostart entries.
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

# Create a desktop launcher that opens the web interface in Chromium.
DESKTOP_DIR="$USER_HOME/Desktop"
if [ ! -d "$DESKTOP_DIR" ]; then
    mkdir -p "$DESKTOP_DIR"
    chown "$USER_NAME":"$USER_NAME" "$DESKTOP_DIR"
fi
DESKTOP_FILE="$DESKTOP_DIR/PiScreenPortal.desktop"
OPEN_SCRIPT="$USER_HOME/.local/bin/piscreenportal-open-web.sh"
mkdir -p "$USER_HOME/.local/bin"
chown "$USER_NAME":"$USER_NAME" "$USER_HOME/.local" "$USER_HOME/.local/bin" 2>/dev/null || true
cat > "$OPEN_SCRIPT" <<'EOF'
#!/bin/sh
export GNOME_KEYRING_CONTROL=
export GNOME_KEYRING_PID=
export SSH_AUTH_SOCK=

BROWSER=""
for cand in chromium chromium-browser google-chrome; do
    if command -v "$cand" >/dev/null 2>&1; then
        BROWSER="$cand"
        break
    fi
done

if [ -n "$BROWSER" ]; then
    exec "$BROWSER" \
        --new-window \
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
        --ozone-platform=x11 \
        --password-store=basic \
        --use-mock-keychain \
        http://localhost:2411
fi

exec xdg-open http://localhost:2411
EOF
chmod +x "$OPEN_SCRIPT"
chown "$USER_NAME":"$USER_NAME" "$OPEN_SCRIPT"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=PiScreenPortal
Comment=Open the PiScreenPortal web interface
Exec=$OPEN_SCRIPT
Icon=chromium
Terminal=false
Categories=Utility;
StartupNotify=true
EOF
chmod +x "$DESKTOP_FILE"
chown "$USER_NAME":"$USER_NAME" "$DESKTOP_FILE"
# Some desktops require the launcher to be marked as trusted.
if command -v gio >/dev/null 2>&1; then
    sudo -u "$USER_NAME" gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
fi

# --------------------------------------------------
# 24/7 kiosk mode: keep Wi-Fi power saving and screen blanking disabled.
# Otherwise the Pi can drop Wi-Fi while idle or blank the screen after a
# few minutes, both of which are bad for unattended kiosk operation.
# --------------------------------------------------
echo ">>> 24/7 mode: permanently disabling Wi-Fi power saving"
NM_CONF_DIR="/etc/NetworkManager/conf.d"
NM_CONF="$NM_CONF_DIR/99-pi-kiosk-powersave.conf"
sudo mkdir -p "$NM_CONF_DIR"
sudo tee "$NM_CONF" >/dev/null <<'EOF'
# Disables Wi-Fi power saving for all connections.
# 2 = disable, 3 = enable (NetworkManager default on Bookworm+).
# Created by PiScreenPortal. Keep this enabled for reliable 24/7 operation.
[connection]
wifi.powersave = 2
EOF
if systemctl is-active --quiet NetworkManager; then
    sudo systemctl reload NetworkManager || sudo systemctl restart NetworkManager
fi

echo ">>> 24/7 mode: permanently disabling screensaver / DPMS (X11 LXDE autostart)"
AUTOSTART_DIR="$USER_HOME/.config/lxsession/LXDE-pi"
AUTOSTART="$AUTOSTART_DIR/autostart"
if [ -d "$AUTOSTART_DIR" ] && [ -f "$AUTOSTART" ]; then
    if ! grep -q "xset s off" "$AUTOSTART"; then
        echo "@xset s off"     | sudo -u "$USER_NAME" tee -a "$AUTOSTART" >/dev/null
        echo "@xset -dpms"     | sudo -u "$USER_NAME" tee -a "$AUTOSTART" >/dev/null
        echo "@xset s noblank" | sudo -u "$USER_NAME" tee -a "$AUTOSTART" >/dev/null
    fi
fi

# Wayfire (Wayland on Pi OS Bookworm+): set idle timeouts to 0.
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

# labwc (Wayland on Trixie+): no change needed by default on Raspberry Pi OS.

# --------------------------------------------------
# Done
# --------------------------------------------------
IP="$(hostname -I | awk '{print $1}')"
PORT=2411

# --------------------------------------------------
# Start or restart the service.
# --------------------------------------------------
echo ">>> Starting pi-kiosk.service..."
if sudo systemctl is-active --quiet pi-kiosk; then
    sudo systemctl restart pi-kiosk
else
    sudo systemctl start pi-kiosk
fi
sleep 1
sudo systemctl --no-pager --lines=0 status pi-kiosk || true

echo ""
echo "=========================================="
echo " Installation complete."
echo "=========================================="
echo ""
echo " Web interface:"
echo "   http://$IP:$PORT"
echo ""
echo " Service status: sudo systemctl status pi-kiosk"
echo " Live log:       journalctl -u pi-kiosk -f"
echo ""
