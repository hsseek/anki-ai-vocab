import pytest

from app.config import DEFAULT_ANKICONNECT_URL, ConfigError, load_settings
from app.providers.claude import ClaudeProvider
from app.providers.factory import create_provider
from app.providers.openai_provider import OpenAIProvider

CLAUDE_ENV = {"LLM_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-ant-test", "ANTHROPIC_MODEL": "claude-test"}
GEMINI_ENV_BASE = {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "AIza-test"}
OPENAI_ENV = {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test", "OPENAI_MODEL": "gpt-test"}


def test_missing_provider():
    with pytest.raises(ConfigError, match="LLM_PROVIDER is not set"):
        load_settings({})


def test_invalid_provider():
    with pytest.raises(ConfigError, match="invalid"):
        load_settings({"LLM_PROVIDER": "mistral"})


@pytest.mark.parametrize("missing", ["ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"])
def test_claude_missing_setting(missing):
    env = {k: v for k, v in CLAUDE_ENV.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


@pytest.mark.parametrize("missing", ["OPENAI_API_KEY", "OPENAI_MODEL"])
def test_openai_missing_setting(missing):
    env = {k: v for k, v in OPENAI_ENV.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


def test_blank_value_counts_as_missing():
    with pytest.raises(ConfigError, match="ANTHROPIC_MODEL"):
        load_settings({**CLAUDE_ENV, "ANTHROPIC_MODEL": "   "})


def test_only_selected_provider_is_required():
    # OpenAI settings are absent, which is fine when Claude is selected.
    settings = load_settings(CLAUDE_ENV)
    assert settings.provider == "claude"
    assert settings.api_key == "sk-ant-test"
    assert settings.models == ("claude-test",)
    assert settings.ankiconnect_url == DEFAULT_ANKICONNECT_URL


def test_provider_name_is_case_insensitive_and_url_override():
    settings = load_settings({**OPENAI_ENV, "LLM_PROVIDER": " OpenAI ", "ANKICONNECT_URL": "http://localhost:9999"})
    assert settings.provider == "openai"
    assert settings.ankiconnect_url == "http://localhost:9999"


def test_model_setting_accepts_fallback_list():
    settings = load_settings({**GEMINI_ENV_BASE, "GEMINI_MODEL": " model-a , model-b,, "})
    assert settings.models == ("model-a", "model-b")
    assert create_provider(settings).models == ["model-a", "model-b"]


def test_model_setting_with_only_commas_is_invalid():
    with pytest.raises(ConfigError, match="GEMINI_MODEL"):
        load_settings({**GEMINI_ENV_BASE, "GEMINI_MODEL": " , "})


def test_factory_picks_claude():
    provider = create_provider(load_settings(CLAUDE_ENV))
    assert isinstance(provider, ClaudeProvider)
    assert provider.model == "claude-test"


def test_factory_picks_openai():
    provider = create_provider(load_settings(OPENAI_ENV))
    assert isinstance(provider, OpenAIProvider)
    assert provider.model == "gpt-test"


GEMINI_ENV = {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "AIza-test", "GEMINI_MODEL": "gemini-test"}


@pytest.mark.parametrize("missing", ["GEMINI_API_KEY", "GEMINI_MODEL"])
def test_gemini_missing_setting(missing):
    env = {k: v for k, v in GEMINI_ENV.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


def test_factory_picks_gemini():
    from app.providers.gemini import GeminiProvider

    provider = create_provider(load_settings(GEMINI_ENV))
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "gemini-test"
    assert "generativelanguage.googleapis.com" in str(provider.client.base_url)
