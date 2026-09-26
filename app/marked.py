"""Expand model-marked targets into the two example fields used by Anki."""

import re

TARGET = re.compile(r"\[\[([^\[\]]+)\]\]")


def expand_example(sentence: str) -> tuple[str, str]:
    matches = list(TARGET.finditer(sentence))
    remainder = TARGET.sub("", sentence)
    if (not matches or "[[" in remainder or "]]" in remainder
            or "[[[" in sentence or "]]]" in sentence
            or any(not match.group(1).strip() for match in matches)):
        raise ValueError("Each example must mark targets with balanced, nonempty [[...]] spans")
    return TARGET.sub(r"\1", sentence), TARGET.sub("___", sentence)
