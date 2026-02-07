from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from softnix_agentic_agent.agent.executor import SafeActionExecutor
from softnix_agentic_agent.agent.planner import Planner
from softnix_agentic_agent.config import Settings
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
        executor = SafeActionExecutor(workspace=Path(state.workspace), safe_commands=self.settings.safe_commands)

        try:
            while state.iteration < state.max_iters:
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
                plan, token_usage, prompt_text = self.planner.build_plan(
                    task=state.task,
                    iteration=current_iteration,
                    max_iters=state.max_iters,
                    previous_output=state.last_output,
                    skills_context=skills_context,
                )

                actions = plan.get("actions", []) if isinstance(plan.get("actions", []), list) else []
                action_results = []
                for action in actions:
                    result = executor.execute(action)
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
            if action.get("name") != "write_workspace_file":
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
