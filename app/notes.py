"""Build Anki field values (HTML) from the meanings the user selected and edited.

One meaning   -> plain definition, a bullet list of examples, comma-separated synonyms.
Two or more   -> every field is a numbered list, so item 1 is the same meaning
                 in Definition, Examples, ExamplesMasked and Synonyms.

All user and model text is HTML-escaped here, before it reaches Anki.
"""

from html import escape

from app.schemas import NoteMeaning

EMPTY_ITEM = "—"  # keeps numbering aligned when a meaning has no synonyms


def esc(text: str) -> str:
    """HTML-escape text for an Anki field."""
    return escape(text.strip(), quote=False)


def _clean(items: list[str]) -> list[str]:
    return [item.strip() for item in items if item.strip()]


def _definition(m: NoteMeaning) -> str:
    pos = f'<span class="pos">{esc(m.part_of_speech)}</span> ' if m.part_of_speech.strip() else ""
    return pos + esc(m.definition)


def _bullets(items: list[str]) -> str:
    items = _clean(items)
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def _synonyms(m: NoteMeaning) -> str:
    return ", ".join(esc(s) for s in _clean(m.synonyms))


def _numbered(values: list[str]) -> str:
    return "<ol>" + "".join(f"<li>{v or EMPTY_ITEM}</li>" for v in values) + "</ol>"


def build_fields(word: str, language: str, meanings: list[NoteMeaning]) -> dict[str, str]:
    """Return the fields for one "AI Vocab" note."""
    definitions = [_definition(m) for m in meanings]
    examples = [_bullets(m.examples) for m in meanings]
    masked = [_bullets(m.examples_masked) for m in meanings]
    synonyms = [_synonyms(m) for m in meanings]

    def combine(values: list[str]) -> str:
        return values[0] if len(meanings) == 1 else _numbered(values)

    return {
        "Word": esc(word),
        "Language": esc(language),
        "Definition": combine(definitions),
        "Examples": combine(examples),
        "ExamplesMasked": combine(masked),
        # Leave Synonyms empty when no meaning has any, so the card hides the section.
        "Synonyms": combine(synonyms) if any(synonyms) else "",
    }
