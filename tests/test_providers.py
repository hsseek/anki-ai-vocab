"""Both providers, with the SDK clients replaced by simple fakes (no network)."""

import json
from types import SimpleNamespace

import anthropic
import openai
import pytest

from app.providers.base import LLMError, ModelUnavailableError, api_error_text
from app.providers.claude import TOOL_NAME, ClaudeProvider
from app.providers.gemini import GeminiProvider
from app.providers.openai_provider import OpenAIProvider, strict_json_schema
from app.schemas import WordResult


class FakeCreate:
    """Stands in for `client.messages.create` / `client.chat.completions.create`.

    Returns (or raises) the queued items in order and records every call.
    """

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def fake_claude(*outcomes):
    create = FakeCreate(*outcomes)
    return SimpleNamespace(messages=SimpleNamespace(create=create)), create


def fake_openai(*outcomes):
    create = FakeCreate(*outcomes)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, create


def claude_response(tool_input, stop_reason="tool_use"):
    block = SimpleNamespace(type="tool_use", name=TOOL_NAME, input=tool_input)
    return SimpleNamespace(content=[block], stop_reason=stop_reason)


def openai_response(content, finish_reason="stop", refusal=None):
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


STATUS_CODES = {"BadRequestError": 400, "AuthenticationError": 401, "PermissionDeniedError": 403,
                "NotFoundError": 404, "RateLimitError": 429, "InternalServerError": 500}


def sdk_error(cls):
    """Create an SDK exception without building an HTTP response.

    The provider code only uses isinstance checks and status_code, so this is enough.
    """
    err = cls.__new__(cls)
    Exception.__init__(err, "boom")
    err.message = "boom"
    err.body = None
    if cls.__name__ in STATUS_CODES:
        err.status_code = STATUS_CODES[cls.__name__]
    return err


# --- Same result shape from both providers -------------------------------


def test_both_providers_return_the_same_result(sample_result):
    claude_client, claude_create = fake_claude(claude_response(sample_result))
    openai_client, openai_create = fake_openai(openai_response(json.dumps(sample_result)))

    claude = ClaudeProvider("key", ["claude-test"], client=claude_client)
    gpt = OpenAIProvider("key", ["gpt-test"], client=openai_client)

    a = claude.generate("run", None, 2).result
    b = gpt.generate("run", None, 2).result

    assert isinstance(a, WordResult) and isinstance(b, WordResult)
    assert a == b
    assert a.meanings[0].examples_masked[1] == "She ___ to the bus."

    # Both got the same system prompt.
    system_claude = claude_create.calls[0]["system"]
    system_openai = openai_create.calls[0]["messages"][0]["content"]
    assert system_claude == system_openai


def test_claude_forces_the_tool(sample_result):
    client, create = fake_claude(claude_response(sample_result))
    ClaudeProvider("key", ["claude-test"], client=client).generate("run", "English", 3)

    call = create.calls[0]
    assert call["model"] == "claude-test"
    assert call["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert call["tools"][0]["input_schema"] == WordResult.model_json_schema()
    user_prompt = call["messages"][0]["content"]
    assert "run" in user_prompt and "English" in user_prompt and "3" in user_prompt


def test_openai_uses_strict_structured_output(sample_result):
    client, create = fake_openai(openai_response(json.dumps(sample_result)))
    OpenAIProvider("key", ["gpt-test"], client=client).generate("run", None, 2)

    fmt = create.calls[0]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True


def test_strict_schema_closes_every_object():
    schema = strict_json_schema(WordResult)
    objects = [schema, *schema["$defs"].values()]
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


# --- Validation and retry --------------------------------------------------


def test_claude_retries_once_after_invalid_output(sample_result):
    client, create = fake_claude(claude_response({"meanings": "oops"}), claude_response(sample_result))
    result = ClaudeProvider("key", ["m"], client=client).generate("run", None, 2).result
    assert len(create.calls) == 2
    assert result.detected_language == "English"


def test_openai_retries_once_after_bad_json(sample_result):
    client, create = fake_openai(openai_response("{not json"), openai_response(json.dumps(sample_result)))
    OpenAIProvider("key", ["m"], client=client).generate("run", None, 2)
    assert len(create.calls) == 2


def test_gives_up_after_two_invalid_outputs(sample_result):
    bad = dict(sample_result, meanings=[])  # no meanings -> invalid
    client, create = fake_claude(claude_response(bad), claude_response(bad))
    with pytest.raises(LLMError, match="unexpected format twice"):
        ClaudeProvider("key", ["m"], client=client).generate("run", None, 2)
    assert len(create.calls) == 2


def test_mismatched_masked_examples_are_invalid(sample_result):
    sample_result["meanings"][0]["examples_masked"].pop()
    client, _ = fake_openai(*[openai_response(json.dumps(sample_result))] * 2)
    with pytest.raises(LLMError):
        OpenAIProvider("key", ["m"], client=client).generate("run", None, 2)


def test_truncated_claude_response_is_retried(sample_result):
    client, create = fake_claude(claude_response({}, stop_reason="max_tokens"), claude_response(sample_result))
    ClaudeProvider("key", ["m"], client=client).generate("run", None, 2)
    assert len(create.calls) == 2


def test_openai_refusal_is_reported():
    client, _ = fake_openai(openai_response(None, refusal="no thanks"))
    with pytest.raises(LLMError, match="refused"):
        OpenAIProvider("key", ["m"], client=client).generate("run", None, 2)


# --- Provider-specific error messages --------------------------------------


@pytest.mark.parametrize(
    "error_cls, expected",
    [
        (anthropic.AuthenticationError, "ANTHROPIC_API_KEY"),
        (anthropic.NotFoundError, "ANTHROPIC_MODEL"),
        (anthropic.RateLimitError, "rate limit"),
        (anthropic.InternalServerError, "overloaded"),
    ],
)
def test_claude_error_messages(error_cls, expected):
    client, _ = fake_claude(sdk_error(error_cls))
    with pytest.raises(LLMError, match=expected):
        ClaudeProvider("key", ["m"], client=client).generate("run", None, 2)


@pytest.mark.parametrize(
    "error_cls, expected",
    [
        (openai.AuthenticationError, "OPENAI_API_KEY"),
        (openai.NotFoundError, "OPENAI_MODEL"),
        (openai.RateLimitError, "rate limit"),
        (openai.InternalServerError, "having problems"),
    ],
)
def test_openai_error_messages(error_cls, expected):
    client, _ = fake_openai(sdk_error(error_cls))
    with pytest.raises(LLMError, match=expected):
        OpenAIProvider("key", ["m"], client=client).generate("run", None, 2)


def test_api_errors_are_not_retried():
    client, create = fake_claude(sdk_error(anthropic.RateLimitError))
    with pytest.raises(LLMError):
        ClaudeProvider("key", ["m"], client=client).generate("run", None, 2)
    assert len(create.calls) == 1


# --- Gemini (OpenAI-compatible endpoint) ------------------------------------


def test_gemini_returns_the_same_result(sample_result):
    client, create = fake_openai(openai_response(json.dumps(sample_result)))
    result = GeminiProvider("key", ["gemini-test"], client=client).generate("run", None, 2).result
    assert result == WordResult.model_validate(sample_result)
    assert create.calls[0]["model"] == "gemini-test"


def test_gemini_error_messages_name_gemini_settings():
    client, _ = fake_openai(sdk_error(openai.NotFoundError))
    with pytest.raises(LLMError, match="Gemini: .*GEMINI_MODEL"):
        GeminiProvider("key", ["m"], client=client).generate("run", None, 2)


@pytest.mark.parametrize(
    "body",
    [
        {"type": "error", "error": {"type": "invalid_request_error", "message": "Credit balance is too low"}},
        {"error": {"message": "Credit balance is too low", "code": 400}},
        [{"error": {"code": 400, "message": "Credit balance is too low", "status": "INVALID_ARGUMENT"}}],
    ],
)
def test_api_error_text_extracts_the_message(body):
    err = sdk_error(openai.BadRequestError)
    err.body = body
    assert api_error_text(err) == "Credit balance is too low"


def test_api_error_text_falls_back_to_full_message():
    err = sdk_error(openai.BadRequestError)
    err.body = None
    assert api_error_text(err) == "boom"


# --- Fallback models ---------------------------------------------------------


def test_falls_back_to_next_model_when_overloaded(sample_result):
    client, create = fake_openai(sdk_error(openai.InternalServerError),
                                 openai_response(json.dumps(sample_result)))
    provider = GeminiProvider("key", ["big-model", "lite-model"], client=client)
    generation = provider.generate("run", None, 2)
    assert generation.model == "lite-model"
    assert [c["model"] for c in create.calls] == ["big-model", "lite-model"]


@pytest.mark.parametrize("error_cls", [anthropic.RateLimitError, anthropic.APITimeoutError])
def test_claude_rate_limit_and_timeout_trigger_fallback(error_cls, sample_result):
    client, create = fake_claude(sdk_error(error_cls), claude_response(sample_result))
    generation = ClaudeProvider("key", ["a", "b"], client=client).generate("run", None, 2)
    assert generation.model == "b"


def test_permanent_errors_do_not_fall_back():
    client, create = fake_openai(sdk_error(openai.AuthenticationError))
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiProvider("key", ["a", "b"], client=client).generate("run", None, 2)
    assert len(create.calls) == 1


def test_all_models_unavailable():
    client, _ = fake_openai(sdk_error(openai.InternalServerError), sdk_error(openai.RateLimitError))
    with pytest.raises(LLMError, match=r"all models are unavailable right now \(a, b\)"):
        GeminiProvider("key", ["a", "b"], client=client).generate("run", None, 2)


def test_single_model_keeps_its_own_error_message():
    client, _ = fake_openai(sdk_error(openai.InternalServerError))
    with pytest.raises(ModelUnavailableError, match="'only' is overloaded"):
        GeminiProvider("key", ["only"], client=client).generate("run", None, 2)


def test_first_model_is_the_main_model():
    client, _ = fake_openai()
    assert GeminiProvider("key", ["a", "b"], client=client).model == "a"
