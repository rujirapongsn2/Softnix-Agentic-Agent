from pathlib import Path

from softnix_agentic_agent.config import load_settings


def test_load_settings_reads_dotenv(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "SOFTNIX_PROVIDER=openai\nSOFTNIX_OPENAI_API_KEY=test-key\nSOFTNIX_MAX_ITERS=7\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SOFTNIX_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SOFTNIX_MAX_ITERS", raising=False)

    settings = load_settings()

    assert settings.openai_api_key == "test-key"
    assert settings.max_iters == 7


def test_shell_env_overrides_dotenv(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("SOFTNIX_MODEL=dotenv-model\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SOFTNIX_MODEL", "shell-model")

    settings = load_settings()

    assert settings.model == "shell-model"


def test_security_config_from_env(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "SOFTNIX_API_KEY=abc123\n"
        "SOFTNIX_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:5173\n"
        "SOFTNIX_CORS_ALLOW_CREDENTIALS=false\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SOFTNIX_API_KEY", raising=False)
    monkeypatch.delenv("SOFTNIX_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("SOFTNIX_CORS_ALLOW_CREDENTIALS", raising=False)

    settings = load_settings()

    assert settings.api_key == "abc123"
    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:5173"]
    assert settings.cors_allow_credentials is False


def test_execution_runtime_config_from_env(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "SOFTNIX_EXEC_TIMEOUT_SEC=45\n"
        "SOFTNIX_EXEC_RUNTIME=container\n"
        "SOFTNIX_EXEC_CONTAINER_LIFECYCLE=per_run\n"
        "SOFTNIX_EXEC_CONTAINER_IMAGE=python:3.12-slim\n"
        "SOFTNIX_EXEC_CONTAINER_IMAGE_PROFILE=web\n"
        "SOFTNIX_EXEC_CONTAINER_IMAGE_BASE=python:3.12-base\n"
        "SOFTNIX_EXEC_CONTAINER_IMAGE_WEB=python:3.12-web\n"
        "SOFTNIX_EXEC_CONTAINER_IMAGE_DATA=python:3.12-data\n"
        "SOFTNIX_EXEC_CONTAINER_IMAGE_SCRAPING=python:3.12-scraping\n"
        "SOFTNIX_EXEC_CONTAINER_IMAGE_ML=python:3.12-ml\n"
        "SOFTNIX_EXEC_CONTAINER_IMAGE_QA=python:3.12-qa\n"
        "SOFTNIX_EXEC_CONTAINER_NETWORK=none\n"
        "SOFTNIX_EXEC_CONTAINER_CPUS=1.5\n"
        "SOFTNIX_EXEC_CONTAINER_MEMORY=768m\n"
        "SOFTNIX_EXEC_CONTAINER_PIDS_LIMIT=300\n"
        "SOFTNIX_EXEC_CONTAINER_CACHE_DIR=.softnix/test-cache\n"
        "SOFTNIX_EXEC_CONTAINER_PIP_CACHE_ENABLED=false\n"
        "SOFTNIX_MAX_ACTION_OUTPUT_CHARS=5000\n"
        "SOFTNIX_NO_PROGRESS_REPEAT_THRESHOLD=4\n"
        "SOFTNIX_WEB_FETCH_TLS_VERIFY=false\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SOFTNIX_EXEC_TIMEOUT_SEC", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_RUNTIME", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_LIFECYCLE", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_IMAGE", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_IMAGE_PROFILE", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_IMAGE_BASE", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_IMAGE_WEB", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_IMAGE_DATA", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_IMAGE_SCRAPING", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_IMAGE_ML", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_IMAGE_QA", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_NETWORK", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_CPUS", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_MEMORY", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_PIDS_LIMIT", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_CACHE_DIR", raising=False)
    monkeypatch.delenv("SOFTNIX_EXEC_CONTAINER_PIP_CACHE_ENABLED", raising=False)
    monkeypatch.delenv("SOFTNIX_MAX_ACTION_OUTPUT_CHARS", raising=False)
    monkeypatch.delenv("SOFTNIX_NO_PROGRESS_REPEAT_THRESHOLD", raising=False)
    monkeypatch.delenv("SOFTNIX_WEB_FETCH_TLS_VERIFY", raising=False)

    settings = load_settings()
    assert settings.exec_timeout_sec == 45
    assert settings.exec_runtime == "container"
    assert settings.exec_container_lifecycle == "per_run"
    assert settings.exec_container_image == "python:3.12-slim"
    assert settings.exec_container_image_profile == "web"
    assert settings.exec_container_image_base == "python:3.12-base"
    assert settings.exec_container_image_web == "python:3.12-web"
    assert settings.exec_container_image_data == "python:3.12-data"
    assert settings.exec_container_image_scraping == "python:3.12-scraping"
    assert settings.exec_container_image_ml == "python:3.12-ml"
    assert settings.exec_container_image_qa == "python:3.12-qa"
    assert settings.exec_container_network == "none"
    assert settings.exec_container_cpus == 1.5
    assert settings.exec_container_memory == "768m"
    assert settings.exec_container_pids_limit == 300
    assert str(settings.exec_container_cache_dir) == ".softnix/test-cache"
    assert settings.exec_container_pip_cache_enabled is False
    assert settings.max_action_output_chars == 5000
    assert settings.no_progress_repeat_threshold == 4
    assert settings.web_fetch_tls_verify is False


def test_memory_config_from_env(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "SOFTNIX_MEMORY_PROFILE_FILE=MY_PROFILE.md\n"
        "SOFTNIX_MEMORY_SESSION_FILE=MY_SESSION.md\n"
        "SOFTNIX_MEMORY_POLICY_PATH=.softnix/system/ORG_POLICY.md\n"
        "SOFTNIX_MEMORY_PROMPT_MAX_ITEMS=9\n"
        "SOFTNIX_MEMORY_INFERRED_MIN_CONFIDENCE=0.9\n"
        "SOFTNIX_MEMORY_PENDING_ALERT_THRESHOLD=7\n"
        "SOFTNIX_MEMORY_ADMIN_KEY=mem-admin\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SOFTNIX_MEMORY_PROFILE_FILE", raising=False)
    monkeypatch.delenv("SOFTNIX_MEMORY_SESSION_FILE", raising=False)
    monkeypatch.delenv("SOFTNIX_MEMORY_POLICY_PATH", raising=False)
    monkeypatch.delenv("SOFTNIX_MEMORY_PROMPT_MAX_ITEMS", raising=False)
    monkeypatch.delenv("SOFTNIX_MEMORY_INFERRED_MIN_CONFIDENCE", raising=False)
    monkeypatch.delenv("SOFTNIX_MEMORY_PENDING_ALERT_THRESHOLD", raising=False)
    monkeypatch.delenv("SOFTNIX_MEMORY_ADMIN_KEY", raising=False)

    settings = load_settings()
    assert settings.memory_profile_file == "MY_PROFILE.md"
    assert settings.memory_session_file == "MY_SESSION.md"
    assert str(settings.memory_policy_path) == ".softnix/system/ORG_POLICY.md"
    assert settings.memory_prompt_max_items == 9
    assert settings.memory_inferred_min_confidence == 0.9
    assert settings.memory_pending_alert_threshold == 7
    assert settings.memory_admin_key == "mem-admin"
