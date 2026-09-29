#!/usr/bin/env bash
# Update the existing Caddy configuration without reinstalling Caddy or logins.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo." >&2; exit 1; fi

original=/etc/caddy/Caddyfile
candidate=$(mktemp /etc/caddy/Caddyfile.kanki.XXXXXX)
trap 'rm -f "$candidate"' EXIT

python3 - "$original" "$candidate" <<'PY'
from pathlib import Path
import sys

original, candidate = map(Path, sys.argv[1:])
text = original.read_text()
old = "\t\treverse_proxy 127.0.0.1:8000"
new = ("\t\treverse_proxy 127.0.0.1:8000 {\n"
       "\t\t\theader_up X-Kanki-User {http.auth.user.id}\n"
       "\t\t}")
if new not in text:
    if text.count(old) != 1 or "basic_auth" not in text:
        raise SystemExit("Expected one authenticated app reverse proxy; Caddyfile unchanged.")
    text = text.replace(old, new)
candidate.write_text(text)
PY

caddy fmt --overwrite "$candidate"
caddy validate --config "$candidate" --adapter caddyfile
backup="${original}.bak.$(date +%Y%m%d%H%M%S)"
cp "$original" "$backup"
install -m 644 "$candidate" "$original"
systemctl reload caddy
echo "Caddy now forwards the authenticated login ID. Backup: $backup"
