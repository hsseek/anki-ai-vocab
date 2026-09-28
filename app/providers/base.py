"""The LLMProvider interface. The rest of the app depends only on this module."""

import logging
import time
from contextlib import closing
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.prompts import build_user_prompt
from app.metrics import elapsed_ms, emit_metric
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

    def stream(
        self,
        word: str,
        language_override: str | None,
        num_examples: int,
        request_id: str = "unknown",
    ):
        """Yield completed meanings, resetting provisional results on retry/fallback."""
        prompt = build_user_prompt(word, language_override, num_examples)
        generation_start = time.perf_counter()
        emit_metric(
            "generation_started", request_id,
            provider=self.display_name, model_count=len(self.models),
            num_examples=num_examples, language_override=bool(language_override),
        )
        for model_index, model in enumerate(self.models):
            try:
                for attempt in (1, 2):
                    attempt_start = time.perf_counter()
                    first_chunk_ms = None
                    first_meaning_ms = None
                    generation_first_meaning_ms = None
                    output_chars = 0
                    meaning_count = 0
                    emit_metric(
                        "attempt_started", request_id, provider=self.display_name,
                        model=model, model_index=model_index, attempt=attempt,
                    )
                    yield {
                        "type": "start", "model": model, "attempt": attempt,
                        "request_id": request_id,
                    }
                    parser = MeaningParser()
                    try:
                        with closing(self._stream_request(model, prompt)) as chunks:
                            for chunk in chunks:
                                now = time.perf_counter()
                                output_chars += len(chunk)
                                if first_chunk_ms is None:
                                    first_chunk_ms = elapsed_ms(attempt_start, now)
                                    emit_metric(
                                        "first_chunk", request_id, provider=self.display_name,
                                        model=model, attempt=attempt,
                                        elapsed_ms=first_chunk_ms,
                                    )
                                for raw in parser.feed(chunk):
                                    meaning = MarkedMeaning.model_validate(raw).expand(num_examples)
                                    meaning_count += 1
                                    if first_meaning_ms is None:
                                        first_meaning_ms = elapsed_ms(
                                            attempt_start, time.perf_counter()
                                        )
                                        generation_first_meaning_ms = elapsed_ms(
                                            generation_start, time.perf_counter()
                                        )
                                        emit_metric(
                                            "first_meaning", request_id,
                                            provider=self.display_name, model=model,
                                            attempt=attempt, elapsed_ms=first_meaning_ms,
                                            generation_elapsed_ms=generation_first_meaning_ms,
                                        )
                                    yield {
                                        "type": "meaning", "model": model, "meaning": meaning,
                                        "detected_language": parser.metadata.get("detected_language", ""),
                                        "language_code": parser.metadata.get("language_code", ""),
                                    }
                        result = MarkedWordResult.model_validate_json(parser.text).expand(num_examples)
                        finished = time.perf_counter()
                        emit_metric(
                            "attempt_completed", request_id, provider=self.display_name,
                            model=model, model_index=model_index, attempt=attempt,
                            first_chunk_ms=first_chunk_ms,
                            first_meaning_ms=first_meaning_ms,
                            generation_first_meaning_ms=generation_first_meaning_ms,
                            total_ms=elapsed_ms(attempt_start, finished),
                            generation_total_ms=elapsed_ms(generation_start, finished),
                            meaning_count=len(result.meanings),
                            output_chars=output_chars,
                        )
                        yield {"type": "done", "model": model, "result": result}
                        return
                    except (ValueError, InvalidResponseError) as exc:
                        emit_metric(
                            "attempt_invalid", request_id, provider=self.display_name,
                            model=model, attempt=attempt,
                            elapsed_ms=elapsed_ms(attempt_start, time.perf_counter()),
                            meaning_count=meaning_count,
                            error_type=type(exc).__name__,
                        )
                        log.warning("%s (%s) invalid streamed data (attempt %d): %s",
                                    self.display_name, model, attempt, exc)
                        if attempt == 2:
                            raise LLMError(
                                f"{self.display_name} returned invalid data twice. Please try again."
                            ) from exc
            except ModelUnavailableError as exc:
                last_error = exc
                emit_metric(
                    "model_unavailable", request_id, provider=self.display_name,
                    model=model, model_index=model_index,
                    generation_total_ms=elapsed_ms(generation_start, time.perf_counter()),
                    error_type=type(exc.__cause__ or exc).__name__,
                )
                log.warning("%s model %s unavailable: %s", self.display_name, model, exc)
            except LLMError as exc:
                emit_metric(
                    "attempt_failed", request_id, provider=self.display_name,
                    model=model, model_index=model_index,
                    generation_total_ms=elapsed_ms(generation_start, time.perf_counter()),
                    error_type=type(exc.__cause__ or exc).__name__,
                )
                raise
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
