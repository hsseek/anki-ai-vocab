#!/usr/bin/env bash
# One-time server setup: installs Caddy from its official repository, puts
# HTTPS and a login in front of the app, and creates the logins.
#
#   sudo deploy/setup-caddy.sh [--private-cert] DOMAIN ID [ID...]
#   e.g. sudo deploy/setup-caddy.sh vocab.example.com sun kay
#
# Default: a public certificate from Let's Encrypt (ZeroSSL as fallback).
# --private-cert: Caddy acts as its own certificate authority, for domains
# where public CAs may not issue (e.g. iptime.org, whose CAA record forbids
# all CAs). Each computer then installs the root from https://DOMAIN/root.crt.
#
# Forward TCP 443 (and 80) on your router to this server first.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo." >&2; exit 1; fi
PRIVATE=false
if [ "${1:-}" = "--private-cert" ]; then PRIVATE=true; shift; fi
if [ $# -lt 2 ]; then echo "Usage: sudo $0 [--private-cert] DOMAIN ID [ID...]" >&2; exit 1; fi

DOMAIN=$1; shift
HERE=$(cd "$(dirname "$0")" && pwd)

# 1. Install Caddy from the official repo, so it gets security updates.
# Ubuntu Pro gives its (old) ESM caddy package priority 510, which beats the
# official repo's 500, so pin caddy to the official repo explicitly.
echo "== Installing Caddy"
if [ ! -f /etc/apt/sources.list.d/caddy-stable.list ]; then
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        > /etc/apt/sources.list.d/caddy-stable.list
    chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
fi
cat > /etc/apt/preferences.d/caddy-stable <<'PIN'
# Take caddy from the official Caddy repo (see deploy/setup-caddy.sh).
Package: caddy
Pin: origin dl.cloudsmith.io
Pin-Priority: 600
PIN
apt-get update
apt-get install -y caddy
caddy version

# 2. Write the Caddyfile (keeping a backup of the old one). The template marks
# lines for each certificate mode with "# public-cert" / "# private-cert".
if [ -f /etc/caddy/Caddyfile ]; then
    cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.$(date +%Y%m%d%H%M%S)"
fi
if $PRIVATE; then
    sed -e '/# public-cert$/d' -e 's/[[:space:]]*# private-cert$//' "$HERE/Caddyfile"
else
    read -rp "Email for certificate notices and the ZeroSSL fallback (optional, Enter to skip): " EMAIL
    if [ -n "$EMAIL" ]; then
        sed -e '/# private-cert$/d' -e 's/[[:space:]]*# public-cert$//' -e "s/__EMAIL__/$EMAIL/" "$HERE/Caddyfile"
    else
        sed -e '/# private-cert$/d' -e '/# public-cert$/d' "$HERE/Caddyfile"
    fi
fi | sed "s/__DOMAIN__/$DOMAIN/" > /etc/caddy/Caddyfile
caddy fmt --overwrite /etc/caddy/Caddyfile

# 3. Logins. Existing ones are kept, so this script can be run again safely.
for user in "$@"; do
    if grep -q "^$user " /etc/caddy/anki-ai-vocab.users 2>/dev/null; then
        echo "Login '$user' already exists (change it with deploy/set-password.sh)."
    else
        "$HERE/set-password.sh" --no-reload "$user"
    fi
done

# 4. Open the firewall for HTTPS (and HTTP, for certificates and the redirect).
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow 80/tcp comment "caddy http"
    ufw allow 443/tcp comment "caddy https"
fi

# 5. Check and start.
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl enable caddy
systemctl reload-or-restart caddy
echo
if $PRIVATE; then
    ROOT=/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
    for _ in $(seq 1 20); do [ -f "$ROOT" ] && break; sleep 0.5; done
    echo "Done. Install the root certificate on each computer that uses the app:"
    echo "  download: https://$DOMAIN/root.crt"
    echo "  check that its SHA-256 fingerprint is:"
    openssl x509 -in "$ROOT" -noout -fingerprint -sha256 | sed 's/^/    /'
    echo "Then open https://$DOMAIN"
else
    echo "Done. Open https://$DOMAIN (the first visit may take a minute while the certificate is issued)."
    echo "Certificate progress: journalctl -u caddy -f"
fi
