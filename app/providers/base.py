"""The LLMProvider interface. The rest of the app depends only on this module."""

import logging
from contextlib import closing
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.prompts import build_user_prompt
from app.schemas import MarkedMeaning, MarkedWordResult, WordResult
from app.streaming import MeaningParser

log = logging.getLogger(__name__)


# Every request gives up after this many seconds, so errors show up quickly.
REQUEST_TIMEOUT = 90
# Retries done by the SDK itself for temporary errors (the SDK default is 2).
SDK_MAX_RETRIES = 1


class LLMError(Exception):
    """An LLM failure with a message that is safe to show to the user."""


class ModelUnavailableError(LLMError):
    """A temporary problem with one model (overloaded, rate limit, timeout).

    `generate` moves on to the next fallback model when it sees this.
    """


class InvalidResponseError(Exception):
    """The model's output was not usable JSON. Triggers one retry."""


@dataclass(frozen=True)
class Generation:
    result: WordResult
    model: str  # the model that produced the result


class LLMProvider(ABC):
    """Base class for LLM providers.

    Subclasses provide blocking and streaming requests using the same compact
    schema. Both paths validate and expand marked examples, retry invalid data
    once, and fall back to the next model on temporary provider errors.
    """

    display_name: str  # e.g. "Claude", shown in the UI and in error messages

    def __init__(self, models: list[str]):
        # Models in order of preference. The first one is the main model.
        self.models = list(models)

    @property
    def model(self) -> str:
        return self.models[0]

    def generate(
        self, word: str, language_override: str | None, num_examples: int
    ) -> Generation:
        user_prompt = build_user_prompt(word, language_override, num_examples)

        for model in self.models:
            try:
                return Generation(self._generate_with(model, user_prompt, num_examples), model)
            except ModelUnavailableError as exc:
                log.warning("%s model %s unavailable: %s", self.display_name, model, exc)
                last_error = exc

        if len(self.models) == 1:
            raise last_error
        raise LLMError(
            f"{self.display_name}: all models are unavailable right now "
            f"({', '.join(self.models)}). Try again shortly. Last error: {last_error}"
        )

    def _generate_with(self, model: str, user_prompt: str, num_examples: int) -> WordResult:
        """Ask one model, validating the result and retrying once if it is invalid."""
        last_error: Exception | None = None

        for attempt in (1, 2):  # first try + one retry
            try:
                raw = self._request(model, user_prompt)
                return MarkedWordResult.model_validate(raw).expand(num_examples)
            except (ValueError, InvalidResponseError) as exc:
                log.warning("%s (%s) returned invalid data (attempt %d): %s",
                            self.display_name, model, attempt, exc)
                last_error = exc

        raise LLMError(
            f"{self.display_name} returned data in an unexpected format twice. "
            f"Please try again. ({_short(last_error)})"
        )

    def stream(self, word: str, language_override: str | None, num_examples: int):
        """Yield completed meanings, resetting provisional results on retry/fallback."""
        prompt = build_user_prompt(word, language_override, num_examples)
        for model in self.models:
            try:
                for attempt in (1, 2):
                    yield {"type": "start", "model": model, "attempt": attempt}
                    parser = MeaningParser()
                    try:
                        with closing(self._stream_request(model, prompt)) as chunks:
                            for chunk in chunks:
                                for raw in parser.feed(chunk):
                                    meaning = MarkedMeaning.model_validate(raw).expand(num_examples)
                                    yield {
                                        "type": "meaning", "model": model, "meaning": meaning,
                                        "detected_language": parser.metadata.get("detected_language", ""),
                                        "language_code": parser.metadata.get("language_code", ""),
                                    }
                        result = MarkedWordResult.model_validate_json(parser.text).expand(num_examples)
                        yield {"type": "done", "model": model, "result": result}
                        return
                    except (ValueError, InvalidResponseError) as exc:
                        log.warning("%s (%s) invalid streamed data (attempt %d): %s",
                                    self.display_name, model, attempt, exc)
                        if attempt == 2:
                            raise LLMError(
                                f"{self.display_name} returned invalid data twice. Please try again."
                            ) from exc
            except ModelUnavailableError as exc:
                last_error = exc
                log.warning("%s model %s unavailable: %s", self.display_name, model, exc)
        if len(self.models) == 1:
            raise last_error
        raise LLMError(f"{self.display_name}: all models are unavailable. Last error: {last_error}")

    @abstractmethod
    def _stream_request(self, model: str, user_prompt: str):
        """Yield JSON text deltas, raising on incomplete or refused responses."""

    @abstractmethod
    def _request(self, model: str, user_prompt: str) -> dict:
        """Send one request to `model` and return the model's JSON object.

        Raise InvalidResponseError for unusable output, ModelUnavailableError
        for temporary API problems, and LLMError for other API errors.
        """


def api_error_text(exc: Exception) -> str:
    """Extract the human-readable message from an SDK API error.

    Error bodies look like {"error": {"message": ...}} (OpenAI, Anthropic)
    or a list holding that object (Gemini). Falls back to the full text.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, list) and body:
        body = body[0]
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    return getattr(exc, "message", None) or str(exc)


def _short(exc: Exception | None, limit: int = 200) -> str:
    text = str(exc).replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"
