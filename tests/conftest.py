"""Shared test data."""

import pytest

# A valid WordResult as a plain dict, like the JSON a model would return.
SAMPLE_RESULT = {
    "detected_language": "English",
    "language_code": "en",
    "meanings": [
        {
            "part_of_speech": "verb",
            "label": "move fast on foot",
            "definition": "To move quickly using your legs.",
            "examples": ["I run every morning.", "She ran to the bus."],
            "examples_masked": ["I ___ every morning.", "She ___ to the bus."],
            "synonyms": ["sprint", "jog"],
        },
        {
            "part_of_speech": "verb",
            "label": "manage",
            "definition": "To be in charge of a business.",
            "examples": ["He runs a small shop.", "They run the hotel together."],
            "examples_masked": ["He ___ a small shop.", "They ___ the hotel together."],
            "synonyms": [],
        },
    ],
}


@pytest.fixture
def sample_result():
    import copy

    return copy.deepcopy(SAMPLE_RESULT)
