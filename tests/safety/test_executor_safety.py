from pathlib import Path

from softnix_agentic_agent.agent.executor import SafeActionExecutor


def test_reject_action_not_allowlisted(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["ls"])
    result = ex.execute({"name": "bad_action", "params": {}})
    assert result.ok is False
    assert "not allowed" in (result.error or "")


def test_reject_write_outside_workspace(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["ls"])
    result = ex.execute(
        {
            "name": "write_workspace_file",
            "params": {"path": "../escape.txt", "content": "x"},
        }
    )
    assert result.ok is False
    assert "escapes workspace" in (result.error or "")


def test_reject_disallowed_command(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["ls"])
    result = ex.execute({"name": "run_safe_command", "params": {"command": "rm -rf ."}})
    assert result.ok is False
    assert "allowlisted" in (result.error or "") or "blocked" in (result.error or "")
