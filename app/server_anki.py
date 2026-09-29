"""Per-login AnkiConnect access and background AnkiWeb sync tracking."""

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.anki import build_note, duplicate_query, note_type
from app.notes import build_fields
from app.schemas import NoteRequest

log = logging.getLogger(__name__)
UNAVAILABLE = "Server Anki is unavailable. Ask the administrator to start your Anki profile."


class AnkiError(Exception):
    pass


@dataclass
class SyncState:
    state: str = "idle"
    requested_at: float = 0
    detail: str = ""


class ServerAnki:
    def __init__(self, users: tuple[tuple[str, int], ...], status_dir: Path,
                 client: httpx.Client | None = None):
        self.ports = dict(users)
        self.status_dir = status_dir
        self.client = client or httpx.Client(timeout=15)
        self.lock = threading.RLock()
        self.user_locks = {user: threading.Lock() for user in self.ports}
        self.sync_states = {user: SyncState() for user in self.ports}

    def call(self, user: str, action: str, params: dict | None = None):
        # Port is selected only from administrator configuration, never a request value.
        port = self.ports[user]
        try:
            response = self.client.post(
                f"http://127.0.0.1:{port}",
                json={"action": action, "version": 6, "params": params or {}},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AnkiError(UNAVAILABLE) from exc
        if not isinstance(data, dict) or "error" not in data or "result" not in data:
            raise AnkiError("AnkiConnect returned an unexpected response.")
        if data["error"]:
            raise AnkiError(f"AnkiConnect {action}: {data['error']}")
        return data["result"]

    def decks(self, user: str):
        return self.call(user, "deckNames")

    def add(self, user: str, req: NoteRequest, allow_duplicate: bool = False):
        word = req.word.strip()
        with self.user_locks[user]:
            decks = self.decks(user)
            if req.deck not in decks:
                raise AnkiError("That deck is not in your Anki profile. Refresh the page.")
            if not allow_duplicate and self.call(user, "findNotes", {
                "query": duplicate_query(req.deck, word),
            }):
                return {"duplicate": True}
            names = self.call(user, "modelNames")
            if note_type()["modelName"] not in names:
                self.call(user, "createModel", note_type())
            fields = build_fields(word, req.language, req.meanings)
            note = build_note(req.deck, fields)
            note["options"] = {"allowDuplicate": allow_duplicate, "duplicateScope": "deck"}
            note_id = self.call(user, "addNote", {"note": note})
            self._request_sync(user)
            return {"duplicate": False, "note_id": note_id, "sync": self.status(user)}

    def _request_sync(self, user: str):
        with self.lock:
            current = self.status(user)["state"]
            # Coalesce additions while Anki is already syncing. A later pass
            # ensures notes added during the first pass are uploaded.
            if current in ("queued", "running"):
                self.sync_states[user].detail = "Another sync will follow."
                return
            self.sync_states[user] = SyncState("queued", time.time())
            threading.Thread(target=self._sync_worker, args=(user,), daemon=True).start()

    def retry_sync(self, user: str):
        self._request_sync(user)
        return self.status(user)

    def _sync_worker(self, user: str):
        try:
            self.call(user, "sync")  # Starts Anki's asynchronous collection sync.
            with self.lock:
                if self.sync_states[user].state == "queued":
                    self.sync_states[user].state = "running"
        except AnkiError as exc:
            log.warning("Anki sync request failed for %s: %s", user, exc)
            with self.lock:
                self.sync_states[user].state = "error"
                self.sync_states[user].detail = str(exc)

    def status(self, user: str):
        with self.lock:
            state = self.sync_states[user]
            if state.state in ("queued", "running"):
                path = self.status_dir / f"{user}.json"
                try:
                    marker = json.loads(path.read_text())
                except (OSError, ValueError):
                    marker = {}
                if marker.get("time", 0) >= state.requested_at:
                    if marker.get("state") == "finished":
                        if state.detail:
                            # A note arrived while syncing; run another pass.
                            state.detail = ""
                            state.state = "queued"
                            state.requested_at = time.time()
                            threading.Thread(target=self._sync_worker, args=(user,), daemon=True).start()
                        else:
                            state.state = "finished"
                    elif marker.get("state") == "error":
                        state.state = "error"
                        state.detail = "Anki reported a sync error. Open your server Anki window."
                    elif marker.get("state") == "started":
                        state.state = "running"
                elif time.time() - state.requested_at > 300:
                    state.state = "error"
                    state.detail = "No sync completion reported within five minutes. Check server Anki."
            return {"state": state.state, "detail": state.detail}
