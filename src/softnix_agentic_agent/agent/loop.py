from __future__ import annotations

import copy
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
            max_output_chars=self.settings.max_action_output_chars,
        )

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
                compact_stats = memory.compact(["profile", "session"])
                if compact_stats["removed_expired"] or compact_stats["removed_duplicates"]:
                    self.store.log_event(
                        state.run_id,
                        "memory compact "
                        f"expired={compact_stats['removed_expired']} "
                        f"duplicates={compact_stats['removed_duplicates']}",
                    )

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
                skills_context = skill_loader.render_compact_context()
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
                    prepared_action = self._prepare_action(action, state.task, Path(state.workspace))
                    result = executor.execute(prepared_action)
                    action_results.append(
                        {
                            "name": result.name,
                            "ok": result.ok,
                            "output": result.output,
                            "error": result.error,
                        }
                    )
                self._snapshot_artifacts(state, actions, action_results)

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

                self.store.write_state(state)

            state.status = RunStatus.COMPLETED
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

    def _snapshot_artifacts(self, state: RunState, actions: list[dict[str, Any]], action_results: list[dict[str, Any]]) -> None:
        workspace = Path(state.workspace)
        for action, result in zip(actions, action_results):
            action_name = str(action.get("name", ""))
            result_name = str(result.get("name", ""))
            if action_name not in {"write_workspace_file", "write_file"} and result_name != "write_workspace_file":
                continue
            if not bool(result.get("ok")):
                continue
            params = action.get("params", {}) if isinstance(action.get("params"), dict) else {}
            raw_path = params.get("path") or params.get("file_path")
            if raw_path is None:
                continue
            try:
                rel = self.store.snapshot_workspace_file(state.run_id, workspace, str(raw_path))
                self.store.log_event(state.run_id, f"artifact saved: {rel}")
            except Exception as exc:
                self.store.log_event(state.run_id, f"artifact snapshot failed: {exc}")

    def _prepare_action(self, action: dict[str, Any], task: str, workspace: Path) -> dict[str, Any]:
        prepared = copy.deepcopy(action)
        name = str(prepared.get("name", ""))
        if name not in {"run_safe_command", "run_shell_command"}:
            return prepared

        params = prepared.get("params")
        if not isinstance(params, dict):
            return prepared

        command = str(params.get("command", "")).strip()
        if not command:
            return prepared

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
            if not str(target).startswith(str(root)):
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
