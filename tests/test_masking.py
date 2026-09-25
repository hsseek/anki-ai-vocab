from app.masking import check_meaning, contains_word, fallback_mask
from app.schemas import Meaning


def make_meaning(**overrides):
    data = {
        "part_of_speech": "verb",
        "label": "move fast",
        "definition": "To move quickly on foot.",
        "examples": ["I run daily."],
        "examples_masked": ["I ___ daily."],
        "synonyms": [],
    }
    data.update(overrides)
    return Meaning(**data)


def test_contains_word_is_case_insensitive_whole_word():
    assert contains_word("Run, Forest!", "run")
    assert not contains_word("The brunch was nice.", "run")
    assert not contains_word("I ___ daily.", "run")


def test_fallback_mask_catches_simple_inflections():
    assert fallback_mask("She runs and keeps running.", "run") == "She ___ and keeps ___."


def test_fallback_mask_multi_word_expression():
    assert fallback_mask("He gave up after he Gives up.", "give up") == "He gave ___ after he ___ ___."
    assert contains_word("He ___ ___ quickly.", "give up") is False


def test_single_letter_parts_are_ignored():
    # "a" in "a lot" would match almost every English sentence.
    assert not contains_word("I have a cat.", "a lot")
    assert contains_word("Thanks a lot.", "a lot")


def test_korean_and_japanese_use_substring_match():
    # Korean particles attach directly to the word.
    assert contains_word("사과를 먹었어요.", "사과")
    assert fallback_mask("사과를 먹었어요.", "사과") == "___를 먹었어요."
    assert fallback_mask("毎日本を読みます。", "本") == "毎日___を読みます。"


def test_check_meaning_leaves_good_output_alone():
    checked = check_meaning(make_meaning(), "run")
    assert checked.examples_masked == ["I ___ daily."]
    assert checked.masked_flags == [False]
    assert checked.definition_warning is False


def test_check_meaning_applies_fallback_and_flags():
    meaning = make_meaning(
        examples=["I run daily.", "She runs fast."],
        examples_masked=["I ___ daily.", "She runs fast."],
    )
    checked = check_meaning(meaning, "run")
    assert checked.examples_masked == ["I ___ daily.", "She ___ fast."]
    assert checked.masked_flags == [False, True]
    assert checked.examples == meaning.examples  # unmasked examples untouched


def test_check_meaning_warns_when_definition_has_word():
    checked = check_meaning(make_meaning(definition="To run quickly."), "run")
    assert checked.definition_warning is True
