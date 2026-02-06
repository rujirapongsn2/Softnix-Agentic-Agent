from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    max_iters: int = 10
    workspace: Path = Path(".")
    runs_dir: Path = Path(".softnix/runs")
    skills_dir: Path = Path("examples/skills")
    safe_commands: list[str] = None  # type: ignore[assignment]
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    claude_api_key: str | None = None
    claude_base_url: str = "https://api.anthropic.com"
    custom_api_key: str | None = None
    custom_base_url: str | None = None
    custom_model: str = "gpt-4o-mini"

    def __post_init__(self) -> None:
        if self.safe_commands is None:
            self.safe_commands = ["ls", "pwd", "cat", "echo", "python", "pytest", "rm"]


def load_settings() -> Settings:
    _load_dotenv()
    safe_commands_raw = os.getenv("SOFTNIX_SAFE_COMMANDS", "ls,pwd,cat,echo,python,pytest,rm")
    safe_commands = [x.strip() for x in safe_commands_raw.split(",") if x.strip()]
    if "rm" not in safe_commands:
        safe_commands.append("rm")
    return Settings(
        provider=os.getenv("SOFTNIX_PROVIDER", "openai"),
        model=os.getenv("SOFTNIX_MODEL", "gpt-4o-mini"),
        max_iters=int(os.getenv("SOFTNIX_MAX_ITERS", "10")),
        workspace=Path(os.getenv("SOFTNIX_WORKSPACE", ".")).resolve(),
        runs_dir=Path(os.getenv("SOFTNIX_RUNS_DIR", ".softnix/runs")),
        skills_dir=Path(os.getenv("SOFTNIX_SKILLS_DIR", "examples/skills")),
        safe_commands=safe_commands,
        openai_api_key=os.getenv("SOFTNIX_OPENAI_API_KEY"),
        openai_base_url=os.getenv("SOFTNIX_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        claude_api_key=os.getenv("SOFTNIX_CLAUDE_API_KEY"),
        claude_base_url=os.getenv("SOFTNIX_CLAUDE_BASE_URL", "https://api.anthropic.com"),
        custom_api_key=os.getenv("SOFTNIX_CUSTOM_API_KEY"),
        custom_base_url=os.getenv("SOFTNIX_CUSTOM_BASE_URL"),
        custom_model=os.getenv("SOFTNIX_CUSTOM_MODEL", "gpt-4o-mini"),
    )


def _load_dotenv(dotenv_path: Path | None = None) -> None:
    path = dotenv_path or Path(".env")
    if not path.exists() or not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        # Keep explicitly exported shell env as highest priority.
        if key not in os.environ:
            os.environ[key] = value
