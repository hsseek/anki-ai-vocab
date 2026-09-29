"""The AI Vocab note type and AnkiConnect payload helpers."""

from app.notes import esc

MODEL_NAME = "AI Vocab"
FIELDS = ["Word", "Language", "Definition", "Examples", "ExamplesMasked", "Synonyms"]
TAGS = ["ai-vocab"]

# --- Card templates ---------------------------------------------------------

FORWARD_FRONT = '<div class="word">{{Word}}</div>'
FORWARD_BACK = """\
{{FrontSide}}
<hr id="answer">
<div class="section definition">{{Definition}}</div>
<div class="section examples">{{Examples}}</div>
{{#Synonyms}}
<div class="section synonyms"><div class="heading">Synonyms</div>{{Synonyms}}</div>
{{/Synonyms}}"""

REVERSE_FRONT = """\
<div class="section definition">{{Definition}}</div>
<div class="section examples">{{ExamplesMasked}}</div>"""
REVERSE_BACK = """\
{{FrontSide}}
<hr id="answer">
<div class="word">{{Word}}</div>"""

# Colors are CSS variables so night mode only has to swap the palette.
# Anki adds .nightMode (desktop) or .night_mode (older/mobile) to the card.
CARD_CSS = """\
.card {
  --text: #1f2328;
  --muted: #6a737d;
  --accent: #2f6fb3;
  --bg: #fbfaf7;
  --rule: #d8d4cc;
  font-family: system-ui, -apple-system, "Segoe UI", "Noto Sans", "Noto Sans CJK KR", "Noto Sans CJK JP", sans-serif;
  font-size: 20px;
  line-height: 1.55;
  color: var(--text);
  background: var(--bg);
  text-align: left;
  max-width: 640px;
  margin: 0 auto;
  padding: 20px;
}
.card.nightMode, .card.night_mode, .nightMode .card, .night_mode .card {
  --text: #e6e3dc;
  --muted: #9aa0a6;
  --accent: #7fb2e5;
  --bg: #1f2023;
  --rule: #3a3c40;
}
.word { font-size: 1.8em; font-weight: 600; text-align: center; margin: 0.4em 0; }
hr#answer { border: none; border-top: 1px solid var(--rule); margin: 1em 0; }
.section { margin: 0.8em 0; }
.pos { color: var(--accent); font-style: italic; font-size: 0.85em; margin-right: 0.3em; }
.examples { color: var(--text); }
.examples ul { margin: 0.3em 0; padding-left: 1.2em; }
.examples li { margin: 0.2em 0; }
.synonyms { color: var(--muted); font-size: 0.9em; }
.heading { font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
ol { padding-left: 1.4em; margin: 0.3em 0; }
ol > li { margin: 0.4em 0; }
"""


def search_quote(text: str) -> str:
    """Escape text for use inside a quoted Anki search term.

    `*` and `_` are wildcards in Anki searches, so they are escaped too.
    """
    for char in ("\\", '"', "*", "_"):
        text = text.replace(char, "\\" + char)
    return text


def note_type() -> dict:
    """Parameters for AnkiConnect's createModel action."""
    return {
        "modelName": MODEL_NAME,
        "inOrderFields": FIELDS,
        "css": CARD_CSS,
        "isCloze": False,
        "cardTemplates": [
            {"Name": "Forward", "Front": FORWARD_FRONT, "Back": FORWARD_BACK},
            {"Name": "Reverse", "Front": REVERSE_FRONT, "Back": REVERSE_BACK},
        ],
    }


def duplicate_query(deck: str, word: str) -> str:
    """Anki search for "AI Vocab" notes in `deck` whose Word field equals `word`.

    Anki field searches ignore case, so "Run" matches "run". The Word field
    is stored HTML-escaped, so the search uses the escaped form too.
    """
    return (
        f'"deck:{search_quote(deck)}" '
        f'"note:{search_quote(MODEL_NAME)}" '
        f'"Word:{search_quote(esc(word))}"'
    )


def build_note(deck: str, fields: dict[str, str]) -> dict:
    """The `note` parameter for AnkiConnect's addNote action (without options)."""
    return {"deckName": deck, "modelName": MODEL_NAME, "fields": fields, "tags": TAGS}
