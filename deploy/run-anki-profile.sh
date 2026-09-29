#!/usr/bin/env bash
# Each login has a separate Anki data directory and X display.
set -euo pipefail

login=${1:?login required}
[[ "$login" =~ ^[A-Za-z0-9_-]+$ ]] || exit 1
: "${KANKI_DISPLAY:?set KANKI_DISPLAY in the service environment file}"
: "${KANKI_ANKI_BIN:?set KANKI_ANKI_BIN in the service environment file}"
base="$HOME/.local/share/kanki-anki/$login"
mkdir -p "$base" "$HOME/.local/state/kanki"
exec xvfb-run --auth-file="$HOME/.config/kanki/xauth-$login" \
    --server-num="$KANKI_DISPLAY" --server-args="-screen 0 1280x800x24 -nolisten tcp" \
    "$KANKI_ANKI_BIN" -b "$base"
