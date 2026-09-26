"""Claude provider: forces one tool call using the shared marked-example schema."""

import anthropic

from app.prompts import SYSTEM_PROMPT
from app.providers.base import (
    REQUEST_TIMEOUT,
    SDK_MAX_RETRIES,
    InvalidResponseError,
    LLMError,
    LLMProvider,
    ModelUnavailableError,
    api_error_text,
)
from app.schemas import MarkedWordResult

TOOL_NAME = "save_word_result"
MAX_TOKENS = 8192


class ClaudeProvider(LLMProvider):
    display_name = "Claude"

    def __init__(self, api_key: str, models: list[str], client: anthropic.Anthropic | None = None):
        super().__init__(models)
        # `client` can be injected by tests.
        self.client = client or anthropic.Anthropic(
            api_key=api_key, timeout=REQUEST_TIMEOUT, max_retries=SDK_MAX_RETRIES
        )
        self.tool = {
            "name": TOOL_NAME,
            "description": "Save the vocabulary data for the word.",
            "input_schema": MarkedWordResult.model_json_schema(),
        }

    def _request(self, model: str, user_prompt: str) -> dict:
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[self.tool],
                tool_choice={"type": "tool", "name": TOOL_NAME},
            )
        except anthropic.APIError as exc:
            error_cls = ModelUnavailableError if _is_temporary(exc) else LLMError
            raise error_cls(_error_message(exc, model)) from exc

        if response.stop_reason == "max_tokens":
            raise InvalidResponseError("response was cut off at max_tokens")
        for block in response.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                return block.input
        raise InvalidResponseError("no tool call in the response")

    def _stream_request(self, model: str, user_prompt: str):
        try:
            with self.client.messages.create(
                model=model, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[self.tool], tool_choice={"type": "tool", "name": TOOL_NAME},
                stream=True,
            ) as stream:
                tool_index = None
                finished = False
                stopped = False
                for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use" and block.name == TOOL_NAME:
                            if tool_index is not None:
                                raise InvalidResponseError("Multiple vocabulary tool calls")
                            tool_index = event.index
                    elif event.type == "content_block_delta":
                        if event.index == tool_index and event.delta.type == "input_json_delta":
                            yield event.delta.partial_json
                    elif event.type == "message_delta":
                        if event.delta.stop_reason:
                            if event.delta.stop_reason != "tool_use":
                                raise InvalidResponseError(
                                    f"Response ended with {event.delta.stop_reason}"
                                )
                            finished = True
                    elif event.type == "message_stop":
                        stopped = True
                if tool_index is None or not finished or not stopped:
                    raise InvalidResponseError("Incomplete vocabulary tool stream")
        except anthropic.APIError as exc:
            error_cls = ModelUnavailableError if _is_temporary(exc) else LLMError
            raise error_cls(_error_message(exc, model)) from exc


def _is_temporary(exc: anthropic.APIError) -> bool:
    """Overloaded, rate-limited or timed out: worth trying another model."""
    if isinstance(exc, (anthropic.RateLimitError, anthropic.APITimeoutError)):
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500


def _error_message(exc: anthropic.APIError, model: str) -> str:
    """Turn an SDK exception into a clear message for the user."""
    if isinstance(exc, anthropic.AuthenticationError):
        return "Claude: the API key was rejected. Check ANTHROPIC_API_KEY in .env."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "Claude: this API key is not allowed to use this model or feature."
    if isinstance(exc, anthropic.NotFoundError):
        return (f"Claude: model '{model}' was not found or is not available. "
                f"Check ANTHROPIC_MODEL in .env. ({api_error_text(exc)})")
    if isinstance(exc, anthropic.RateLimitError):
        return f"Claude: rate limit reached for '{model}'. Wait a moment and try again."
    if isinstance(exc, anthropic.APITimeoutError):
        return f"Claude: the request to '{model}' timed out. Try again."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Claude: could not connect to the Anthropic API. Check your internet connection."
    if isinstance(exc, anthropic.BadRequestError):
        return f"Claude: the request was rejected ({api_error_text(exc)})."
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return (f"Claude: '{model}' is overloaded or the API is having problems. "
                f"Try again shortly. ({api_error_text(exc)})")
    return f"Claude: API error ({exc})."
