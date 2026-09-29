import json

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.server_anki import ServerAnki


BODY = {
    "word": " run ", "language": "English", "deck": "Vocab",
    "meanings": [{"part_of_speech": "verb", "definition": "Move <fast>.",
                  "examples": ["I run."], "examples_masked": ["I ___."]}],
}


class FakeProvider:
    display_name = "Fake"
    model = "fake"


def app_client(tmp_path, responses):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append((request.url.port, body))
        answer = responses.get((request.url.port, body["action"]), None)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, json={"result": answer, "error": None})

    transport = httpx.MockTransport(handler)
    anki = ServerAnki((("sun", 8765), ("kay", 8766)), tmp_path,
                      httpx.Client(transport=transport))
    settings = Settings("claude", "fake", ("fake",), (("sun", 8765), ("kay", 8766)))
    app = create_app(settings, FakeProvider(), anki)
    return TestClient(app), calls, anki


def test_decks_are_isolated_and_require_login(tmp_path):
    client, calls, _ = app_client(tmp_path, {
        (8765, "deckNames"): ["Sun"], (8766, "deckNames"): ["Kay"],
    })
    assert client.get("/api/decks").status_code == 401
    assert client.get("/api/decks", headers={"x-kanki-user": "unknown"}).status_code == 401
    assert client.get("/api/decks", headers={"x-kanki-user": "sun"}).json() == ["Sun"]
    assert client.get("/api/decks", headers={"x-kanki-user": "kay"}).json() == ["Kay"]
    assert [port for port, _ in calls] == [8765, 8766]


def test_duplicate_and_add_use_only_selected_profile(tmp_path):
    responses = {(8765, "deckNames"): ["Vocab"], (8765, "findNotes"): [42],
                 (8765, "modelNames"): ["AI Vocab"], (8765, "addNote"): 99,
                 (8765, "sync"): None}
    client, calls, _ = app_client(tmp_path, responses)
    headers = {"x-kanki-user": "sun"}
    assert client.post("/api/add", json=BODY, headers=headers).json() == {"duplicate": True}
    assert not any(body["action"] == "addNote" for _, body in calls)
    result = client.post("/api/add?allow_duplicate=true", json=BODY, headers=headers)
    assert result.status_code == 200
    assert result.json()["note_id"] == 99
    assert all(port == 8765 for port, _ in calls)
    note = next(body["params"]["note"] for _, body in calls if body["action"] == "addNote")
    assert note["options"]["allowDuplicate"] is True
    assert note["fields"]["Word"] == "run"
    assert "&lt;fast&gt;" in note["fields"]["Definition"]


def test_offline_server_anki_is_clear(tmp_path):
    client, _, _ = app_client(tmp_path, {(8765, "deckNames"): httpx.ConnectError("offline")})
    response = client.get("/api/decks", headers={"x-kanki-user": "sun"})
    assert response.status_code == 503
    assert "Server Anki is unavailable" in response.json()["detail"]


def test_sync_hook_reports_finish_and_retries(tmp_path):
    client, _, anki = app_client(tmp_path, {(8765, "sync"): None})
    headers = {"x-kanki-user": "sun"}
    assert client.post("/api/sync", headers=headers).json()["state"] in ("queued", "running")
    requested = anki.sync_states["sun"].requested_at
    (tmp_path / "sun.json").write_text(json.dumps({"state": "finished", "time": requested + 1}))
    assert client.get("/api/sync", headers=headers).json()["state"] == "finished"


def test_sync_hook_reports_error(tmp_path):
    client, _, anki = app_client(tmp_path, {(8765, "sync"): None})
    headers = {"x-kanki-user": "sun"}
    client.post("/api/sync", headers=headers)
    requested = anki.sync_states["sun"].requested_at
    (tmp_path / "sun.json").write_text(json.dumps({"state": "error", "time": requested + 1}))
    result = client.get("/api/sync", headers=headers).json()
    assert result["state"] == "error"
    assert "Anki reported" in result["detail"]
