from pathlib import Path

from softnix_agentic_agent.agent.executor import SafeActionExecutor


def _executor(tmp_path: Path) -> SafeActionExecutor:
    return SafeActionExecutor(workspace=tmp_path, safe_commands=["echo", "ls", "python"])


def test_list_dir_returns_entries(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("A", encoding="utf-8")
    (tmp_path / "b.txt").write_text("B", encoding="utf-8")

    ex = _executor(tmp_path)
    result = ex.execute({"name": "list_dir", "params": {"path": "."}})

    assert result.ok is True
    assert "a.txt" in result.output
    assert "b.txt" in result.output


def test_read_file_returns_content(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hello world", encoding="utf-8")

    ex = _executor(tmp_path)
    result = ex.execute({"name": "read_file", "params": {"path": "note.txt"}})

    assert result.ok is True
    assert result.output == "hello world"


def test_write_workspace_file_creates_file(tmp_path: Path) -> None:
    ex = _executor(tmp_path)
    result = ex.execute(
        {
            "name": "write_workspace_file",
            "params": {"path": "out/index.html", "content": "<h1>Portfolio</h1>"},
        }
    )

    assert result.ok is True
    assert (tmp_path / "out" / "index.html").read_text(encoding="utf-8") == "<h1>Portfolio</h1>"


def test_write_workspace_file_append_mode(tmp_path: Path) -> None:
    ex = _executor(tmp_path)

    first = ex.execute(
        {
            "name": "write_workspace_file",
            "params": {"path": "out/log.txt", "content": "line1\n"},
        }
    )
    second = ex.execute(
        {
            "name": "write_workspace_file",
            "params": {"path": "out/log.txt", "content": "line2\n", "mode": "append"},
        }
    )

    assert first.ok is True
    assert second.ok is True
    assert (tmp_path / "out" / "log.txt").read_text(encoding="utf-8") == "line1\nline2\n"


def test_run_safe_command_success(tmp_path: Path) -> None:
    ex = _executor(tmp_path)
    result = ex.execute(
        {
            "name": "run_safe_command",
            "params": {"command": "echo hello-softnix"},
        }
    )

    assert result.ok is True
    assert "hello-softnix" in result.output


def test_run_safe_command_rejects_non_allowlisted(tmp_path: Path) -> None:
    ex = _executor(tmp_path)
    result = ex.execute(
        {
            "name": "run_safe_command",
            "params": {"command": "cat /etc/hosts"},
        }
    )

    assert result.ok is False
    assert "allowlisted" in (result.error or "")
