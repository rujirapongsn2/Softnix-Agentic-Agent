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
    skills_dir: Path = Path("skillpacks")
    safe_commands: list[str] = None  # type: ignore[assignment]
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    claude_api_key: str | None = None
    claude_base_url: str = "https://api.anthropic.com"
    custom_api_key: str | None = None
    custom_base_url: str | None = None
    custom_model: str = "gpt-4o-mini"
    api_key: str | None = None
    cors_origins: list[str] = None  # type: ignore[assignment]
    cors_allow_credentials: bool = True
    exec_timeout_sec: int = 30
    exec_runtime: str = "host"
    exec_container_lifecycle: str = "per_action"
    exec_container_image: str = "python:3.11-slim"
    exec_container_image_profile: str = "auto"
    exec_container_image_base: str = "python:3.11-slim"
    exec_container_image_web: str = "python:3.11-slim"
    exec_container_image_data: str = "python:3.11-slim"
    exec_container_image_scraping: str = "python:3.11-slim"
    exec_container_image_ml: str = "python:3.11-slim"
    exec_container_image_qa: str = "python:3.11-slim"
    exec_container_network: str = "none"
    exec_container_cpus: float = 1.0
    exec_container_memory: str = "512m"
    exec_container_pids_limit: int = 256
    exec_container_cache_dir: Path = Path(".softnix/container-cache")
    exec_container_pip_cache_enabled: bool = True
    max_action_output_chars: int = 12000
    no_progress_repeat_threshold: int = 3
    web_fetch_tls_verify: bool = True
    memory_profile_file: str = "memory/PROFILE.md"
    memory_session_file: str = "memory/SESSION.md"
    memory_policy_path: Path = Path(".softnix/system/POLICY.md")
    memory_prompt_max_items: int = 20
    memory_inferred_min_confidence: float = 0.75
    memory_pending_alert_threshold: int = 10
    memory_admin_key: str | None = None

    def __post_init__(self) -> None:
        if self.safe_commands is None:
            self.safe_commands = ["ls", "pwd", "cat", "echo", "python", "pytest", "rm"]
        if self.cors_origins is None:
            self.cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
        if not self.exec_container_image_base:
            self.exec_container_image_base = self.exec_container_image
        if not self.exec_container_image_web:
            self.exec_container_image_web = self.exec_container_image
        if not self.exec_container_image_data:
            self.exec_container_image_data = self.exec_container_image
        if not self.exec_container_image_scraping:
            self.exec_container_image_scraping = self.exec_container_image
        if not self.exec_container_image_ml:
            self.exec_container_image_ml = self.exec_container_image
        if not self.exec_container_image_qa:
            self.exec_container_image_qa = self.exec_container_image


def load_settings() -> Settings:
    _load_dotenv()
    safe_commands_raw = os.getenv("SOFTNIX_SAFE_COMMANDS", "ls,pwd,cat,echo,python,pytest,rm")
    safe_commands = _parse_csv(safe_commands_raw)
    if "rm" not in safe_commands:
        safe_commands.append("rm")
    cors_origins = _parse_csv(
        os.getenv("SOFTNIX_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    )
    cors_allow_credentials = os.getenv("SOFTNIX_CORS_ALLOW_CREDENTIALS", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return Settings(
        provider=os.getenv("SOFTNIX_PROVIDER", "openai"),
        model=os.getenv("SOFTNIX_MODEL", "gpt-4o-mini"),
        max_iters=int(os.getenv("SOFTNIX_MAX_ITERS", "10")),
        workspace=Path(os.getenv("SOFTNIX_WORKSPACE", ".")).resolve(),
        runs_dir=Path(os.getenv("SOFTNIX_RUNS_DIR", ".softnix/runs")),
        skills_dir=Path(os.getenv("SOFTNIX_SKILLS_DIR", "skillpacks")),
        safe_commands=safe_commands,
        openai_api_key=os.getenv("SOFTNIX_OPENAI_API_KEY"),
        openai_base_url=os.getenv("SOFTNIX_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        claude_api_key=os.getenv("SOFTNIX_CLAUDE_API_KEY"),
        claude_base_url=os.getenv("SOFTNIX_CLAUDE_BASE_URL", "https://api.anthropic.com"),
        custom_api_key=os.getenv("SOFTNIX_CUSTOM_API_KEY"),
        custom_base_url=os.getenv("SOFTNIX_CUSTOM_BASE_URL"),
        custom_model=os.getenv("SOFTNIX_CUSTOM_MODEL", "gpt-4o-mini"),
        api_key=os.getenv("SOFTNIX_API_KEY"),
        cors_origins=cors_origins,
        cors_allow_credentials=cors_allow_credentials,
        exec_timeout_sec=int(os.getenv("SOFTNIX_EXEC_TIMEOUT_SEC", "30")),
        exec_runtime=os.getenv("SOFTNIX_EXEC_RUNTIME", "host"),
        exec_container_lifecycle=os.getenv("SOFTNIX_EXEC_CONTAINER_LIFECYCLE", "per_action"),
        exec_container_image=os.getenv("SOFTNIX_EXEC_CONTAINER_IMAGE", "python:3.11-slim"),
        exec_container_image_profile=os.getenv("SOFTNIX_EXEC_CONTAINER_IMAGE_PROFILE", "auto"),
        exec_container_image_base=os.getenv(
            "SOFTNIX_EXEC_CONTAINER_IMAGE_BASE",
            os.getenv("SOFTNIX_EXEC_CONTAINER_IMAGE", "python:3.11-slim"),
        ),
        exec_container_image_web=os.getenv(
            "SOFTNIX_EXEC_CONTAINER_IMAGE_WEB",
            os.getenv("SOFTNIX_EXEC_CONTAINER_IMAGE", "python:3.11-slim"),
        ),
        exec_container_image_data=os.getenv(
            "SOFTNIX_EXEC_CONTAINER_IMAGE_DATA",
            os.getenv("SOFTNIX_EXEC_CONTAINER_IMAGE", "python:3.11-slim"),
        ),
        exec_container_image_scraping=os.getenv(
            "SOFTNIX_EXEC_CONTAINER_IMAGE_SCRAPING",
            os.getenv("SOFTNIX_EXEC_CONTAINER_IMAGE", "python:3.11-slim"),
        ),
        exec_container_image_ml=os.getenv(
            "SOFTNIX_EXEC_CONTAINER_IMAGE_ML",
            os.getenv("SOFTNIX_EXEC_CONTAINER_IMAGE", "python:3.11-slim"),
        ),
        exec_container_image_qa=os.getenv(
            "SOFTNIX_EXEC_CONTAINER_IMAGE_QA",
            os.getenv("SOFTNIX_EXEC_CONTAINER_IMAGE", "python:3.11-slim"),
        ),
        exec_container_network=os.getenv("SOFTNIX_EXEC_CONTAINER_NETWORK", "none"),
        exec_container_cpus=float(os.getenv("SOFTNIX_EXEC_CONTAINER_CPUS", "1.0")),
        exec_container_memory=os.getenv("SOFTNIX_EXEC_CONTAINER_MEMORY", "512m"),
        exec_container_pids_limit=int(os.getenv("SOFTNIX_EXEC_CONTAINER_PIDS_LIMIT", "256")),
        exec_container_cache_dir=Path(os.getenv("SOFTNIX_EXEC_CONTAINER_CACHE_DIR", ".softnix/container-cache")),
        exec_container_pip_cache_enabled=os.getenv("SOFTNIX_EXEC_CONTAINER_PIP_CACHE_ENABLED", "true").lower()
        in {"1", "true", "yes", "on"},
        max_action_output_chars=int(os.getenv("SOFTNIX_MAX_ACTION_OUTPUT_CHARS", "12000")),
        no_progress_repeat_threshold=int(os.getenv("SOFTNIX_NO_PROGRESS_REPEAT_THRESHOLD", "3")),
        web_fetch_tls_verify=os.getenv("SOFTNIX_WEB_FETCH_TLS_VERIFY", "true").lower()
        in {"1", "true", "yes", "on"},
        memory_profile_file=os.getenv("SOFTNIX_MEMORY_PROFILE_FILE", "memory/PROFILE.md"),
        memory_session_file=os.getenv("SOFTNIX_MEMORY_SESSION_FILE", "memory/SESSION.md"),
        memory_policy_path=Path(os.getenv("SOFTNIX_MEMORY_POLICY_PATH", ".softnix/system/POLICY.md")),
        memory_prompt_max_items=int(os.getenv("SOFTNIX_MEMORY_PROMPT_MAX_ITEMS", "20")),
        memory_inferred_min_confidence=float(os.getenv("SOFTNIX_MEMORY_INFERRED_MIN_CONFIDENCE", "0.75")),
        memory_pending_alert_threshold=int(os.getenv("SOFTNIX_MEMORY_PENDING_ALERT_THRESHOLD", "10")),
        memory_admin_key=os.getenv("SOFTNIX_MEMORY_ADMIN_KEY"),
    )


def _parse_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


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
