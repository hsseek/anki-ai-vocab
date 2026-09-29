"""Tiny Anki add-on: report collection sync lifecycle to the local web app."""

import json
import os
import time
from pathlib import Path

from aqt import gui_hooks
from aqt import sync as anki_sync

status_file = os.environ.get("KANKI_SYNC_STATUS_FILE")


def write_state(state):
    if not status_file:
        return
    path = Path(status_file)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"state": state, "time": time.time()}))
    os.replace(temporary, path)


_failed = False
_original_handle_sync_error = anki_sync.handle_sync_error


def handle_sync_error(mw, err):
    global _failed
    _failed = True
    write_state("error")
    return _original_handle_sync_error(mw, err)


def on_start():
    global _failed
    _failed = False
    write_state("started")


def on_finish():
    write_state("error" if _failed else "finished")


anki_sync.handle_sync_error = handle_sync_error
gui_hooks.sync_will_start.append(on_start)
gui_hooks.sync_did_finish.append(on_finish)
