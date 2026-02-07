from pathlib import Path

import httpx

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


def test_web_fetch_rejects_localhost(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["ls"])
    result = ex.execute({"name": "web_fetch", "params": {"url": "http://127.0.0.1:8787"}})
    assert result.ok is False
    assert "localhost" in (result.error or "")


def test_web_fetch_success_with_mock(tmp_path: Path, monkeypatch) -> None:
    class _Resp:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        text = "<html>Hello</html>"

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url, timeout, follow_redirects, verify):  # type: ignore[no-untyped-def]
        assert url == "https://example.com"
        assert timeout == 15.0
        assert follow_redirects is True
        assert verify is True
        return _Resp()

    monkeypatch.setattr(httpx, "get", _fake_get)
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["ls"])
    result = ex.execute({"name": "web_fetch", "params": {"url": "https://example.com"}})
    assert result.ok is True
    assert "status=200" in result.output
    assert "<html>Hello</html>" in result.output


def test_rm_allowed_within_workspace(tmp_path: Path) -> None:
    target = tmp_path / "delete_me.txt"
    target.write_text("x", encoding="utf-8")
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["rm"])
    result = ex.execute({"name": "run_safe_command", "params": {"command": "rm delete_me.txt"}})
    assert result.ok is True
    assert target.exists() is False


def test_rm_rejects_outside_workspace(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["rm"])
    result = ex.execute({"name": "run_safe_command", "params": {"command": "rm ../outside.txt"}})
    assert result.ok is False
    assert "workspace" in (result.error or "")


def test_run_python_code_rejects_non_allowlisted_binary(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["ls"])
    result = ex.execute(
        {
            "name": "run_python_code",
            "params": {"code": "print('x')", "python_bin": "python"},
        }
    )
    assert result.ok is False
    assert "allowlisted" in (result.error or "")


def test_rm_supports_targets_from_params(tmp_path: Path) -> None:
    target = tmp_path / "script.py"
    target.write_text("print('x')", encoding="utf-8")
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["rm"])
    result = ex.execute({"name": "run_safe_command", "params": {"command": "rm -f", "path": "script.py"}})
    assert result.ok is True
    assert target.exists() is False
