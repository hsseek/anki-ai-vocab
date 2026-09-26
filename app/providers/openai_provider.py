"""OpenAI provider: Structured Outputs using the shared marked-example schema."""

import copy
import json

import openai

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

SCHEMA_NAME = "word_result"


def strict_json_schema(model: type) -> dict:
    """Make a Pydantic JSON schema acceptable to OpenAI strict mode.

    Strict mode requires every object to list all its properties as required
    and to set additionalProperties to false.
    """
    schema = copy.deepcopy(model.model_json_schema())

    def fix(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for value in node.values():
                fix(value)
        elif isinstance(node, list):
            for item in node:
                fix(item)

    fix(schema)
    return schema


class OpenAIProvider(LLMProvider):
    display_name = "OpenAI"
    # Subclasses for OpenAI-compatible services override these.
    base_url: str | None = None  # None = the official OpenAI API
    key_var = "OPENAI_API_KEY"
    model_var = "OPENAI_MODEL"

    def __init__(self, api_key: str, models: list[str], client: openai.OpenAI | None = None):
        super().__init__(models)
        # `client` can be injected by tests.
        self.client = client or openai.OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=REQUEST_TIMEOUT,
            max_retries=SDK_MAX_RETRIES,
        )
        self.response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": SCHEMA_NAME,
                "strict": True,
                "schema": strict_json_schema(MarkedWordResult),
            },
        }

    def _request(self, model: str, user_prompt: str) -> dict:
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=self.response_format,
            )
        except openai.APIError as exc:
            error_cls = ModelUnavailableError if _is_temporary(exc) else LLMError
            raise error_cls(self._error_message(exc, model)) from exc

        choice = response.choices[0]
        if getattr(choice.message, "refusal", None):
            raise LLMError(f"{self.display_name}: the model refused the request ({choice.message.refusal}).")
        if choice.finish_reason == "length":
            raise InvalidResponseError("response was cut off (finish_reason=length)")
        try:
            return json.loads(choice.message.content or "")
        except json.JSONDecodeError as exc:
            raise InvalidResponseError(f"response is not valid JSON: {exc}") from exc

    def _error_message(self, exc: openai.APIError, model: str) -> str:
        """Turn an SDK exception into a clear message for the user."""
        name = self.display_name
        if isinstance(exc, openai.AuthenticationError):
            return f"{name}: the API key was rejected. Check {self.key_var} in .env."
        if isinstance(exc, openai.PermissionDeniedError):
            return f"{name}: this API key is not allowed to use this model or feature."
        if isinstance(exc, openai.NotFoundError):
            return (f"{name}: model '{model}' was not found or is not available. "
                    f"Check {self.model_var} in .env. ({api_error_text(exc)})")
        if isinstance(exc, openai.RateLimitError):
            # 429 is also used for an exhausted quota / free-tier limit.
            return f"{name}: rate limit or quota reached for '{model}'. Wait a moment, or check your plan and limits."
        if isinstance(exc, openai.APITimeoutError):
            return f"{name}: the request to '{model}' timed out. Try again."
        if isinstance(exc, openai.APIConnectionError):
            return f"{name}: could not connect to the API. Check your internet connection."
        if isinstance(exc, openai.BadRequestError):
            return f"{name}: the request was rejected ({api_error_text(exc)})."
        if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
            return f"{name}: '{model}' is overloaded or the API is having problems. Try again shortly. ({api_error_text(exc)})"
        return f"{name}: API error ({exc})."

    def _stream_request(self, model: str, user_prompt: str):
        try:
            with self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=self.response_format,
                stream=True,
            ) as stream:
                finished = False
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if getattr(choice.delta, "refusal", None):
                        raise LLMError(f"{self.display_name}: the model refused the request.")
                    if choice.delta.content:
                        yield choice.delta.content
                    if choice.finish_reason is not None:
                        if choice.finish_reason != "stop":
                            raise InvalidResponseError(
                                f"Response ended with {choice.finish_reason}"
                            )
                        finished = True
                if not finished:
                    raise InvalidResponseError("Response stream ended before completion")
        except openai.APIError as exc:
            error_cls = ModelUnavailableError if _is_temporary(exc) else LLMError
            raise error_cls(self._error_message(exc, model)) from exc


def _is_temporary(exc: openai.APIError) -> bool:
    """Overloaded, rate-limited or timed out: worth trying another model."""
    if isinstance(exc, (openai.RateLimitError, openai.APITimeoutError)):
        return True
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500
