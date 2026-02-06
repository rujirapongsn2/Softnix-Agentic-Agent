from pathlib import Path

import pytest

from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.providers.claude_provider import ClaudeProvider
from softnix_agentic_agent.providers.factory import create_provider
from softnix_agentic_agent.providers.openai_compatible_provider import OpenAICompatibleProvider
from softnix_agentic_agent.providers.openai_provider import OpenAIProvider


def _settings() -> Settings:
    return Settings(
        provider="openai",
        model="gpt-4o-mini",
        max_iters=5,
        workspace=Path("."),
        runs_dir=Path(".softnix/runs"),
        skills_dir=Path("examples/skills"),
        safe_commands=["ls"],
        openai_api_key="x",
        claude_api_key="y",
        custom_api_key="z",
        custom_base_url="http://localhost:9999/v1",
    )


def test_factory_openai() -> None:
    p = create_provider("openai", _settings())
    assert isinstance(p, OpenAIProvider)


def test_factory_claude() -> None:
    p = create_provider("claude", _settings())
    assert isinstance(p, ClaudeProvider)


def test_factory_custom() -> None:
    p = create_provider("custom", _settings())
    assert isinstance(p, OpenAICompatibleProvider)


def test_factory_invalid() -> None:
    with pytest.raises(ValueError):
        create_provider("bad", _settings())


def test_openai_provider_requires_api_key() -> None:
    provider = OpenAIProvider(api_key=None)
    with pytest.raises(ValueError, match="SOFTNIX_OPENAI_API_KEY"):
        provider.generate(messages=[{"role": "user", "content": "hi"}], model="gpt-4o-mini")


def test_openai_provider_rejects_claude_model_name() -> None:
    provider = OpenAIProvider(api_key="x")
    with pytest.raises(ValueError, match="Model looks like Claude"):
        provider.generate(messages=[{"role": "user", "content": "hi"}], model="claude-haiku-4-5")


def test_claude_provider_rejects_openai_model_name() -> None:
    provider = ClaudeProvider(api_key="x")
    with pytest.raises(ValueError, match="Model looks like OpenAI"):
        provider.generate(messages=[{"role": "user", "content": "hi"}], model="gpt-4o-mini")
