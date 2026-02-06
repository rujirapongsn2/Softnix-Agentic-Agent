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
