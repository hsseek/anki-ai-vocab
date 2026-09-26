#!/usr/bin/env bash
# Add a login or change its password. Only a bcrypt hash is stored.
#
#   sudo deploy/set-password.sh ID            add, or change the password
#   sudo deploy/set-password.sh --delete ID   remove the login
#
# Pass --no-reload to skip reloading Caddy (used by setup-caddy.sh).
set -euo pipefail

USERS_FILE=/etc/caddy/anki-ai-vocab.users
MIN_LENGTH=12

delete=false
reload=true
user=""
for arg in "$@"; do
    case "$arg" in
        --delete) delete=true ;;
        --no-reload) reload=false ;;
        *) user="$arg" ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo." >&2; exit 1; fi
if [[ ! "$user" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Usage: sudo $0 [--delete] ID   (ID: letters, digits, . _ -)" >&2
    exit 1
fi

touch "$USERS_FILE"
chown root:caddy "$USERS_FILE"
chmod 640 "$USERS_FILE"

# Drop any existing line for this user.
others=$(grep -v "^$user " "$USERS_FILE" || true)

if $delete; then
    printf '%s\n' "$others" | sed '/^$/d' > "$USERS_FILE"
    echo "Removed login '$user'."
else
    while true; do
        read -rsp "New password for '$user' (at least $MIN_LENGTH characters): " pw1; echo
        read -rsp "Repeat the password: " pw2; echo
        if [ "$pw1" != "$pw2" ]; then echo "The passwords do not match. Try again."; continue; fi
        if [ ${#pw1} -lt $MIN_LENGTH ]; then echo "Too short. Try again."; continue; fi
        break
    done
    # caddy reads the password from stdin when it is not a terminal.
    hash=$(printf '%s\n' "$pw1" | caddy hash-password)
    unset pw1 pw2
    if [[ "$hash" != \$2* ]]; then echo "Hashing the password failed." >&2; exit 1; fi
    { printf '%s\n' "$others" | sed '/^$/d'; echo "$user $hash"; } > "$USERS_FILE"
    echo "Saved login '$user'."
fi

if $reload; then
    if [ ! -s "$USERS_FILE" ]; then
        echo "Warning: no logins left. Caddy will refuse to load until you add one." >&2
    else
        systemctl reload caddy
    fi
fi
