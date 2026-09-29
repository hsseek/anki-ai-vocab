#!/usr/bin/env bash
# One privileged setup step for the existing g3 deployment.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo." >&2; exit 1; fi

apt-get update
apt-get install -y \
    xvfb xauth x11vnc \
    libasound2t64 libdbus-1-3 libegl1 libfontconfig1 libfreetype6 libgl1 \
    libnss3 libpulse0 \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
    libxcomposite1 libxcursor1 libxi6 libxkbcommon0 libxkbcommon-x11-0 \
    libxrandr2 libxrender1 libxtst6 libglib2.0-0t64

"$(dirname "$0")/enable-caddy-user-header.sh"
