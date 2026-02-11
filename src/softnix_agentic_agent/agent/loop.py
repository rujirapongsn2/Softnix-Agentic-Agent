from __future__ import annotations

import copy
import ast
import hashlib
import json
import re
import shlex
import uuid
from pathlib import Path
from typing import Any

from softnix_agentic_agent.agent.executor import SafeActionExecutor
from softnix_agentic_agent.agent.planner import Planner
from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.memory.markdown_store import MarkdownMemoryStore
from softnix_agentic_agent.memory.service import CoreMemoryService
from softnix_agentic_agent.skills.loader import SkillLoader
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.types import IterationRecord, RunState, RunStatus, StopReason, utc_now_iso


class AgentLoopRunner:
    def __init__(self, settings: Settings, planner: Planner, store: FilesystemStore) -> None:
        self.settings = settings
        self.planner = planner
        self.store = store

    def start_run(
        self,
        task: str,
        provider_name: str,
        model: str,
        workspace: Path,
        skills_dir: Path,
        max_iters: int,
    ) -> RunState:
        state = self.prepare_run(
            task=task,
            provider_name=provider_name,
            model=model,
            workspace=workspace,
            skills_dir=skills_dir,
            max_iters=max_iters,
        )
        return self.execute_prepared_run(state.run_id)

    def prepare_run(
        self,
        task: str,
        provider_name: str,
        model: str,
        workspace: Path,
        skills_dir: Path,
        max_iters: int,
    ) -> RunState:
        run_id = uuid.uuid4().hex[:12]
        state = RunState(
            run_id=run_id,
            task=task,
            provider=provider_name,
            model=model,
            workspace=str(workspace.resolve()),
            skills_dir=str(skills_dir.resolve()),
            max_iters=max_iters,
        )
        self.store.init_run(state)
        return state

    def execute_prepared_run(self, run_id: str) -> RunState:
        state = self.store.read_state(run_id)
        return self._run_loop(state)

    def resume_run(self, run_id: str) -> RunState:
        state = self.store.read_state(run_id)
        if state.status in {RunStatus.COMPLETED, RunStatus.CANCELED, RunStatus.FAILED}:
            return state
        return self._run_loop(state)

    def _run_loop(self, state: RunState) -> RunState:
        skill_loader = SkillLoader(Path(state.skills_dir))
        selected_for_runtime = skill_loader.select_skills(task=state.task)
        runtime_image, runtime_profile = self._resolve_container_runtime_image(state.task, selected_for_runtime)
        if self.settings.exec_runtime == "container":
            self.store.log_event(
                state.run_id,
                f"container runtime profile={runtime_profile} image={runtime_image}",
            )
        memory_store = MarkdownMemoryStore(
            workspace=Path(state.workspace),
            policy_path=self.settings.memory_policy_path,
            profile_file=self.settings.memory_profile_file,
            session_file=self.settings.memory_session_file,
        )
        memory = CoreMemoryService(
            memory_store,
            self.store,
            state.run_id,
            inferred_min_confidence=self.settings.memory_inferred_min_confidence,
        )
        memory.ensure_ready()

        executor = SafeActionExecutor(
            workspace=Path(state.workspace),
            safe_commands=self.settings.safe_commands,
            command_timeout_sec=self.settings.exec_timeout_sec,
            exec_runtime=self.settings.exec_runtime,
            exec_container_lifecycle=self.settings.exec_container_lifecycle,
            exec_container_image=runtime_image,
            exec_container_network=self.settings.exec_container_network,
            exec_container_cpus=self.settings.exec_container_cpus,
            exec_container_memory=self.settings.exec_container_memory,
            exec_container_pids_limit=self.settings.exec_container_pids_limit,
            exec_container_cache_dir=self.settings.exec_container_cache_dir,
            exec_container_pip_cache_enabled=self.settings.exec_container_pip_cache_enabled,
            exec_container_env_vars=self.settings.exec_container_env_vars,
            run_id=state.run_id,
            max_output_chars=self.settings.max_action_output_chars,
            web_fetch_tls_verify=self.settings.web_fetch_tls_verify,
        )
        previous_iteration_signature = ""
        repeated_iteration_count = 0
        produced_files_in_run: set[str] = set()
        previous_iteration_had_failed_action = False

        try:
            if state.iteration == 0:
                memory_decisions = memory.apply_confirmation_text(state.task)
                if memory_decisions:
                    self.store.log_event(state.run_id, f"memory decisions entries={len(memory_decisions)}")

                memory_changes = memory.apply_user_text(state.task)
                if memory_changes:
                    self.store.log_event(state.run_id, f"memory updated entries={len(memory_changes)}")

                memory_staged = memory.stage_inferred_preferences(state.task)
                if memory_staged:
                    self.store.log_event(state.run_id, f"memory staged entries={len(memory_staged)}")

            while state.iteration < state.max_iters:
                try:
                    compact_stats = memory.compact(["profile", "session"])
                    if compact_stats["removed_expired"] or compact_stats["removed_duplicates"]:
                        self.store.log_event(
                            state.run_id,
                            "memory compact "
                            f"expired={compact_stats['removed_expired']} "
                            f"duplicates={compact_stats['removed_duplicates']}",
                        )
                except Exception as exc:
                    memory.record_compact_failure(str(exc))
                    self.store.log_event(state.run_id, f"alert: memory compact failed error={exc}")

                latest = self.store.read_state(state.run_id)
                if latest.cancel_requested:
                    state.cancel_requested = True
                    state.status = RunStatus.CANCELED
                    state.stop_reason = StopReason.CANCELED
                    state.updated_at = utc_now_iso()
                    self.store.write_state(state)
                    self.store.log_event(state.run_id, "stopped by cancel request")
                    return state

                current_iteration = state.iteration + 1
                selected_skills = skill_loader.select_skills(task=state.task)
                if selected_skills:
                    selected_names = ",".join(skill.name for skill in selected_skills)
                else:
                    selected_names = "(none)"
                self.store.log_event(state.run_id, f"skills selected iteration={current_iteration} names={selected_names}")
                skills_context = skill_loader.render_compact_context(task=state.task)
                memory_context = memory.build_prompt_context(max_items=self.settings.memory_prompt_max_items)
                plan, token_usage, prompt_text = self.planner.build_plan(
                    task=state.task,
                    iteration=current_iteration,
                    max_iters=state.max_iters,
                    previous_output=state.last_output,
                    skills_context=skills_context,
                    memory_context=memory_context,
                )

                actions = plan.get("actions", []) if isinstance(plan.get("actions", []), list) else []
                action_results = []
                for action in actions:
                    prepared_action = self._prepare_action(
                        action,
                        state.task,
                        Path(state.workspace),
                        Path(state.skills_dir),
                    )
                    action_name = str(prepared_action.get("name", ""))
                    if not self._is_action_allowed_by_policy(action_name, memory):
                        error = f"blocked by policy.allow.tools: {action_name}"
                        result_payload = {
                            "name": action_name,
                            "ok": False,
                            "output": "",
                            "error": error,
                        }
                        action_results.append(result_payload)
                        self.store.log_event(state.run_id, f"policy blocked action name={action_name}")
                        self.store.append_memory_audit(
                            state.run_id,
                            {
                                "op": "policy_block",
                                "scope": "policy",
                                "key": "policy.allow.tools",
                                "action": action_name,
                                "actor": "system",
                                "reason": error,
                            },
                        )
                        continue

                    result = executor.execute(prepared_action)
                    action_results.append(
                        {
                            "name": result.name,
                            "ok": result.ok,
                            "output": result.output,
                            "error": result.error,
                        }
                    )
                new_artifacts = self._snapshot_artifacts(state, actions, action_results)
                produced_files_in_run.update(new_artifacts)

                memory_metrics = memory.collect_metrics(
                    pending_alert_threshold=self.settings.memory_pending_alert_threshold
                )
                self.store.log_event(
                    state.run_id,
                    f"memory metrics pending_count={memory_metrics['pending_count']}",
                )
                if memory_metrics["pending_backlog_alert"]:
                    self.store.log_event(
                        state.run_id,
                        "alert: memory pending backlog "
                        f"{memory_metrics['pending_count']} >= "
                        f"{memory_metrics['pending_alert_threshold']}",
                    )

                done = bool(plan.get("done", False))
                output = str(plan.get("final_output") or "")
                if not output and action_results:
                    output = "\n\n".join(
                        [
                            (
                                f"[{x['name']}] ok={x['ok']}\n{x['output']}\n"
                                + (f"error={x['error']}" if x.get("error") else "")
                            ).strip()
                            for x in action_results
                        ]
                    )
                has_failed_action = any(not bool(result.get("ok")) for result in action_results)

                if done:
                    if has_failed_action:
                        done = False
                        output = (
                            (output + "\n\n" if output else "")
                            + "[validation] failed; continue iterations\n"
                            + "- current iteration has failed actions"
                        )
                        self.store.log_event(state.run_id, "objective validation blocked by failed actions in iteration")
                    elif previous_iteration_had_failed_action and not actions:
                        done = False
                        output = (
                            (output + "\n\n" if output else "")
                            + "[validation] failed; continue iterations\n"
                            + "- previous iteration failed and no recovery action executed"
                        )
                        self.store.log_event(state.run_id, "objective validation blocked by unresolved previous failure")

                if done:
                    validation_report = self._evaluate_objective_validations(
                        task=state.task,
                        plan=plan,
                        workspace=Path(state.workspace),
                        produced_files=produced_files_in_run,
                    )
                    plan["validation"] = validation_report
                    if not validation_report["ok"]:
                        done = False
                        failures = validation_report["failures"]
                        failure_text = "\n".join(f"- {item}" for item in failures)
                        output = (
                            (output + "\n\n" if output else "")
                            + "[validation] failed; continue iterations\n"
                            + failure_text
                        )
                        self.store.log_event(
                            state.run_id,
                            f"objective validation failed count={len(failures)}",
                        )
                    else:
                        self.store.log_event(state.run_id, "objective validation passed")

                record = IterationRecord(
                    run_id=state.run_id,
                    iteration=current_iteration,
                    timestamp=utc_now_iso(),
                    prompt=prompt_text,
                    plan=plan,
                    actions=actions,
                    action_results=action_results,
                    output=output,
                    done=done,
                    token_usage=token_usage,
                )
                self.store.append_iteration(record)
                self.store.log_event(state.run_id, f"iteration={current_iteration} done={done}")

                state.iteration = current_iteration
                state.last_output = output
                state.updated_at = utc_now_iso()

                if done:
                    state.status = RunStatus.COMPLETED
                    state.stop_reason = StopReason.COMPLETED
                    self.store.write_state(state)
                    return state

                if not has_failed_action:
                    auto_complete_report = self._evaluate_auto_complete_validations(
                        task=state.task,
                        workspace=Path(state.workspace),
                        produced_files=produced_files_in_run,
                    )
                    if auto_complete_report.get("checks") and auto_complete_report.get("ok"):
                        state.status = RunStatus.COMPLETED
                        state.stop_reason = StopReason.COMPLETED
                        state.updated_at = utc_now_iso()
                        self.store.write_state(state)
                        self.store.log_event(
                            state.run_id,
                            "objective auto-completed from inferred validations",
                        )
                        return state

                self.store.write_state(state)
                previous_iteration_had_failed_action = has_failed_action

                current_sig = self._build_iteration_signature(actions=actions, action_results=action_results, output=output)
                if current_sig == previous_iteration_signature:
                    repeated_iteration_count += 1
                else:
                    repeated_iteration_count = 1
                    previous_iteration_signature = current_sig

                threshold = max(2, int(self.settings.no_progress_repeat_threshold))
                if repeated_iteration_count >= threshold:
                    state.status = RunStatus.FAILED
                    state.stop_reason = StopReason.NO_PROGRESS
                    state.updated_at = utc_now_iso()
                    self.store.write_state(state)
                    action_names = ",".join(str(a.get("name", "")) for a in actions) or "(none)"
                    self.store.log_event(
                        state.run_id,
                        "stopped: no_progress detected "
                        f"repeated={repeated_iteration_count} "
                        f"signature={current_sig[:12]} actions={action_names}",
                    )
                    return state

            state.status = RunStatus.FAILED
            state.stop_reason = StopReason.MAX_ITERS
            state.updated_at = utc_now_iso()
            self.store.write_state(state)
            self.store.log_event(state.run_id, "stopped: max_iters reached")
            return state

        except KeyboardInterrupt:
            state.status = RunStatus.CANCELED
            state.stop_reason = StopReason.INTERRUPTED
            state.updated_at = utc_now_iso()
            self.store.write_state(state)
            self.store.log_event(state.run_id, "stopped: keyboard interrupt")
            return state
        except Exception as exc:
            state.status = RunStatus.FAILED
            state.stop_reason = StopReason.ERROR
            state.updated_at = utc_now_iso()
            self.store.write_state(state)
            self.store.log_event(state.run_id, f"error: {exc}")
            return state
        finally:
            executor.shutdown()

    def _snapshot_artifacts(
        self,
        state: RunState,
        actions: list[dict[str, Any]],
        action_results: list[dict[str, Any]],
    ) -> set[str]:
        workspace = Path(state.workspace)
        snapshotted: set[str] = set()
        output_extract_actions = {
            "run_python_code",
            "run_safe_command",
            "run_shell_command",
            "write_workspace_file",
            "write_file",
        }
        for action, result in zip(actions, action_results):
            action_name = str(action.get("name", ""))
            result_name = str(result.get("name", ""))
            if not bool(result.get("ok")):
                continue
            params = action.get("params", {}) if isinstance(action.get("params"), dict) else {}
            candidate_paths: list[str] = []
            raw_path = params.get("path") or params.get("file_path")
            if raw_path is not None and (
                action_name in {"write_workspace_file", "write_file"} or result_name == "write_workspace_file"
            ):
                candidate_paths.append(str(raw_path))
            if action_name == "run_python_code" or result_name == "run_python_code":
                candidate_paths.extend(self._extract_python_output_targets(params=params, workspace=workspace))

            output = str(result.get("output") or "")
            if output and (action_name in output_extract_actions or result_name in output_extract_actions):
                candidate_paths.extend(self._extract_existing_file_targets_from_text(output, workspace))

            for raw in candidate_paths:
                try:
                    rel = self.store.snapshot_workspace_file(state.run_id, workspace, str(raw))
                    if rel in snapshotted:
                        continue
                    snapshotted.add(rel)
                    self.store.log_event(state.run_id, f"artifact saved: {rel}")
                except Exception as exc:
                    self.store.log_event(state.run_id, f"artifact snapshot failed: {exc}")
        return snapshotted

    def _extract_python_output_targets(self, params: dict[str, Any], workspace: Path) -> list[str]:
        raw_candidates: list[str] = []

        def _append_raw(value: Any) -> None:
            text = str(value or "").strip()
            if text:
                raw_candidates.append(text)

        args = params.get("args")
        if isinstance(args, list):
            dir_flags = {"--out-dir", "--output-dir", "--artifact-dir", "--artifacts-dir"}
            path_flags = {"--output", "--out", "--out-file", "--result-file", "--summary-path", "--meta-path"}
            i = 0
            while i < len(args):
                token = str(args[i]).strip()
                if not token:
                    i += 1
                    continue
                flag, sep, value = token.partition("=")
                if sep and flag in dir_flags.union(path_flags):
                    _append_raw(value)
                    i += 1
                    continue
                if token in dir_flags.union(path_flags):
                    if i + 1 < len(args):
                        _append_raw(args[i + 1])
                    i += 2
                    continue
                i += 1

        for key in (
            "out_dir",
            "output_dir",
            "artifact_dir",
            "artifacts_dir",
            "output",
            "out",
            "out_file",
            "result_file",
            "summary_path",
            "meta_path",
        ):
            if key in params:
                _append_raw(params.get(key))

        root = workspace.resolve()
        expanded: list[str] = []
        for raw in raw_candidates:
            probe = Path(raw)
            candidate = probe.resolve() if probe.is_absolute() else (root / probe).resolve()
            if not self._is_within_root(candidate, root):
                continue
            if candidate.is_file():
                expanded.append(str(candidate.relative_to(root)))
                continue
            if candidate.is_dir():
                for child in sorted(candidate.rglob("*")):
                    if child.is_file():
                        expanded.append(str(child.relative_to(root)))

        seen: set[str] = set()
        uniq: list[str] = []
        for item in expanded:
            if item in seen:
                continue
            seen.add(item)
            uniq.append(item)
        return uniq

    def _evaluate_auto_complete_validations(
        self,
        task: str,
        workspace: Path,
        produced_files: set[str],
    ) -> dict[str, Any]:
        inferred_paths = set(self._infer_output_files_from_task(task))
        if not inferred_paths:
            return {"ok": False, "failures": ["no inferred outputs"], "checks": []}
        missing_in_run = sorted(path for path in inferred_paths if path not in produced_files)
        if missing_in_run:
            return {
                "ok": False,
                "failures": [f"inferred output not produced in this run: {p}" for p in missing_in_run],
                "checks": [],
            }
        return self._evaluate_objective_validations(
            task=task,
            plan={"validations": []},
            workspace=workspace,
            produced_files=produced_files,
        )

    def _build_iteration_signature(
        self,
        actions: list[dict[str, Any]],
        action_results: list[dict[str, Any]],
        output: str,
    ) -> str:
        compact_results = []
        for item in action_results:
            compact_results.append(
                {
                    "name": str(item.get("name", "")),
                    "ok": bool(item.get("ok", False)),
                    "error": str(item.get("error", "")),
                    "output": str(item.get("output", ""))[:500],
                }
            )

        payload = {
            "actions": actions,
            "results": compact_results,
            "output": (output or "")[:800],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _prepare_action(
        self,
        action: dict[str, Any],
        task: str,
        workspace: Path,
        skills_root: Path,
    ) -> dict[str, Any]:
        prepared = copy.deepcopy(action)
        name = str(prepared.get("name", ""))
        params = prepared.get("params")
        if not isinstance(params, dict):
            return prepared

        if name in {"run_safe_command", "run_shell_command"}:
            command = str(params.get("command", "")).strip()
            if not command:
                return prepared

            command = self._normalize_shell_python_alias(command)
            params["command"] = command

            try:
                parts = shlex.split(command)
            except Exception:
                return prepared
            if not parts or parts[0] != "rm":
                return prepared

            if self._has_rm_targets(parts):
                return prepared

            targets = self._extract_file_targets_from_task(task, workspace)
            if not targets:
                return prepared

            params["paths"] = targets
            params["command"] = f"{command} " + " ".join(shlex.quote(t) for t in targets)
            return prepared

        if name == "run_python_code":
            python_bin = str(params.get("python_bin", "")).strip()
            if python_bin == "python3":
                params["python_bin"] = "python"
            rel_script_path = str(params.get("path", "")).strip()
            skill_script = self._resolve_skill_script_path(rel_script_path, skills_root)
            if skill_script is not None and skill_script.suffix == ".py":
                rel = skill_script.relative_to(skills_root.resolve())
                params["path"] = str(Path(".softnix_skill_exec") / rel)
                params["code"] = skill_script.read_text(encoding="utf-8")
                params["skill_source_path"] = str(skill_script)
            else:
                code_text = str(params.get("code", ""))
                if code_text.strip():
                    params["code"] = self._rewrite_embedded_skill_script_refs(code_text, skills_root)
            return prepared

        return prepared

    def _normalize_shell_python_alias(self, command: str) -> str:
        try:
            parts = shlex.split(command)
        except Exception:
            return command
        if not parts:
            return command
        if parts[0] != "python3":
            return command
        parts[0] = "python"
        return shlex.join(parts)

    def _has_rm_targets(self, parts: list[str]) -> bool:
        treat_as_target = False
        for token in parts[1:]:
            if token == "--":
                treat_as_target = True
                continue
            if not treat_as_target and token.startswith("-"):
                continue
            return True
        return False

    def _extract_file_targets_from_task(self, task: str, workspace: Path) -> list[str]:
        candidates = re.findall(r"([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)", task)
        safe_targets: list[str] = []
        root = workspace.resolve()
        for raw in candidates:
            target = (root / raw).resolve()
            if not self._is_within_root(target, root):
                continue
            if target.exists() and target.is_file():
                safe_targets.append(str(target.relative_to(root)))
        # preserve order, deduplicate
        seen = set()
        uniq = []
        for t in safe_targets:
            if t in seen:
                continue
            seen.add(t)
            uniq.append(t)
        return uniq

    def _extract_existing_file_targets_from_text(self, text: str, workspace: Path) -> list[str]:
        if not text.strip():
            return []
        candidates = re.findall(r"([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)", text)
        safe_targets: list[str] = []
        root = workspace.resolve()
        for raw in candidates:
            target = (root / raw).resolve()
            if not self._is_within_root(target, root):
                continue
            if target.exists() and target.is_file():
                safe_targets.append(str(target.relative_to(root)))
        seen = set()
        uniq = []
        for t in safe_targets:
            if t in seen:
                continue
            seen.add(t)
            uniq.append(t)
        return uniq

    def _is_action_allowed_by_policy(self, action_name: str, memory: CoreMemoryService) -> bool:
        allowed = memory.get_policy_allow_tools()
        if allowed is None:
            return True
        normalized = self._normalize_action_name(action_name)
        return normalized in allowed

    def _normalize_action_name(self, name: str) -> str:
        raw = (name or "").strip().lower()
        aliases = {
            "write_file": "write_workspace_file",
            "run_shell_command": "run_safe_command",
        }
        return aliases.get(raw, raw)

    def _resolve_skill_script_path(self, value: str, skills_root: Path) -> Path | None:
        text = (value or "").strip()
        if not text:
            return None
        root = skills_root.resolve()
        raw = Path(text)
        candidates: list[Path] = []
        if raw.is_absolute():
            candidates.append(raw.resolve())
        else:
            candidates.append((root / raw).resolve())
            parts = raw.parts
            if parts and parts[0] == root.name:
                candidates.append((root / Path(*parts[1:])).resolve())
        for candidate in candidates:
            if not self._is_within_root(candidate, root):
                continue
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    def _rewrite_embedded_skill_script_refs(self, code: str, skills_root: Path) -> str:
        pattern = re.compile(r"(?P<q>['\"])(?P<path>[^'\"]+?\.py)(?P=q)")
        replacements: dict[str, str] = {}
        embedded_files: dict[str, str] = {}

        for match in pattern.finditer(code):
            raw_path = match.group("path")
            if raw_path in replacements:
                continue
            resolved = self._resolve_skill_script_path(raw_path, skills_root)
            if resolved is None or resolved.suffix != ".py":
                continue
            rel = resolved.relative_to(skills_root.resolve())
            exec_rel = str(Path(".softnix_skill_exec") / rel).replace("\\", "/")
            replacements[raw_path] = exec_rel
            embedded_files[exec_rel] = resolved.read_text(encoding="utf-8")

        if not replacements:
            return code

        rewritten = code
        for src, dst in replacements.items():
            rewritten = rewritten.replace(f"'{src}'", repr(dst))
            rewritten = rewritten.replace(f'"{src}"', repr(dst))

        prelude_lines = [
            "from pathlib import Path as __softnix_Path",
            "__softnix_skill_files = {",
        ]
        for path, content in embedded_files.items():
            prelude_lines.append(f"    {repr(path)}: {repr(content)},")
        prelude_lines.extend(
            [
                "}",
                "for __p, __c in __softnix_skill_files.items():",
                "    __t = __softnix_Path(__p)",
                "    __t.parent.mkdir(parents=True, exist_ok=True)",
                "    __t.write_text(__c, encoding='utf-8')",
                "",
            ]
        )
        return "\n".join(prelude_lines) + rewritten

    def _resolve_container_runtime_image(self, task: str, selected_skills: list[Any]) -> tuple[str, str]:
        default_image = self.settings.exec_container_image
        if self.settings.exec_runtime != "container":
            return default_image, "host"

        requested = (self.settings.exec_container_image_profile or "auto").strip().lower()
        profile = requested
        if profile not in {"auto", "base", "web", "data", "scraping", "ml", "qa"}:
            profile = "auto"

        if profile == "auto":
            text = (task or "").lower()
            skill_names = [str(getattr(s, "name", "")).lower() for s in selected_skills]
            if (
                any(tok in text for tok in {"selenium", "playwright", "beautifulsoup", "scrape", "crawler"})
                or any(("scrap" in name or "crawl" in name) for name in skill_names)
            ):
                profile = "scraping"
            elif (
                any(tok in text for tok in {"pytorch", "tensorflow", "scikit", "sklearn", "xgboost", "train model"})
                or any(("ml" in name or "model" in name) for name in skill_names)
            ):
                profile = "ml"
            elif (
                any(tok in text for tok in {"pytest", "unit test", "integration test", "coverage"})
                or any(("test" in name or "qa" in name) for name in skill_names)
            ):
                profile = "qa"
            elif (
                any(tok in text for tok in {"csv", "pandas", "numpy", "dataset", "dataframe"})
                or any("data" in name for name in skill_names)
            ):
                profile = "data"
            elif (
                "http://" in text
                or "https://" in text
                or "url" in text
                or any("web" in name for name in skill_names)
            ):
                profile = "web"
            else:
                profile = "base"

        images = {
            "base": self.settings.exec_container_image_base or default_image,
            "web": self.settings.exec_container_image_web or default_image,
            "data": self.settings.exec_container_image_data or default_image,
            "scraping": self.settings.exec_container_image_scraping or default_image,
            "ml": self.settings.exec_container_image_ml or default_image,
            "qa": self.settings.exec_container_image_qa or default_image,
        }
        return images.get(profile, default_image), profile

    def _evaluate_objective_validations(
        self,
        task: str,
        plan: dict[str, Any],
        workspace: Path,
        produced_files: set[str] | None = None,
    ) -> dict[str, Any]:
        checks = self._collect_validation_checks(task=task, plan=plan, produced_files=produced_files)
        if not checks:
            return {"ok": True, "failures": [], "checks": []}

        failures: list[str] = []
        if produced_files is not None and self._task_requires_web_intel_contract(task):
            expected_web_intel_paths = {
                str(item.get("path", "")).strip()
                for item in checks
                if str(item.get("path", "")).strip().startswith("web_intel/")
            }
            missing_in_run = sorted(path for path in expected_web_intel_paths if path not in produced_files)
            for path in missing_in_run:
                failures.append(f"required web_intel output not produced in this run: {path}")

        root = workspace.resolve()
        for check in checks:
            ctype = str(check.get("type", "")).strip().lower()
            path_text = str(check.get("path", "")).strip()
            if not path_text:
                failures.append("validation missing path")
                continue
            target = (root / path_text).resolve()
            if not self._is_within_root(target, root):
                failures.append(f"path escapes workspace: {path_text}")
                continue
            if ctype == "file_exists":
                if not target.exists() or not target.is_file():
                    failures.append(f"missing output file: {path_text}")
                continue
            if ctype == "text_in_file":
                if not target.exists() or not target.is_file():
                    failures.append(f"missing output file: {path_text}")
                    continue
                content = target.read_text(encoding="utf-8")
                needle = str(check.get("contains", ""))
                if needle and needle not in content:
                    failures.append(f"text not found in {path_text}: {needle}")
                continue
            if ctype == "python_import":
                if not target.exists() or not target.is_file():
                    failures.append(f"missing output file: {path_text}")
                    continue
                module = str(check.get("module", "")).strip()
                if not module:
                    failures.append(f"validation missing module for {path_text}")
                    continue
                content = target.read_text(encoding="utf-8")
                if not self._python_file_imports_module(content, module):
                    failures.append(f"module not imported in {path_text}: {module}")
                continue
            failures.append(f"unknown validation type: {ctype}")

        return {"ok": len(failures) == 0, "failures": failures, "checks": checks}

    def _collect_validation_checks(
        self,
        task: str,
        plan: dict[str, Any],
        produced_files: set[str] | None = None,
    ) -> list[dict[str, str]]:
        checks: list[dict[str, str]] = []
        raw_validations = plan.get("validations")
        if isinstance(raw_validations, list):
            for item in raw_validations:
                if not isinstance(item, dict):
                    continue
                ctype = str(item.get("type", "")).strip().lower()
                path = str(item.get("path", "")).strip()
                contains = str(item.get("contains", ""))
                module = str(item.get("module", "")).strip()
                if ctype in {"file_exists", "text_in_file", "python_import"} and path:
                    payload = {"type": ctype, "path": path}
                    if ctype == "text_in_file":
                        payload["contains"] = contains
                    if ctype == "python_import":
                        payload["module"] = module
                    checks.append(payload)

        inferred_files = self._infer_output_files_from_task(task)
        for path in inferred_files:
            checks.append({"type": "file_exists", "path": path})

        lowered_task = (task or "").lower()
        if "pytest" in lowered_task:
            for path in inferred_files:
                if path.endswith("result.txt"):
                    checks.append({"type": "text_in_file", "path": path, "contains": "pytest"})

        required_modules = self._infer_required_python_modules_from_task(task)
        if required_modules:
            python_files = [path for path in inferred_files if path.endswith(".py")]
            if produced_files:
                python_files = [path for path in python_files if path in produced_files]
            for path in python_files:
                for module in required_modules:
                    checks.append({"type": "python_import", "path": path, "module": module})

        # For fetch-first web-intel tasks, require script-generated markers
        # so "manual summary/meta writing" does not silently pass objective checks.
        is_web_intel_task = self._task_requires_web_intel_contract(task)
        if is_web_intel_task:
            lowered_task = (task or "").lower()
            has_meta = ("web_intel/meta.json" in inferred_files) or ("web_intel/meta.json" in lowered_task)
            has_summary = ("web_intel/summary.md" in inferred_files) or ("web_intel/summary.md" in lowered_task)
            if has_meta:
                checks.append({"type": "text_in_file", "path": "web_intel/meta.json", "contains": '"generated_by": "web_intel_fetch.py"'})
                checks.append({"type": "text_in_file", "path": "web_intel/meta.json", "contains": '"timestamp": "'})
            if has_summary:
                checks.append({"type": "text_in_file", "path": "web_intel/summary.md", "contains": "# Web Intel Summary"})

        # preserve order with dedup
        seen = set()
        uniq: list[dict[str, str]] = []
        for item in checks:
            sig = (
                item.get("type", ""),
                item.get("path", ""),
                item.get("contains", ""),
                item.get("module", ""),
            )
            if sig in seen:
                continue
            seen.add(sig)
            uniq.append(item)
        return uniq

    def _infer_required_python_modules_from_task(self, task: str) -> list[str]:
        lowered = (task or "").lower()
        modules: list[str] = []
        if "numpy" in lowered:
            modules.append("numpy")
        if "pandas" in lowered:
            modules.append("pandas")
        if "scipy" in lowered:
            modules.append("scipy")
        return modules

    def _python_file_imports_module(self, source: str, module: str) -> bool:
        target = (module or "").strip().lower()
        if not target:
            return False
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0].lower() == target:
                        return True
            if isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0].lower()
                if mod == target:
                    return True
        return False

    def _infer_output_files_from_task(self, task: str) -> list[str]:
        text = (task or "").strip()
        if not text:
            return []
        intent_keywords = (
            "write",
            "create",
            "generate",
            "save",
            "output",
            "บันทึก",
            "สร้าง",
            "เขียนผลลัพธ์",
            "เขียนลง",
        )
        lowered = text.lower()
        if not any(k in lowered for k in intent_keywords):
            return []

        candidates = re.findall(r"([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)", text)
        files: list[str] = []
        for token in candidates:
            if "://" in token or token.startswith("www."):
                continue
            if token.count(".") > 1 and "/" not in token:
                # likely domain name, not workspace file
                continue
            if token.startswith("./"):
                token = token[2:]
            if token.startswith("/"):
                continue
            files.append(token)

        seen = set()
        uniq: list[str] = []
        for f in files:
            if f in seen:
                continue
            seen.add(f)
            uniq.append(f)
        return uniq

    def _task_requires_web_intel_contract(self, task: str) -> bool:
        lowered = (task or "").lower()
        if not lowered:
            return False
        triggers = ("fetch-first", "web_fetch", "web-intel", "web_intel")
        if any(token in lowered for token in triggers):
            return True
        # If task explicitly asks to read these files, enforce contract as well.
        return ("web_intel/meta.json" in lowered) or ("web_intel/summary.md" in lowered)

    def _is_within_root(self, path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False
