"""AnkiConnect client, note formatting and duplicate handling.

AnkiConnect is replaced with httpx.MockTransport, so no network is used.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.anki import (
    FIELDS,
    MODEL_NAME,
    UNAVAILABLE_MESSAGE,
    AnkiClient,
    AnkiError,
    AnkiUnavailableError,
)
from app.config import Settings
from app.main import create_app
from app.notes import build_fields
from app.providers.base import Generation
from app.schemas import NoteMeaning, WordResult

URL = "http://anki.test"


class FakeAnki:
    """A tiny in-memory AnkiConnect. Records every request."""

    def __init__(self, models=(MODEL_NAME,), decks=("Default", "Vocab"), existing=()):
        self.models = list(models)
        self.decks = list(decks)
        self.existing = list(existing)  # note ids returned by findNotes
        self.requests = []
        self.errors = {}  # action -> error string

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        action, params = body["action"], body["params"]
        if action in self.errors:
            return httpx.Response(200, json={"result": None, "error": self.errors[action]})
        result = {
            "deckNames": lambda: self.decks,
            "modelNames": lambda: self.models,
            "createModel": lambda: self.models.append(params["modelName"]) or {},
            "findNotes": lambda: self.existing,
            "addNote": lambda: 1234,
        }[action]()
        return httpx.Response(200, json={"result": result, "error": None})

    def client(self) -> AnkiClient:
        return AnkiClient(URL, transport=httpx.MockTransport(self.handler))

    def actions(self):
        return [r["action"] for r in self.requests]


def offline_client() -> AnkiClient:
    def refuse(request):
        raise httpx.ConnectError("Connection refused", request=request)

    return AnkiClient(URL, transport=httpx.MockTransport(refuse))


# --- Client -----------------------------------------------------------------


def test_requests_use_version_6():
    fake = FakeAnki()
    assert fake.client().deck_names() == ["Default", "Vocab"]
    assert fake.requests[0] == {"action": "deckNames", "version": 6, "params": {}}


def test_error_field_raises():
    fake = FakeAnki()
    fake.errors["deckNames"] = "collection is not available"
    with pytest.raises(AnkiError, match="collection is not available"):
        fake.client().deck_names()


def test_offline_anki_gives_clear_message():
    with pytest.raises(AnkiUnavailableError) as info:
        offline_client().deck_names()
    assert str(info.value) == UNAVAILABLE_MESSAGE


def test_ensure_model_creates_note_type_once():
    fake = FakeAnki(models=["Basic"])
    client = fake.client()
    client.ensure_model()
    client.ensure_model()  # cached, no more requests

    assert fake.actions() == ["modelNames", "createModel"]
    params = fake.requests[1]["params"]
    assert params["modelName"] == MODEL_NAME
    assert params["inOrderFields"] == FIELDS
    assert [t["Name"] for t in params["cardTemplates"]] == ["Forward", "Reverse"]
    reverse = params["cardTemplates"][1]
    assert "{{Word}}" not in reverse["Front"] and "{{Synonyms}}" not in reverse["Front"]
    assert "{{ExamplesMasked}}" in reverse["Front"]


def test_ensure_model_skips_existing_note_type():
    fake = FakeAnki()
    fake.client().ensure_model()
    assert fake.actions() == ["modelNames"]


def test_find_duplicates_query():
    fake = FakeAnki(existing=[42])
    assert fake.client().find_duplicates('My "Deck"', "rock & roll") == [42]
    query = fake.requests[0]["params"]["query"]
    assert query == '"deck:My \\"Deck\\"" "note:AI Vocab" "Word:rock &amp; roll"'


def test_find_duplicates_escapes_wildcards():
    fake = FakeAnki()
    fake.client().find_duplicates("Default", "a_b*")
    assert '"Word:a\\_b\\*"' in fake.requests[0]["params"]["query"]


def test_add_note_payload():
    fake = FakeAnki()
    note_id = fake.client().add_note("Vocab", {"Word": "run"}, allow_duplicate=True)
    assert note_id == 1234
    note = fake.requests[-1]["params"]["note"]
    assert note["deckName"] == "Vocab"
    assert note["modelName"] == MODEL_NAME
    assert note["tags"] == ["ai-vocab"]
    assert note["options"] == {"allowDuplicate": True, "duplicateScope": "deck"}


# --- Note formatting ----------------------------------------------------------


def meaning(pos, definition, examples, masked, synonyms):
    return NoteMeaning(part_of_speech=pos, definition=definition, examples=examples,
                       examples_masked=masked, synonyms=synonyms)


def test_single_meaning_is_not_numbered():
    fields = build_fields("run", "English", [
        meaning("verb", "To move fast.", ["I run."], ["I ___."], ["sprint", "jog"]),
    ])
    assert fields["Definition"] == '<span class="pos">verb</span> To move fast.'
    assert fields["Examples"] == "<ul><li>I run.</li></ul>"
    assert fields["ExamplesMasked"] == "<ul><li>I ___.</li></ul>"
    assert fields["Synonyms"] == "sprint, jog"


def test_multiple_meanings_are_numbered_consistently():
    fields = build_fields("run", "English", [
        meaning("verb", "To move fast.", ["I run.", "  "], ["I ___."], ["sprint"]),
        meaning("verb", "To manage.", ["He runs a shop."], ["He ___ a shop."], []),
    ])
    assert fields["Definition"] == (
        '<ol><li><span class="pos">verb</span> To move fast.</li>'
        '<li><span class="pos">verb</span> To manage.</li></ol>'
    )
    # Blank example lines are dropped.
    assert fields["Examples"] == (
        "<ol><li><ul><li>I run.</li></ul></li><li><ul><li>He runs a shop.</li></ul></li></ol>"
    )
    assert fields["ExamplesMasked"].count("<ol>") == 1
    # A meaning without synonyms keeps its number with a placeholder.
    assert fields["Synonyms"] == "<ol><li>sprint</li><li>—</li></ol>"


def test_synonyms_empty_when_no_meaning_has_any():
    fields = build_fields("run", "English", [
        meaning("verb", "a", ["x"], ["x"], []),
        meaning("noun", "b", ["y"], ["y"], []),
    ])
    assert fields["Synonyms"] == ""


def test_fields_are_html_escaped():
    fields = build_fields("<b>", "English", [
        meaning("noun", "Use <script> & more", ["a < b"], ["a < ___"], ["x&y"]),
    ])
    assert fields["Word"] == "&lt;b&gt;"
    assert "<script>" not in fields["Definition"]
    assert "&lt;script&gt; &amp; more" in fields["Definition"]
    assert fields["Examples"] == "<ul><li>a &lt; b</li></ul>"
    assert fields["Synonyms"] == "x&amp;y"


# --- Routes: duplicate flow and offline Anki ------------------------------------


class FakeProvider:
    display_name = "Fake"
    model = "fake-model"

    def __init__(self, result):
        self.result = result

    def generate(self, word, language_override, num_examples):
        return Generation(WordResult.model_validate(self.result), "fake-fallback")


SETTINGS = Settings(provider="claude", api_key="k", models=("m",), ankiconnect_url=URL)
ADD_BODY = {
    "word": "run",
    "language": "English",
    "deck": "Vocab",
    "meanings": [{"definition": "To move fast.", "examples": ["I run."], "examples_masked": ["I ___."]}],
}


def make_app(anki, sample_result=None):
    return TestClient(create_app(SETTINGS, FakeProvider(sample_result), anki))


def test_add_warns_about_duplicate_then_adds_anyway():
    fake = FakeAnki(existing=[99])
    client = make_app(fake.client())

    first = client.post("/api/add", json=ADD_BODY).json()
    assert first == {"status": "duplicate", "note_ids": [99]}
    assert "addNote" not in fake.actions()

    second = client.post("/api/add", json={**ADD_BODY, "allow_duplicate": True}).json()
    assert second == {"status": "added", "note_id": 1234}
    assert fake.requests[-1]["params"]["note"]["options"]["allowDuplicate"] is True


def test_add_without_duplicate():
    fake = FakeAnki()
    res = make_app(fake.client()).post("/api/add", json=ADD_BODY).json()
    assert res["status"] == "added"
    assert fake.requests[-1]["params"]["note"]["options"]["allowDuplicate"] is False


def test_routes_report_offline_anki():
    # `with` runs the startup hook, which must not crash when Anki is offline.
    with make_app(offline_client()) as client:
        for response in (client.get("/api/decks"), client.post("/api/add", json=ADD_BODY)):
            assert response.status_code == 503
            assert response.json()["detail"] == UNAVAILABLE_MESSAGE


def test_generate_route_keeps_word_and_flags(sample_result):
    sample_result["meanings"][1]["examples_masked"][0] = "He runs a small shop."  # model missed it
    client = make_app(FakeAnki().client(), sample_result)
    data = client.post("/api/generate", json={"word": " run ", "num_examples": 2}).json()
    assert data["word"] == "run"
    assert data["model"] == "fake-fallback"
    assert data["meanings"][0]["masked_flags"] == [False, False]
    assert data["meanings"][1]["masked_flags"] == [True, False]
    assert data["meanings"][1]["examples_masked"][0] == "He ___ a small shop."
    assert client.get("/api/info").json() == {"provider": "Fake", "model": "fake-model"}
