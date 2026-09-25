"""Server-side checks on model output and a fallback mask for example sentences.

The model does the real masking, because only it knows every inflected form of
a word. These helpers catch the obvious misses: a masked sentence or a
definition that still contains the word as typed.

Matching rules for each part of the word (multi-word phrases are split on spaces):
- Scripts written without spaces between words (Chinese, Japanese) and Korean,
  where particles attach to words, use a plain substring match.
- Other scripts match words that start with the part, case-insensitively, so
  "run" also finds "runs" and "running" (but not "brunch").
"""

import re

from app.schemas import CheckedMeaning, Meaning

MASK = "___"

# Hiragana, Katakana, CJK ideographs and Hangul.
_NO_SPACE_SCRIPTS = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯ᄀ-ᇿ]")


def _parts(word: str) -> list[str]:
    """Split a word or phrase into the parts that should be checked."""
    parts = []
    for part in word.split():
        # Skip one-letter parts like "a" in "a lot"; they match too much.
        if len(part) == 1 and not _NO_SPACE_SCRIPTS.search(part):
            continue
        parts.append(part)
    return parts


def _pattern(part: str) -> re.Pattern:
    escaped = re.escape(part)
    if _NO_SPACE_SCRIPTS.search(part):
        return re.compile(escaped, re.IGNORECASE)
    return re.compile(rf"(?<!\w){escaped}\w*", re.IGNORECASE)


def contains_word(text: str, word: str) -> bool:
    """True if `text` still contains the word or any part of a multi-word phrase."""
    return any(_pattern(p).search(text) for p in _parts(word))


def fallback_mask(text: str, word: str) -> str:
    """Replace every remaining occurrence of the word's parts with ___."""
    for part in _parts(word):
        text = _pattern(part).sub(MASK, text)
    return text


def check_meaning(meaning: Meaning, word: str) -> CheckedMeaning:
    """Apply the fallback mask where needed and flag anything the user should check."""
    masked, flags = [], []
    for sentence in meaning.examples_masked:
        if contains_word(sentence, word):
            masked.append(fallback_mask(sentence, word))
            flags.append(True)
        else:
            masked.append(sentence)
            flags.append(False)

    return CheckedMeaning(
        **meaning.model_dump(exclude={"examples_masked"}),
        examples_masked=masked,
        masked_flags=flags,
        definition_warning=contains_word(meaning.definition, word),
    )
