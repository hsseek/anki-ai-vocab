#!/usr/bin/env bash
# Configure one isolated Anki instance. Run as the same OS user as the web app.
set -euo pipefail

if [ "$#" -ne 3 ]; then
    echo "Usage: $0 LOGIN ANKICONNECT_PORT X_DISPLAY (e.g. sun 8765 91)" >&2
    exit 1
fi
login=$1 port=$2 display=$3
[[ "$login" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "Invalid login ID" >&2; exit 1; }
[[ "$port" =~ ^[0-9]+$ && "$display" =~ ^[0-9]+$ ]] || exit 1
anki_bin=${KANKI_ANKI_BIN:-$(command -v anki || true)}
[[ -x "$anki_bin" ]] || { echo "Install Anki or set KANKI_ANKI_BIN to its executable." >&2; exit 1; }
command -v xvfb-run >/dev/null || { echo "Install xvfb and xauth first." >&2; exit 1; }

here=$(cd "$(dirname "$0")" && pwd)
base="$HOME/.local/share/kanki-anki/$login"
config="$HOME/.config/kanki"
mkdir -p "$base/addons21" "$config" "$HOME/.config/systemd/user"
ln -sfn "$here/sync-status-addon" "$base/addons21/kanki_sync_status"
printf 'KANKI_ANKI_BIN=%s\nKANKI_DISPLAY=%s\n' "$anki_bin" "$display" > "$config/anki-$login.env"
chmod 600 "$config/anki-$login.env"
cp "$here/anki-profile@.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now "anki-profile@$login"
echo "Configured '$login'. Ensure AnkiConnect is installed in this profile on loopback port $port."
