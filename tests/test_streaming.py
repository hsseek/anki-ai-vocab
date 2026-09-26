"""Streaming SDKs, partial JSON, retries, and the public event protocol."""

import json
from types import SimpleNamespace as NS

import openai
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.marked import expand_example
from app.providers.base import LLMError
from app.providers.claude import ClaudeProvider, TOOL_NAME
from app.providers.gemini import GeminiProvider
from app.providers.openai_provider import OpenAIProvider
from app.schemas import MarkedWordResult, WordResult
from app.streaming import MeaningParser
from tests.test_anki import SETTINGS
from tests.test_providers import fake_openai, fake_claude, sdk_error


class FakeStream:
    def __init__(self, events):
        self.events = iter(events)
        self.closed = False
        self.consumed = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def __iter__(self):
        for event in self.events:
            self.consumed += 1
            if isinstance(event, Exception):
                raise event
            yield event


def openai_chunk(text=None, finish=None, refusal=None):
    return NS(choices=[NS(delta=NS(content=text, refusal=refusal), finish_reason=finish)])


def openai_stream(raw, finish="stop", size=13):
    text = json.dumps(raw, ensure_ascii=False)
    return FakeStream([
        *[openai_chunk(text[i:i + size]) for i in range(0, len(text), size)],
        openai_chunk(finish=finish),
    ])


def claude_stream(raw):
    text = json.dumps(raw)
    return FakeStream([
        NS(type="content_block_start", index=0, content_block=NS(type="tool_use", name=TOOL_NAME)),
        *[NS(type="content_block_delta", index=0,
             delta=NS(type="input_json_delta", partial_json=text[i:i + 11]))
          for i in range(0, len(text), 11)],
        NS(type="message_delta", delta=NS(stop_reason="tool_use")),
        NS(type="message_stop"),
    ])


@pytest.mark.parametrize("marked, plain, masked", [
    ("She [[ran]] home.", "She ran home.", "She ___ home."),
    ("[[Run]], then [[run]] again.", "Run, then run again.", "___, then ___ again."),
    ("She [[took]] her coat [[off]].", "She took her coat off.", "She ___ her coat ___."),
    ("그는 집으로 [[달렸다]].", "그는 집으로 달렸다.", "그는 집으로 ___."),
    ('A [[<tag>]] & "quote".', 'A <tag> & "quote".', 'A ___ & "quote".'),
])
def test_marked_examples(marked, plain, masked):
    assert expand_example(marked) == (plain, masked)


@pytest.mark.parametrize("bad", ["No target.", "[[]]", "[[ ]]", "[[run]", "[[run]] and [[ran",
                                "[[[run]]]", "[[run [[ran]]]]"])
def test_invalid_markers(bad):
    with pytest.raises(ValueError):
        expand_example(bad)


@pytest.mark.parametrize("size", [1, 7, 4096])
def test_parser_handles_chunk_boundaries_strings_and_unicode(compact_result, size):
    compact_result["meanings"][0]["definition"] = 'A "quote", } ], \\ and 한국어.'
    text = json.dumps(compact_result, ensure_ascii=False)
    parser = MeaningParser()
    meanings = []
    for i in range(0, len(text), size):
        meanings.extend(parser.feed(text[i:i + size]))
    assert meanings == compact_result["meanings"]
    assert parser.metadata["language_code"] == "en"


def test_parser_waits_for_closed_meaning(compact_result):
    meaning = json.dumps(compact_result["meanings"][0])
    parser = MeaningParser()
    assert parser.feed('{"meanings":[' + meaning[:-1]) == []
    assert parser.feed("}") == [compact_result["meanings"][0]]


@pytest.mark.parametrize("provider_class", [OpenAIProvider, GeminiProvider, ClaudeProvider])
def test_streams_same_result_and_closes_sdk(provider_class, compact_result, sample_result):
    if provider_class is ClaudeProvider:
        stream = claude_stream(compact_result)
        client, create = fake_claude(stream)
    else:
        stream = openai_stream(compact_result)
        client, create = fake_openai(stream)
    provider = provider_class("key", ["test"], client=client)
    events = provider.stream("run", None, 2)
    assert next(events)["type"] == "start"
    first = next(events)
    assert first["type"] == "meaning"
    assert not stream.closed  # First meaning reached the caller before the SDK completed.
    assert first["meaning"].examples_masked[1] == "She ___ to the bus."
    rest = list(events)
    assert rest[-1]["result"] == WordResult.model_validate(sample_result)
    assert create.calls[0]["stream"] is True
    assert stream.closed
    schema = (create.calls[0]["tools"][0]["input_schema"] if provider_class is ClaudeProvider
              else create.calls[0]["response_format"]["json_schema"]["schema"])
    assert "examples_masked" not in json.dumps(schema)
    assert "examples_marked" in json.dumps(schema)


def test_invalid_stream_resets_and_retries(compact_result):
    client, create = fake_openai(openai_stream(compact_result, finish="length"),
                                 openai_stream(compact_result))
    events = list(OpenAIProvider("k", ["m"], client=client).stream("run", None, 2))
    assert [e["attempt"] for e in events if e["type"] == "start"] == [1, 2]
    assert events[-1]["type"] == "done"
    assert len(create.calls) == 2


def test_stream_fallback_after_partial_output(compact_result):
    text = json.dumps(compact_result)
    first = FakeStream([openai_chunk(text), sdk_error(openai.InternalServerError)])
    client, _ = fake_openai(first, openai_stream(compact_result))
    events = list(GeminiProvider("k", ["a", "b"], client=client).stream("run", None, 2))
    assert [e["model"] for e in events if e["type"] == "start"] == ["a", "b"]
    assert events[-1]["model"] == "b"
    assert first.closed


def test_abandoning_generator_closes_upstream(compact_result):
    stream = openai_stream(compact_result)
    client, _ = fake_openai(stream)
    events = OpenAIProvider("k", ["m"], client=client).stream("run", None, 2)
    next(events)
    next(events)
    events.close()
    assert stream.closed


def test_refusal_and_missing_finish_do_not_succeed(compact_result):
    refusal = FakeStream([openai_chunk(refusal="No")])
    client, _ = fake_openai(refusal)
    with pytest.raises(LLMError, match="refused"):
        list(OpenAIProvider("k", ["m"], client=client).stream("run", None, 2))
    client, _ = fake_openai(
        FakeStream([openai_chunk(json.dumps(compact_result))]),
        FakeStream([openai_chunk(json.dumps(compact_result))]),
    )
    with pytest.raises(LLMError, match="twice"):
        list(OpenAIProvider("k", ["m"], client=client).stream("run", None, 2))


def test_wrong_example_count_retries(compact_result):
    client, create = fake_openai(openai_stream(compact_result), openai_stream(compact_result))
    with pytest.raises(LLMError, match="twice"):
        list(OpenAIProvider("k", ["m"], client=client).stream("run", None, 3))
    assert len(create.calls) == 2


def test_stream_route_checks_meanings_and_preserves_note_shape(compact_result):
    compact_result["meanings"][0]["examples_marked"][0] = "I [[run]] and run."
    client, _ = fake_openai(openai_stream(compact_result))
    provider = OpenAIProvider("k", ["m"], client=client)
    with TestClient(create_app(SETTINGS, provider)) as app:
        response = app.post("/api/generate/stream", json={"word": "run", "num_examples": 2})
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["start", "meaning", "meaning", "done"]
    assert events[1]["meaning"]["masked_flags"] == [True, False]
    assert events[-1]["result"]["meanings"][0]["examples_masked"][0] == "I ___ and ___."


def test_route_error_event_and_no_false_done():
    client, _ = fake_openai(sdk_error(openai.AuthenticationError))
    with TestClient(create_app(SETTINGS, OpenAIProvider("k", ["m"], client=client))) as app:
        response = app.post("/api/generate/stream", json={"word": "run"})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["start", "error"]
    assert "OPENAI_API_KEY" in events[-1]["detail"]
