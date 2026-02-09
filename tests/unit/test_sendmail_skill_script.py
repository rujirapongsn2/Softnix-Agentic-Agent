from __future__ import annotations

import argparse
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
    script_path = root / "skillpacks" / "sendmail" / "scripts" / "send_with_resend.py"
    spec = importlib.util.spec_from_file_location("send_with_resend_module", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, script_path


def test_resolve_api_key_from_env() -> None:
    module, script_path = _load_sendmail_script()
    env = {"RESEND_API_KEY": "re_env_value"}
    key = module.resolve_api_key(env, str(script_path))
    assert key == "re_env_value"


def test_resolve_api_key_from_default_skill_secret_file(tmp_path: Path) -> None:
    module, script_path = _load_sendmail_script()
    secrets_dir = tmp_path / "sendmail" / ".secrets"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "RESEND_API_KEY").write_text("re_file_value\n", encoding="utf-8")
    fake_script = tmp_path / "sendmail" / "scripts" / "send_with_resend.py"
    fake_script.parent.mkdir(parents=True)
    fake_script.write_text("# fake", encoding="utf-8")
    key = module.resolve_api_key({}, str(fake_script))
    assert key == "re_file_value"


def test_build_payload_accepts_text_or_html() -> None:
    module, _ = _load_sendmail_script()
    args = argparse.Namespace(
        from_email="Acme <onboarding@resend.dev>",
        to="a@example.com,b@example.com",
        subject="Hello",
        text="body",
        html="",
    )
    payload = module.build_payload(args)
    assert payload["from"] == "Acme <onboarding@resend.dev>"
    assert payload["to"] == ["a@example.com", "b@example.com"]
    assert payload["subject"] == "Hello"
    assert payload["text"] == "body"


def test_build_payload_requires_recipient() -> None:
    module, _ = _load_sendmail_script()
    args = argparse.Namespace(
        from_email="Acme <onboarding@resend.dev>",
        to="",
        subject="Hello",
        text="body",
        html="",
    )
    try:
        module.build_payload(args)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "recipient" in str(exc)


def test_build_payload_requires_body() -> None:
    module, _ = _load_sendmail_script()
    args = argparse.Namespace(
        from_email="Acme <onboarding@resend.dev>",
        to="a@example.com",
        subject="Hello",
        text="",
        html="",
    )
    try:
        module.build_payload(args)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "body" in str(exc)
