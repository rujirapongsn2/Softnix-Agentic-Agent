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
