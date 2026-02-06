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


def test_write_accepts_file_path_alias(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["ls"])
    result = ex.execute(
        {
            "name": "write_workspace_file",
            "params": {"file_path": "index.html", "content": "<h1>Hello</h1>"},
        }
    )
    assert result.ok is True
    assert (tmp_path / "index.html").exists()


def test_read_allows_absolute_path_in_workspace(tmp_path: Path) -> None:
    p = tmp_path / "note.txt"
    p.write_text("hello", encoding="utf-8")
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["ls"])
    result = ex.execute(
        {
            "name": "read_file",
            "params": {"path": str(p.resolve())},
        }
    )
    assert result.ok is True
    assert result.output == "hello"
