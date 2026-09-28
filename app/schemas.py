"""Pydantic models shared by both LLM providers and the API routes."""

from pydantic import BaseModel, Field, model_validator

from app.marked import expand_example

# ---------------------------------------------------------------------------
# What the LLM returns. Both providers generate their JSON schema from these
# models, so keep them simple: no defaults and no extra constraints, because
# OpenAI strict mode rejects some JSON-schema keywords.
# ---------------------------------------------------------------------------


class Meaning(BaseModel):
    part_of_speech: str = Field(description="Part of speech, e.g. noun, verb.")
    label: str = Field(description="Short gloss of a few words for a selection list.")
    definition: str = Field(
        description="Learner-friendly definition that does not contain the word."
    )
    examples: list[str] = Field(description="Natural example sentences.")
    examples_masked: list[str] = Field(
        description="The same sentences with every form of the word replaced by ___."
    )
    synonyms: list[str] = Field(description="A few synonyms in the same language.")

    @model_validator(mode="after")
    def _examples_match(self):
        if len(self.examples) != len(self.examples_masked):
            raise ValueError("examples and examples_masked must have the same length")
        if not self.examples:
            raise ValueError("at least one example is required")
        return self


class WordResult(BaseModel):
    detected_language: str = Field(description="English name of the word's language.")
    language_code: str = Field(description="ISO 639-1 code of the word's language.")
    meanings: list[Meaning] = Field(description="All common meanings of the word.")

    @model_validator(mode="after")
    def _has_meanings(self):
        if not self.meanings:
            raise ValueError("at least one meaning is required")
        return self


class MarkedMeaning(BaseModel):
    """Compact wire schema: the model writes each sentence only once."""

    part_of_speech: str
    label: str
    definition: str
    examples_marked: list[str] = Field(
        description="Sentences with every target form wrapped in [[...]], e.g. She [[ran]] home."
    )
    synonyms: list[str]

    def expand(self, num_examples: int) -> Meaning:
        if len(self.examples_marked) != num_examples:
            raise ValueError(f"Expected exactly {num_examples} examples per meaning")
        pairs = [expand_example(sentence) for sentence in self.examples_marked]
        return Meaning(
            part_of_speech=self.part_of_speech, label=self.label,
            definition=self.definition, synonyms=self.synonyms,
            examples=[pair[0] for pair in pairs],
            examples_masked=[pair[1] for pair in pairs],
        )


class MarkedWordResult(BaseModel):
    detected_language: str
    language_code: str
    meanings: list[MarkedMeaning]

    def expand(self, num_examples: int) -> WordResult:
        return WordResult(
            detected_language=self.detected_language, language_code=self.language_code,
            meanings=[meaning.expand(num_examples) for meaning in self.meanings],
        )


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    word: str = Field(min_length=1, max_length=100)
    language: str | None = None  # language override, e.g. "Korean"
    num_examples: int = Field(default=2, ge=1, le=3)


class CheckedMeaning(Meaning):
    """A meaning plus the results of the server-side checks."""

    masked_flags: list[bool]  # True = fallback masking was applied to this example
    definition_warning: bool  # True = definition contains the target word


class GenerateResponse(BaseModel):
    word: str
    model: str  # the model that answered (may be a fallback model)
    detected_language: str
    language_code: str
    meanings: list[CheckedMeaning]


class ClientGenerationMetric(BaseModel):
    """Browser-observed latency; contains no word or generated content."""

    request_id: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    event: str = Field(pattern=r"^(first_meaning|complete|error)$")
    elapsed_ms: int = Field(ge=0, le=300_000)


class NoteMeaning(BaseModel):
    """One meaning as edited by the user in the preview."""

    part_of_speech: str = ""
    definition: str = ""
    examples: list[str] = []
    examples_masked: list[str] = []
    synonyms: list[str] = []


class NoteRequest(BaseModel):
    word: str = Field(min_length=1)
    language: str = ""
    deck: str = Field(min_length=1)
    meanings: list[NoteMeaning] = Field(min_length=1)
