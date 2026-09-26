"""Load and validate settings from the environment / .env file."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_ANKICONNECT_URL = "http://127.0.0.1:8765"

# Settings each provider needs: provider -> (api key variable, model variable)
PROVIDER_VARS = {
    "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"),
    "openai": ("OPENAI_API_KEY", "OPENAI_MODEL"),
    "gemini": ("GEMINI_API_KEY", "GEMINI_MODEL"),
}


class ConfigError(Exception):
    """Raised when .env settings are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    provider: str  # "claude", "openai" or "gemini"
    api_key: str
    models: tuple[str, ...]  # main model first, then fallbacks
    ankiconnect_url: str  # AnkiConnect address as seen from the browser's computer


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read settings from `env` (defaults to os.environ after loading .env).

    Only the selected provider's key and model are required. The model setting
    may list fallback models separated by commas, e.g. "model-a,model-b".
    """
    if env is None:
        load_dotenv(ENV_FILE)
        env = os.environ

    def get(name: str) -> str:
        return (env.get(name) or "").strip()

    provider = get("LLM_PROVIDER").lower()
    if not provider:
        raise ConfigError(
            "LLM_PROVIDER is not set. Add LLM_PROVIDER=claude, openai or gemini to .env."
        )
    if provider not in PROVIDER_VARS:
        raise ConfigError(
            f"LLM_PROVIDER={provider!r} is invalid. Use 'claude', 'openai' or 'gemini'."
        )

    key_var, model_var = PROVIDER_VARS[provider]
    missing = [name for name in (key_var, model_var) if not get(name)]
    if missing:
        raise ConfigError(
            f"LLM_PROVIDER={provider} requires {' and '.join(missing)} in .env."
        )

    models = tuple(m.strip() for m in get(model_var).split(",") if m.strip())
    if not models:
        raise ConfigError(f"{model_var} in .env does not contain a model name.")

    return Settings(
        provider=provider,
        api_key=get(key_var),
        models=models,
        ankiconnect_url=get("ANKICONNECT_URL") or DEFAULT_ANKICONNECT_URL,
    )
