from pathlib import Path
import subprocess

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


def test_container_runtime_wraps_safe_command_with_docker(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run(parts, cwd, text, capture_output, timeout, check):  # type: ignore[no-untyped-def]
        captured["parts"] = parts
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(args=parts, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    ex = SafeActionExecutor(
        workspace=tmp_path,
        safe_commands=["ls"],
        exec_runtime="container",
        exec_container_image="python:3.11-slim",
    )
    result = ex.execute({"name": "run_safe_command", "params": {"command": "ls"}})
    assert result.ok is True
    parts = captured["parts"]
    assert isinstance(parts, list)
    assert parts[0] == "docker"
    assert "run" in parts
    assert "python:3.11-slim" in parts
    assert "ls" in parts


def test_container_runtime_maps_python_script_path(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run(parts, cwd, text, capture_output, timeout, check):  # type: ignore[no-untyped-def]
        captured["parts"] = parts
        return subprocess.CompletedProcess(args=parts, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    ex = SafeActionExecutor(
        workspace=tmp_path,
        safe_commands=["python"],
        exec_runtime="container",
        exec_container_image="python:3.11-slim",
    )
    result = ex.execute({"name": "run_python_code", "params": {"code": "print('x')"}})
    assert result.ok is True
    parts = captured["parts"]
    assert isinstance(parts, list)
    joined = " ".join(str(x) for x in parts)
    assert "/workspace/.softnix_exec/" in joined


def test_container_runtime_per_run_reuses_container_and_shutdown(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def _fake_run(parts, cwd, text, capture_output, timeout, check):  # type: ignore[no-untyped-def]
        calls.append([str(x) for x in parts])
        return subprocess.CompletedProcess(args=parts, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    ex = SafeActionExecutor(
        workspace=tmp_path,
        safe_commands=["ls", "python"],
        exec_runtime="container",
        exec_container_lifecycle="per_run",
        exec_container_image="python:3.11-slim",
        run_id="runabc",
    )

    r1 = ex.execute({"name": "run_safe_command", "params": {"command": "ls"}})
    r2 = ex.execute({"name": "run_python_code", "params": {"code": "print('x')"}})
    ex.shutdown()

    assert r1.ok is True
    assert r2.ok is True
    assert len(calls) >= 4
    assert calls[0][:2] == ["docker", "run"]
    assert "--name" in calls[0]
    assert "softnix-run-runabc" in calls[0]
    assert calls[1][:2] == ["docker", "exec"]
    assert calls[2][:2] == ["docker", "exec"]
    assert calls[-1][:3] == ["docker", "rm", "-f"]


def test_run_python_code_can_execute_existing_script_by_path_only(tmp_path: Path) -> None:
    script = tmp_path / "runner.py"
    script.write_text("print('ok-from-path')\n", encoding="utf-8")
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["python"])
    result = ex.execute({"name": "run_python_code", "params": {"path": "runner.py"}})
    assert result.ok is True
    assert "ok-from-path" in result.output


def test_run_python_code_accepts_python3_alias_when_python_is_allowlisted(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["python"])
    result = ex.execute(
        {
            "name": "run_python_code",
            "params": {"code": "print('ok-alias')", "python_bin": "python3"},
        }
    )
    assert result.ok is True
    assert "ok-alias" in result.output


def test_run_safe_command_accepts_python3_alias_when_python_is_allowlisted(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["python"])
    result = ex.execute(
        {
            "name": "run_safe_command",
            "params": {"command": "python3 -c \"print('ok-shell-alias')\""},
        }
    )
    assert result.ok is True
    assert "ok-shell-alias" in result.output


def test_run_safe_command_supports_structured_args_and_stdout_path(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["python"])
    result = ex.execute(
        {
            "name": "run_safe_command",
            "params": {
                "command": "python",
                "args": ["-c", "print('ok-structured')"],
                "stdout_path": "result.txt",
            },
        }
    )
    assert result.ok is True
    assert (tmp_path / "result.txt").exists() is True
    assert (tmp_path / "result.txt").read_text(encoding="utf-8").strip() == "ok-structured"
    assert "redirected output: result.txt" in result.output


def test_run_safe_command_legacy_redirect_output_writes_combined_stream(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["python"])
    result = ex.execute(
        {
            "name": "run_safe_command",
            "params": {
                "command": "python",
                "args": ["-c", "import sys; print('out'); print('err', file=sys.stderr)"],
                "redirect_output": "combined.txt",
            },
        }
    )
    assert result.ok is True
    content = (tmp_path / "combined.txt").read_text(encoding="utf-8")
    assert "out" in content
    assert "err" in content


def test_run_safe_command_rejects_non_list_args(tmp_path: Path) -> None:
    ex = SafeActionExecutor(workspace=tmp_path, safe_commands=["python"])
    result = ex.execute(
        {
            "name": "run_safe_command",
            "params": {"command": "python", "args": "not-a-list"},
        }
    )
    assert result.ok is False
    assert "args must be a list" in (result.error or "")
