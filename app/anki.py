"""AnkiConnect client (API version 6) and the "AI Vocab" note type."""

import httpx

from app.notes import esc

API_VERSION = 6
MODEL_NAME = "AI Vocab"
FIELDS = ["Word", "Language", "Definition", "Examples", "ExamplesMasked", "Synonyms"]
TAGS = ["ai-vocab"]
UNAVAILABLE_MESSAGE = "Open Anki desktop and make sure the AnkiConnect add-on is installed."

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


class AnkiError(Exception):
    """AnkiConnect returned an error."""


class AnkiUnavailableError(AnkiError):
    """Anki is not running or AnkiConnect cannot be reached."""

    def __init__(self):
        super().__init__(UNAVAILABLE_MESSAGE)


def search_quote(text: str) -> str:
    """Escape text for use inside a quoted Anki search term.

    `*` and `_` are wildcards in Anki searches, so they are escaped too.
    """
    for char in ("\\", '"', "*", "_"):
        text = text.replace(char, "\\" + char)
    return text


class AnkiClient:
    def __init__(self, url: str, transport: httpx.BaseTransport | None = None):
        # `transport` lets tests replace the network with httpx.MockTransport.
        self.url = url
        self.http = httpx.Client(transport=transport, timeout=10)
        self._model_ready = False

    def invoke(self, action: str, **params):
        """Call one AnkiConnect action and return its result."""
        payload = {"action": action, "version": API_VERSION, "params": params}
        try:
            response = self.http.post(self.url, json=payload)
            response.raise_for_status()
            data = response.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            raise AnkiUnavailableError()
        except (httpx.HTTPError, ValueError) as exc:
            raise AnkiError(f"Unexpected response from AnkiConnect: {exc}")

        if not isinstance(data, dict) or "error" not in data or "result" not in data:
            raise AnkiError("Unexpected response from AnkiConnect. Is it a recent version?")
        if data["error"] is not None:
            raise AnkiError(f"AnkiConnect error ({action}): {data['error']}")
        return data["result"]

    def deck_names(self) -> list[str]:
        return self.invoke("deckNames")

    def ensure_model(self) -> None:
        """Create the "AI Vocab" note type if it does not exist yet."""
        if self._model_ready:
            return
        if MODEL_NAME not in self.invoke("modelNames"):
            self.invoke(
                "createModel",
                modelName=MODEL_NAME,
                inOrderFields=FIELDS,
                css=CARD_CSS,
                isCloze=False,
                cardTemplates=[
                    {"Name": "Forward", "Front": FORWARD_FRONT, "Back": FORWARD_BACK},
                    {"Name": "Reverse", "Front": REVERSE_FRONT, "Back": REVERSE_BACK},
                ],
            )
        self._model_ready = True

    def find_duplicates(self, deck: str, word: str) -> list[int]:
        """Find "AI Vocab" notes in `deck` whose Word field equals `word`.

        Anki field searches ignore case, so "Run" matches "run". The Word field
        is stored HTML-escaped, so the search uses the escaped form too.
        """
        query = (
            f'"deck:{search_quote(deck)}" '
            f'"note:{search_quote(MODEL_NAME)}" '
            f'"Word:{search_quote(esc(word))}"'
        )
        return self.invoke("findNotes", query=query)

    def add_note(self, deck: str, fields: dict[str, str], allow_duplicate: bool = False) -> int:
        self.ensure_model()
        return self.invoke(
            "addNote",
            note={
                "deckName": deck,
                "modelName": MODEL_NAME,
                "fields": fields,
                "tags": TAGS,
                # Match our own check: duplicates only count within the same deck.
                "options": {"allowDuplicate": allow_duplicate, "duplicateScope": "deck"},
            },
        )
