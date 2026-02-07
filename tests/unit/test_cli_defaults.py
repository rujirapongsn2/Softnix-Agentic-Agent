from pathlib import Path

from softnix_agentic_agent.cli import _resolve_run_options
from softnix_agentic_agent.config import Settings


def test_resolve_run_options_uses_settings_defaults() -> None:
    settings = Settings(
        provider="claude",
        model="claude-sonnet-4-5",
        max_iters=12,
        workspace=Path("/tmp/work"),
        skills_dir=Path("/tmp/skills"),
    )

    resolved = _resolve_run_options(
        settings=settings,
        provider=None,
        model=None,
        max_iters=None,
        workspace=None,
        skills_dir=None,
    )

    assert resolved["provider"] == "claude"
    assert resolved["model"] == "claude-sonnet-4-5"
    assert resolved["max_iters"] == 12
    assert resolved["workspace"] == Path("/tmp/work")
    assert resolved["skills_dir"] == Path("/tmp/skills")


def test_resolve_run_options_prefers_cli_values() -> None:
    settings = Settings(provider="claude", model="claude-sonnet-4-5")

    resolved = _resolve_run_options(
        settings=settings,
        provider="openai",
        model="gpt-4o-mini",
        max_iters=3,
        workspace=Path("./tmp"),
        skills_dir=Path("skillpacks"),
    )

    assert resolved["provider"] == "openai"
    assert resolved["model"] == "gpt-4o-mini"
    assert resolved["max_iters"] == 3
