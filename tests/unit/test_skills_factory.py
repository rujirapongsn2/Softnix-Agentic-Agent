from pathlib import Path

from softnix_agentic_agent.skills.factory import SkillCreateRequest, create_skill_scaffold, validate_skill_dir


def test_create_skill_scaffold_with_secret_and_validate_ready(tmp_path: Path) -> None:
    req = SkillCreateRequest(
        skills_root=tmp_path,
        name="Order Status",
        description="check order status via API",
        guidance="use order id from user",
        api_key_name="ORDER_API_KEY",
        api_key_value="ord_test_123",
        endpoint_template="/orders/{item_id}",
    )
    created = create_skill_scaffold(req)
    assert created.skill_name == "order-status"
    assert (tmp_path / "order-status" / "SKILL.md").exists()
    assert (tmp_path / "order-status" / "scripts" / "check_status.py").exists()
    assert (tmp_path / "order-status" / ".secret" / "ORDER_API_KEY").exists()

    result = validate_skill_dir(tmp_path / "order-status", run_smoke=True)
    assert result.ok is True
    assert result.ready is True
    assert any(check.startswith("smoke_ok:") for check in result.checks)


def test_create_skill_scaffold_without_secret_value_is_not_ready(tmp_path: Path) -> None:
    req = SkillCreateRequest(
        skills_root=tmp_path,
        name="Order Status",
        description="check order status via API",
        api_key_name="ORDER_API_KEY",
        api_key_value="",
    )
    _ = create_skill_scaffold(req)
    result = validate_skill_dir(tmp_path / "order-status", run_smoke=False)
    assert result.ok is True
    assert result.ready is False
    assert ".secret/ORDER_API_KEY is empty or placeholder" in result.warnings


def test_validate_skill_dir_rejects_legacy_secrets_folder(tmp_path: Path) -> None:
    skill_dir = tmp_path / "demo-skill"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / ".secrets").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: demo
---
Use scripts/check_status.py
""",
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "check_status.py").write_text("print('ok')\n", encoding="utf-8")

    result = validate_skill_dir(skill_dir, run_smoke=False)
    assert result.ok is False
    assert "legacy .secrets folder detected; use .secret instead" in result.errors
