from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import shlex
import subprocess
from typing import Any
from urllib.parse import urlparse

import httpx

from softnix_agentic_agent.types import ActionResult


class SafeActionExecutor:
    def __init__(
        self,
        workspace: Path,
        safe_commands: list[str],
        command_timeout_sec: int = 30,
        exec_runtime: str = "host",
        exec_container_lifecycle: str = "per_action",
        exec_container_image: str = "python:3.11-slim",
        exec_container_network: str = "none",
        exec_container_cpus: float = 1.0,
        exec_container_memory: str = "512m",
        exec_container_pids_limit: int = 256,
        exec_container_cache_dir: Path | None = None,
        exec_container_pip_cache_enabled: bool = True,
        exec_container_env_vars: list[str] | None = None,
        run_id: str = "",
        max_output_chars: int = 12000,
        web_fetch_tls_verify: bool = True,
    ) -> None:
        self.workspace = workspace.resolve()
        self.safe_commands = safe_commands
        self.command_timeout_sec = command_timeout_sec
        runtime = (exec_runtime or "host").strip().lower()
        if runtime not in {"host", "container"}:
            runtime = "host"
        self.exec_runtime = runtime
        lifecycle = (exec_container_lifecycle or "per_action").strip().lower()
        if lifecycle not in {"per_action", "per_run"}:
            lifecycle = "per_action"
        self.exec_container_lifecycle = lifecycle
        self.exec_container_image = (exec_container_image or "python:3.11-slim").strip()
        self.exec_container_network = (exec_container_network or "none").strip()
        self.exec_container_cpus = max(0.1, float(exec_container_cpus))
        self.exec_container_memory = (exec_container_memory or "512m").strip()
        self.exec_container_pids_limit = max(32, int(exec_container_pids_limit))
        cache_dir = exec_container_cache_dir or (self.workspace / ".softnix/container-cache")
        self.exec_container_cache_dir = Path(cache_dir).resolve()
        self.exec_container_pip_cache_enabled = bool(exec_container_pip_cache_enabled)
        self.exec_container_env_vars = [str(x).strip() for x in (exec_container_env_vars or []) if str(x).strip()]
        if self.exec_container_pip_cache_enabled:
            self.exec_container_cache_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = (run_id or "").strip()
        self._container_started = False
        self._container_name = self._build_container_name(self.run_id)
        self.max_output_chars = max_output_chars
        self.web_fetch_tls_verify = bool(web_fetch_tls_verify)

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
            if name == "write_file":
                return self._write_workspace_file(params)
            if name == "run_safe_command":
                return self._run_safe_command(params)
            if name == "run_shell_command":
                return self._run_safe_command(params)
            if name == "run_python_code":
                return self._run_python_code(params)
            if name == "web_fetch":
                return self._web_fetch(params)
            return ActionResult(name=name, ok=False, output="", error=f"Action not allowed: {name}")
        except Exception as exc:
            return ActionResult(name=name, ok=False, output="", error=str(exc))

    def _resolve_workspace_path(self, value: str) -> Path:
        raw = Path(value)
        if raw.is_absolute():
            p = raw.resolve()
        else:
            p = (self.workspace / raw).resolve()
        if not self._is_within_workspace(p):
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
        raw_args = params.get("args")
        if raw_args is not None:
            if not isinstance(raw_args, list):
                raise ValueError("args must be a list")
            parts.extend(str(x) for x in raw_args)
        parts = self._normalize_python_command_alias(parts)
        base = parts[0]
        if base not in self.safe_commands:
            raise ValueError(f"Command is not allowlisted: {base}")
        blocked_tokens = {"sudo", "curl", "wget", "ssh", "scp", "mv"}
        if any(token in blocked_tokens for token in parts):
            raise ValueError("Command contains blocked token")
        if base == "rm":
            parts = self._hydrate_rm_targets(parts, params)
            self._validate_rm_paths(parts)

        proc = self._run_subprocess(parts)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        output_file, stdout_file, stderr_file, append_mode = self._parse_command_redirect_targets(params)
        written_paths: list[str] = []
        if output_file:
            combined = stdout + (("\n" + stderr) if stderr else "")
            self._write_command_output_file(output_file, combined, append_mode=append_mode)
            written_paths.append(output_file)
        else:
            if stdout_file:
                self._write_command_output_file(stdout_file, stdout, append_mode=append_mode)
                written_paths.append(stdout_file)
            if stderr_file:
                self._write_command_output_file(stderr_file, stderr, append_mode=append_mode)
                written_paths.append(stderr_file)

        raw_output = stdout + ("\n" + stderr if stderr else "")
        output = self._truncate_output(raw_output)
        if written_paths:
            lines = [f"redirected output: {p}" for p in written_paths]
            suffix = "\n".join(lines)
            output = f"{output.strip()}\n{suffix}".strip() if output.strip() else suffix

        if proc.returncode != 0:
            return ActionResult(name="run_safe_command", ok=False, output=output, error=f"exit_code={proc.returncode}")
        return ActionResult(name="run_safe_command", ok=True, output=output.strip())

    def _parse_command_redirect_targets(self, params: dict[str, Any]) -> tuple[str, str, str, bool]:
        output_file = str(params.get("redirect_output", "")).strip() or str(params.get("output_file", "")).strip()
        stdout_file = str(params.get("stdout_path", "")).strip() or str(params.get("redirect_stdout", "")).strip()
        stderr_file = str(params.get("stderr_path", "")).strip() or str(params.get("redirect_stderr", "")).strip()

        if output_file and (stdout_file or stderr_file):
            raise ValueError("Use either redirect_output/output_file OR stdout_path/stderr_path, not both")

        append_raw = params.get("append")
        append_mode = bool(append_raw) if append_raw is not None else str(params.get("mode", "")).strip() == "append"
        return output_file, stdout_file, stderr_file, append_mode

    def _write_command_output_file(self, rel_path: str, content: str, append_mode: bool) -> None:
        target = self._resolve_workspace_path(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if append_mode:
            with target.open("a", encoding="utf-8") as f:
                f.write(content)
            return
        target.write_text(content, encoding="utf-8")

    def _hydrate_rm_targets(self, parts: list[str], params: dict[str, Any]) -> list[str]:
        # Some plans produce "rm -f" and provide paths separately. Hydrate targets from params when needed.
        targets: list[str] = []
        treat_as_target = False
        for token in parts[1:]:
            if token == "--":
                treat_as_target = True
                continue
            if not treat_as_target and token.startswith("-"):
                continue
            targets.append(token)
        if targets:
            return parts

        extra_targets: list[str] = []
        path = params.get("path")
        if path is not None:
            extra_targets.append(str(path))
        paths = params.get("paths")
        if isinstance(paths, list):
            extra_targets.extend(str(x) for x in paths)
        if not extra_targets:
            return parts
        return [*parts, *extra_targets]

    def _run_python_code(self, params: dict[str, Any]) -> ActionResult:
        code = str(params.get("code", "")).strip()
        rel_script_path = str(params.get("path", "")).strip()
        if not code and not rel_script_path:
            raise ValueError("Missing code")

        python_bin = str(params.get("python_bin", "python")).strip()
        if not python_bin:
            raise ValueError("Missing python_bin")
        python_bin = self._normalize_python_bin_alias(python_bin)
        if python_bin not in self.safe_commands:
            raise ValueError(f"Python binary is not allowlisted: {python_bin}")

        args = params.get("args", [])
        if args is None:
            args = []
        if not isinstance(args, list):
            raise ValueError("args must be a list")
        args = [str(x) for x in args]

        if rel_script_path:
            script_path = self._resolve_workspace_path(rel_script_path)
            script_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            work_dir = self._resolve_workspace_path(".softnix_exec")
            work_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix="script_", dir=str(work_dir), delete=False, encoding="utf-8"
            ) as tmp:
                script_path = Path(tmp.name)
                tmp.write(code)
        if rel_script_path and code:
            script_path.write_text(code, encoding="utf-8")
        elif rel_script_path and not script_path.exists():
            raise ValueError(f"Script file not found: {script_path}")

        command_parts = [python_bin, str(script_path), *args]
        proc = self._run_subprocess(command_parts)
        output = self._truncate_output((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else ""))
        if proc.returncode != 0:
            return ActionResult(name="run_python_code", ok=False, output=output, error=f"exit_code={proc.returncode}")
        return ActionResult(name="run_python_code", ok=True, output=output.strip())

    def _normalize_python_command_alias(self, parts: list[str]) -> list[str]:
        if not parts:
            return parts
        base = self._normalize_python_bin_alias(parts[0])
        if base == parts[0]:
            return parts
        return [base, *parts[1:]]

    def _normalize_python_bin_alias(self, python_bin: str) -> str:
        raw = (python_bin or "").strip()
        if raw != "python3":
            return raw
        if "python" in self.safe_commands:
            return "python"
        return raw

    def _validate_rm_paths(self, parts: list[str]) -> None:
        if len(parts) < 2:
            raise ValueError("rm requires at least one path")

        targets: list[str] = []
        treat_as_target = False
        for token in parts[1:]:
            if token == "--":
                treat_as_target = True
                continue
            if not treat_as_target and token.startswith("-"):
                continue
            targets.append(token)

        if not targets:
            raise ValueError("rm requires at least one path")

        for target in targets:
            self._resolve_workspace_path(target)

    def _web_fetch(self, params: dict[str, Any]) -> ActionResult:
        url = str(params.get("url", "")).strip()
        if not url:
            raise ValueError("Missing url")

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only http/https URLs are allowed")
        if not parsed.netloc:
            raise ValueError("Invalid URL")
        if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Fetching localhost is not allowed")

        timeout_sec = float(params.get("timeout_sec", 15))
        max_chars = int(params.get("max_chars", 12000))
        verify_tls = params.get("verify_tls")
        if verify_tls is None:
            verify = self.web_fetch_tls_verify
        else:
            verify = str(verify_tls).strip().lower() in {"1", "true", "yes", "on"}

        try:
            resp = httpx.get(url, timeout=timeout_sec, follow_redirects=True, verify=verify)
        except httpx.ConnectError as exc:
            msg = str(exc)
            if "CERTIFICATE_VERIFY_FAILED" in msg and verify:
                raise ValueError(
                    "SSL certificate verify failed. "
                    "Set SOFTNIX_WEB_FETCH_TLS_VERIFY=false for this environment "
                    "or pass params.verify_tls=false in web_fetch action."
                ) from exc
            raise
        resp.raise_for_status()

        text = resp.text or ""
        if len(text) > max_chars:
            text = text[:max_chars]

        output = (
            f"url={url}\n"
            f"status={resp.status_code}\n"
            f"content_type={resp.headers.get('content-type', '')}\n\n"
            f"{text}"
        )
        return ActionResult(name="web_fetch", ok=True, output=output)

    def _truncate_output(self, text: str) -> str:
        if len(text) <= self.max_output_chars:
            return text
        clipped = text[: self.max_output_chars]
        return f"{clipped}\n\n[truncated to {self.max_output_chars} chars]"

    def _run_subprocess(self, parts: list[str]) -> subprocess.CompletedProcess[str]:
        if self.exec_runtime != "container":
            return self._run_subprocess_raw(parts)
        if self.exec_container_lifecycle == "per_run":
            self._ensure_run_container_started()
            return self._run_subprocess_raw(self._build_container_exec_command(parts))
        return self._run_subprocess_raw(self._build_per_action_container_command(parts))

    def _run_subprocess_raw(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=self.command_timeout_sec,
            check=False,
        )

    def _build_per_action_container_command(self, parts: list[str]) -> list[str]:
        mapped = [self._map_workspace_path_for_container(p) for p in parts]
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            self.exec_container_network,
            "--cpus",
            f"{self.exec_container_cpus:g}",
            "--memory",
            self.exec_container_memory,
            "--pids-limit",
            str(self.exec_container_pids_limit),
            "-v",
            f"{self.workspace}:/workspace",
            "-w",
            "/workspace",
        ]
        command.extend(self._build_container_env_flags())
        if self.exec_container_pip_cache_enabled:
            command.extend(["-v", f"{self.exec_container_cache_dir}:/root/.cache/pip"])
        command.extend([self.exec_container_image, *mapped])
        return command

    def _build_container_bootstrap_command(self) -> list[str]:
        command = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self._container_name,
            "--network",
            self.exec_container_network,
            "--cpus",
            f"{self.exec_container_cpus:g}",
            "--memory",
            self.exec_container_memory,
            "--pids-limit",
            str(self.exec_container_pids_limit),
            "-v",
            f"{self.workspace}:/workspace",
            "-w",
            "/workspace",
        ]
        command.extend(self._build_container_env_flags())
        if self.exec_container_pip_cache_enabled:
            command.extend(["-v", f"{self.exec_container_cache_dir}:/root/.cache/pip"])
        command.extend([self.exec_container_image, "sh", "-lc", "while true; do sleep 3600; done"])
        return command

    def _build_container_exec_command(self, parts: list[str]) -> list[str]:
        mapped = [self._map_workspace_path_for_container(p) for p in parts]
        return ["docker", "exec", self._container_name, *mapped]

    def _map_workspace_path_for_container(self, token: str) -> str:
        text = str(token)
        try:
            resolved = Path(text).resolve()
        except Exception:
            return text
        if not self._is_within_workspace(resolved):
            return text
        rel = resolved.relative_to(self.workspace)
        return str(Path("/workspace") / rel)

    def _ensure_run_container_started(self) -> None:
        if self._container_started:
            return
        bootstrap = self._build_container_bootstrap_command()
        proc = self._run_subprocess_raw(bootstrap)
        if proc.returncode != 0:
            output = self._truncate_output((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else ""))
            raise RuntimeError(f"failed to start run container: {output}")
        self._container_started = True

    def shutdown(self) -> None:
        if not self._container_started:
            return
        subprocess.run(
            ["docker", "rm", "-f", self._container_name],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=min(self.command_timeout_sec, 10),
            check=False,
        )
        self._container_started = False

    def _build_container_name(self, run_id: str) -> str:
        rid = (run_id or "").strip() or "runtime"
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", rid).strip("-")
        if not safe:
            safe = "runtime"
        return f"softnix-run-{safe}"

    def _build_container_env_flags(self) -> list[str]:
        flags: list[str] = []
        for key in self.exec_container_env_vars:
            if not key:
                continue
            if os.getenv(key, "").strip():
                # Use "-e KEY" (without value) so docker reads from host env and avoids embedding secret in args.
                flags.extend(["-e", key])
        return flags

    def _is_within_workspace(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.workspace)
            return True
        except ValueError:
            return False
