#!/usr/bin/env bash
# Start the app on localhost only. Open http://127.0.0.1:8000 afterwards.
set -euo pipefail
cd "$(dirname "$0")"

if [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
else
    PYTHON=python3
fi

exec "$PYTHON" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port "${PORT:-8000}"
