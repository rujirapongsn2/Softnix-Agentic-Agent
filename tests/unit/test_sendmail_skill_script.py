from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types


def _load_sendmail_script():
    if "resend" not in sys.modules:
        fake = types.SimpleNamespace()
        fake.api_key = ""
        fake.Emails = types.SimpleNamespace(send=lambda payload: {"id": "mock-id", "payload": payload})
        fake.Emails.SendParams = dict
        sys.modules["resend"] = fake
    root = Path(__file__).resolve().parents[2]
    script_path = root / "skillpacks" / "resend-email" / "scripts" / "send_email.py"
    spec = importlib.util.spec_from_file_location("send_email_module", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, script_path


def test_load_api_key_from_env(monkeypatch) -> None:
    module, _ = _load_sendmail_script()
    monkeypatch.setenv("RESEND_API_KEY", "re_env_value")
    key = module.load_api_key()
    assert key == "re_env_value"


def test_resolve_sender_uses_env_fallback(monkeypatch) -> None:
    module, _ = _load_sendmail_script()
    monkeypatch.setenv("RESEND_FROM_EMAIL", "Ops <ops@example.com>")
    sender = module.resolve_sender("")
    assert sender == "Ops <ops@example.com>"


def test_write_result_creates_result_json(tmp_path: Path) -> None:
    module, _ = _load_sendmail_script()
    out_dir = tmp_path / "resend_email"
    module.write_result(str(out_dir), {"ok": True, "id": "123"})
    result_file = out_dir / "result.json"
    assert result_file.exists()
    assert "\"ok\": true" in result_file.read_text(encoding="utf-8").lower()
