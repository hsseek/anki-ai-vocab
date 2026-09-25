"""Gemini provider: Google's OpenAI-compatible endpoint, reusing OpenAIProvider.

Gemini has a free tier (API key from https://aistudio.google.com), so this
provider lets the app run without paying for API credits.
"""

from app.providers.openai_provider import OpenAIProvider


class GeminiProvider(OpenAIProvider):
    display_name = "Gemini"
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    key_var = "GEMINI_API_KEY"
    model_var = "GEMINI_MODEL"
