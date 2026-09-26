#!/usr/bin/env bash
# Start the app. By default it listens on localhost only: http://127.0.0.1:8000
# On a server, set HOST to a private address such as its Tailscale IP.
# Never use 0.0.0.0 or a public address: the app has no login.
set -euo pipefail
cd "$(dirname "$0")"

if [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
else
    PYTHON=python3
fi

exec "$PYTHON" -m uvicorn app.main:create_app --factory --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
