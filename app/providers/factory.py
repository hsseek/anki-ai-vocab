"""Pick the LLM provider named by LLM_PROVIDER."""

from app.config import Settings
from app.providers.base import LLMProvider


def create_provider(settings: Settings) -> LLMProvider:
    # Imports are local so only the selected SDK is loaded.
    if settings.provider == "claude":
        from app.providers.claude import ClaudeProvider

        return ClaudeProvider(api_key=settings.api_key, models=list(settings.models))
    if settings.provider == "openai":
        from app.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=settings.api_key, models=list(settings.models))
    if settings.provider == "gemini":
        from app.providers.gemini import GeminiProvider

        return GeminiProvider(api_key=settings.api_key, models=list(settings.models))
    raise ValueError(f"Unknown provider: {settings.provider!r}")
