from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
from typing import Any

from softnix_agentic_agent.types import ActionResult


class SafeActionExecutor:
    def __init__(self, workspace: Path, safe_commands: list[str]) -> None:
        self.workspace = workspace.resolve()
        self.safe_commands = safe_commands

    def execute(self, action: dict[str, Any]) -> ActionResult:
        name = action.get("name", "")
        params = action.get("params", {})
        try:
            if name == "list_dir":
                return self._list_dir(params)
            if name == "read_file":
                return self._read_file(params)
            if name == "write_workspace_file":
                return self._write_workspace_file(params)
            if name == "run_safe_command":
                return self._run_safe_command(params)
            return ActionResult(name=name, ok=False, output="", error=f"Action not allowed: {name}")
        except Exception as exc:
            return ActionResult(name=name, ok=False, output="", error=str(exc))

    def _resolve_workspace_path(self, value: str) -> Path:
        raw = Path(value)
        if raw.is_absolute():
            p = raw.resolve()
        else:
            p = (self.workspace / raw).resolve()
        if not str(p).startswith(str(self.workspace)):
            raise ValueError("Path escapes workspace")
        return p

    def _get_path_param(self, params: dict[str, Any]) -> str:
        path_value = params.get("path")
        if path_value is None:
            path_value = params.get("file_path")
        if path_value is None:
            raise ValueError("Missing required path parameter")
        return str(path_value)

    def _list_dir(self, params: dict[str, Any]) -> ActionResult:
        rel = params.get("path", ".")
        p = self._resolve_workspace_path(str(rel))
        if not p.exists() or not p.is_dir():
            raise ValueError(f"Not a directory: {p}")
        items = sorted([x.name for x in p.iterdir()])
        return ActionResult(name="list_dir", ok=True, output="\n".join(items))

    def _read_file(self, params: dict[str, Any]) -> ActionResult:
        rel = self._get_path_param(params)
        p = self._resolve_workspace_path(str(rel))
        if not p.exists() or not p.is_file():
            raise ValueError(f"Not a file: {p}")
        content = p.read_text(encoding="utf-8")
        return ActionResult(name="read_file", ok=True, output=content[:12000])

    def _write_workspace_file(self, params: dict[str, Any]) -> ActionResult:
        rel = self._get_path_param(params)
        content = str(params.get("content", ""))
        mode = str(params.get("mode", "overwrite"))
        p = self._resolve_workspace_path(str(rel))
        p.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            with p.open("a", encoding="utf-8") as f:
                f.write(content)
        else:
            p.write_text(content, encoding="utf-8")
        return ActionResult(name="write_workspace_file", ok=True, output=f"written: {p}")

    def _run_safe_command(self, params: dict[str, Any]) -> ActionResult:
        command = str(params.get("command", "")).strip()
        if not command:
            raise ValueError("Missing command")
        parts = shlex.split(command)
        if not parts:
            raise ValueError("Invalid command")
        base = parts[0]
        if base not in self.safe_commands:
            raise ValueError(f"Command is not allowlisted: {base}")
        blocked_tokens = {"rm", "sudo", "curl", "wget", "ssh", "scp", "mv"}
        if any(token in blocked_tokens for token in parts):
            raise ValueError("Command contains blocked token")

        proc = subprocess.run(
            parts,
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        if proc.returncode != 0:
            return ActionResult(name="run_safe_command", ok=False, output=output, error=f"exit_code={proc.returncode}")
        return ActionResult(name="run_safe_command", ok=True, output=output.strip())
