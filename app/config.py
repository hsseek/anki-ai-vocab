"""Load and validate settings from the environment / .env file."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

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
    anki_users: tuple[tuple[str, int], ...]  # authenticated ID -> server loopback port


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

    users = []
    ports = set()
    for entry in get("ANKI_USERS").split(","):
        if not entry.strip():
            continue
        name, sep, port_text = entry.strip().partition(":")
        if not sep or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ConfigError("ANKI_USERS must list ID:PORT pairs, e.g. sun:8765,kay:8766.")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ConfigError(f"Invalid AnkiConnect port for {name!r}.") from exc
        if not 1024 <= port <= 65535 or port in ports or name in dict(users):
            raise ConfigError("ANKI_USERS requires unique IDs and ports from 1024 to 65535.")
        users.append((name, port))
        ports.add(port)
    if not users:
        raise ConfigError("ANKI_USERS is required (for example, ANKI_USERS=sun:8765,kay:8766).")

    return Settings(
        provider=provider,
        api_key=get(key_var),
        models=models,
        anki_users=tuple(users),
    )
