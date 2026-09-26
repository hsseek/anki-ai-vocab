"""Note type, note building and duplicate search, plus the routes the browser uses.

AnkiConnect itself is called by the browser (app/static/app.js), not the server.
"""

from fastapi.testclient import TestClient

from app.anki import FIELDS, MODEL_NAME, TAGS, build_note, duplicate_query, note_type
from app.config import Settings
from app.main import create_app
from app.notes import build_fields
from app.providers.base import Generation
from app.schemas import NoteMeaning, WordResult

# --- Note type and duplicate search --------------------------------------------


def test_note_type_definition():
    params = note_type()
    assert params["modelName"] == MODEL_NAME
    assert params["inOrderFields"] == FIELDS
    assert params["isCloze"] is False
    assert [t["Name"] for t in params["cardTemplates"]] == ["Forward", "Reverse"]
    reverse = params["cardTemplates"][1]
    assert "{{Word}}" not in reverse["Front"] and "{{Synonyms}}" not in reverse["Front"]
    assert "{{ExamplesMasked}}" in reverse["Front"]
    assert ".nightMode" in params["css"]


def test_duplicate_query_is_escaped():
    assert duplicate_query('My "Deck"', "rock & roll") == (
        '"deck:My \\"Deck\\"" "note:AI Vocab" "Word:rock &amp; roll"'
    )


def test_duplicate_query_escapes_wildcards():
    assert '"Word:a\\_b\\*"' in duplicate_query("Default", "a_b*")


def test_build_note():
    assert build_note("Vocab", {"Word": "run"}) == {
        "deckName": "Vocab", "modelName": MODEL_NAME, "fields": {"Word": "run"}, "tags": TAGS,
    }
    assert TAGS == ["ai-vocab"]


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


# --- Routes ------------------------------------------------------------------------


class FakeProvider:
    display_name = "Fake"
    model = "fake-model"

    def __init__(self, result):
        self.result = result

    def generate(self, word, language_override, num_examples):
        return Generation(WordResult.model_validate(self.result), "fake-fallback")


SETTINGS = Settings(provider="claude", api_key="k", models=("m",), ankiconnect_url="http://127.0.0.1:8765")
NOTE_BODY = {
    "word": " run ",
    "language": "English",
    "deck": "Vocab",
    "meanings": [{"part_of_speech": "verb", "definition": "To move <fast>.",
                  "examples": ["I run."], "examples_masked": ["I ___."]}],
}


def make_app(sample_result=None):
    return TestClient(create_app(SETTINGS, FakeProvider(sample_result)))


def test_info_includes_ankiconnect_url():
    assert make_app().get("/api/info").json() == {
        "provider": "Fake", "model": "fake-model", "ankiconnect_url": "http://127.0.0.1:8765",
    }


def test_note_type_route():
    assert make_app().get("/api/note-type").json() == note_type()


def test_note_route_builds_escaped_note_and_query():
    data = make_app().post("/api/note", json=NOTE_BODY).json()
    note = data["note"]
    assert note["deckName"] == "Vocab" and note["modelName"] == MODEL_NAME
    assert note["tags"] == ["ai-vocab"]
    assert note["fields"]["Word"] == "run"  # trimmed
    assert "To move &lt;fast&gt;." in note["fields"]["Definition"]
    assert data["duplicate_query"] == '"deck:Vocab" "note:AI Vocab" "Word:run"'


def test_note_route_rejects_empty_selection():
    response = make_app().post("/api/note", json={**NOTE_BODY, "meanings": []})
    assert response.status_code == 422


def test_server_has_no_anki_routes():
    client = make_app()
    assert client.get("/api/decks").status_code == 404
    assert client.post("/api/add", json=NOTE_BODY).status_code in (404, 405)


def test_generate_route_keeps_word_and_flags(sample_result):
    sample_result["meanings"][1]["examples_masked"][0] = "He runs a small shop."  # model missed it
    client = make_app(sample_result)
    data = client.post("/api/generate", json={"word": " run ", "num_examples": 2}).json()
    assert data["word"] == "run"
    assert data["model"] == "fake-fallback"
    assert data["meanings"][0]["masked_flags"] == [False, False]
    assert data["meanings"][1]["masked_flags"] == [True, False]
    assert data["meanings"][1]["examples_masked"][0] == "He ___ a small shop."
