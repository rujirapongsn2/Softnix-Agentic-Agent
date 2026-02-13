from __future__ import annotations

import copy
import ast
import hashlib
import json
import re
import shlex
import time
import uuid
from pathlib import Path
from typing import Any

from softnix_agentic_agent.agent.executor import SafeActionExecutor
from softnix_agentic_agent.agent.planner import Planner
from softnix_agentic_agent.agent.task_contract import PathDiscoveryPolicy, TaskContractParser
from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.memory.markdown_store import MarkdownMemoryStore
from softnix_agentic_agent.memory.service import CoreMemoryService
from softnix_agentic_agent.skills.loader import SkillLoader
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.types import IterationRecord, RunState, RunStatus, StopReason, utc_now_iso


class AgentLoopRunner:
    _COMMON_OUTPUT_EXTENSIONS = {
        "txt",
        "md",
        "json",
        "csv",
        "html",
        "htm",
        "xml",
        "yaml",
        "yml",
        "log",
        "py",
        "js",
        "ts",
        "jsx",
        "tsx",
        "css",
        "scss",
        "sql",
        "sh",
        "bash",
        "zsh",
        "bat",
        "ps1",
        "ini",
        "cfg",
        "conf",
        "toml",
        "lock",
        "env",
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "bmp",
        "webp",
        "tif",
        "tiff",
        "zip",
        "gz",
        "tar",
        "parquet",
        "pkl",
        "pickle",
    }
    _SECRET_TOKEN_PATTERNS = (
        ("RESEND_API_KEY", re.compile(r"\bre_[A-Za-z0-9_-]{16,}\b")),
        ("TAVILY_API_KEY", re.compile(r"\btvly-[A-Za-z0-9_-]{16,}\b")),
        ("OPENAI_API_KEY", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    )

    def __init__(self, settings: Settings, planner: Planner, store: FilesystemStore) -> None:
        self.settings = settings
        self.planner = planner
        self.store = store
        self._task_contract_parser = TaskContractParser()
        self._path_discovery_policy = PathDiscoveryPolicy()

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
        sanitized_task, secret_names = self._sanitize_task_and_materialize_secrets(task=task, workspace=workspace)
        run_id = uuid.uuid4().hex[:12]
        state = RunState(
            run_id=run_id,
            task=sanitized_task,
            provider=provider_name,
            model=model,
            workspace=str(workspace.resolve()),
            skills_dir=str(skills_dir.resolve()),
            max_iters=max_iters,
        )
        self.store.init_run(state)
        if secret_names:
            self.store.log_event(
                state.run_id,
                f"security policy applied: secrets sanitized count={len(secret_names)} names={','.join(secret_names)}",
            )
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
        task_contract = self._task_contract_parser.parse(
            task=state.task,
            enforce_web_intel_contract=self._task_requires_web_intel_contract(state.task),
        )
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
            runs_dir=self.settings.runs_dir,
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
            exec_container_run_venv_enabled=self.settings.exec_container_run_venv_enabled,
            exec_container_auto_install_enabled=self.settings.exec_container_auto_install_enabled,
            exec_container_auto_install_max_modules=self.settings.exec_container_auto_install_max_modules,
            run_id=state.run_id,
            max_output_chars=self.settings.max_action_output_chars,
            web_fetch_tls_verify=self.settings.web_fetch_tls_verify,
        )
        previous_iteration_signature = ""
        repeated_iteration_count = 0
        produced_files_in_run: set[str] = set()
        required_outputs = self._merge_required_outputs(
            task_contract.required_outputs,
            self._infer_output_files_from_selected_skills(selected_for_runtime),
        )
        required_absent = list(task_contract.required_absent)
        previous_iteration_had_failed_action = False
        previous_actions: list[dict[str, Any]] = []
        previous_action_results: list[dict[str, Any]] = []
        run_started_at = time.monotonic()
        planner_parse_error_streak = 0
        capability_failure_streak = 0
        previous_capability_failure_fingerprint = ""
        best_objective_progress_score = -1
        objective_stagnation_streak = 0
        skills_seen_in_run: set[str] = set()
        successful_action_history: list[str] = []
        latest_failure_fingerprint = ""
        active_strategy_keys: set[str] = set()

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
                max_wall_sec = max(0, int(self.settings.run_max_wall_time_sec))
                if max_wall_sec > 0:
                    elapsed = int(max(0.0, time.monotonic() - run_started_at))
                    if elapsed >= max_wall_sec:
                        state.status = RunStatus.FAILED
                        state.stop_reason = StopReason.NO_PROGRESS
                        state.last_output = (
                            "stopped by wall time limit "
                            f"(elapsed={elapsed}s, limit={max_wall_sec}s); "
                            "adjust SOFTNIX_RUN_MAX_WALL_TIME_SEC if needed"
                        )
                        state.updated_at = utc_now_iso()
                        self.store.write_state(state)
                        self.store.log_event(
                            state.run_id,
                            f"stopped: wall_time_limit reached elapsed={elapsed}s limit={max_wall_sec}s",
                        )
                        return state

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
                iteration_started_at = time.perf_counter()
                selected_skills = skill_loader.select_skills(task=state.task)
                if selected_skills:
                    selected_names = ",".join(skill.name for skill in selected_skills)
                else:
                    selected_names = "(none)"
                skills_seen_in_run.update(skill.name for skill in selected_skills)
                self.store.log_event(state.run_id, f"skills selected iteration={current_iteration} names={selected_names}")
                skills_context = skill_loader.render_compact_context(task=state.task)
                memory_context = memory.build_prompt_context(max_items=self.settings.memory_prompt_max_items)
                experience_rows: list[dict[str, Any]] = []
                if self.settings.experience_enabled:
                    experience_rows = self.store.retrieve_success_experiences(
                        task=state.task,
                        selected_skills=[skill.name for skill in selected_skills],
                        top_k=max(1, int(self.settings.experience_retrieval_top_k)),
                        max_scan=max(20, int(self.settings.experience_retrieval_max_scan)),
                    )
                    if experience_rows:
                        self.store.log_event(
                            state.run_id,
                            f"experience retrieved iteration={current_iteration} count={len(experience_rows)}",
                        )
                experience_context = self._build_experience_context(experience_rows)
                failure_rows: list[dict[str, Any]] = []
                if self.settings.experience_enabled:
                    failure_rows = self.store.retrieve_failure_experiences(
                        task=state.task,
                        selected_skills=[skill.name for skill in selected_skills],
                        top_k=min(2, max(1, int(self.settings.experience_retrieval_top_k))),
                        max_scan=max(20, int(self.settings.experience_retrieval_max_scan)),
                    )
                    if failure_rows:
                        self.store.log_event(
                            state.run_id,
                            f"failure experience retrieved iteration={current_iteration} count={len(failure_rows)}",
                        )
                active_strategy_keys.update(
                    str(row.get("strategy_key", "")).strip()
                    for row in failure_rows
                    if str(row.get("strategy_key", "")).strip()
                )
                runtime_guidance = self._build_runtime_guidance(
                    task=state.task,
                    workspace=Path(state.workspace),
                    required_outputs=required_outputs,
                    required_absent=required_absent,
                    produced_files=produced_files_in_run,
                    previous_actions=previous_actions,
                    previous_action_results=previous_action_results,
                    objective_stagnation_streak=objective_stagnation_streak,
                    hinted_directories=task_contract.hinted_directories,
                )
                failure_guidance = self._build_failure_strategy_guidance(failure_rows)
                if failure_guidance != "- none":
                    runtime_guidance = (
                        f"{runtime_guidance}\n{failure_guidance}" if runtime_guidance and runtime_guidance != "- none" else failure_guidance
                    )
                plan_started_at = time.perf_counter()
                plan, token_usage, prompt_text, planner_attempts = self._build_plan_with_retry(
                    state=state,
                    task=state.task,
                    iteration=current_iteration,
                    max_iters=state.max_iters,
                    previous_output=state.last_output,
                    skills_context=skills_context,
                    experience_context=experience_context,
                    memory_context=memory_context,
                    runtime_guidance=runtime_guidance,
                )
                if self._should_force_execution_replan(
                    task=state.task,
                    iteration=current_iteration,
                    required_outputs=required_outputs,
                    actions=plan.get("actions", []) if isinstance(plan, dict) else [],
                ):
                    self.store.log_event(
                        state.run_id,
                        f"plan gate triggered iteration={current_iteration} reason=preparatory_only",
                    )
                    forced_guidance = (
                        f"{runtime_guidance}\n"
                        "Execution gate: next plan MUST include at least one non-preparatory action "
                        "that executes the objective (run target script/command or produce required outputs). "
                        "Do not return read_file/list_dir/date-only actions."
                    )
                    replan, replan_usage, replan_prompt, replan_attempts = self._build_plan_with_retry(
                        state=state,
                        task=state.task,
                        iteration=current_iteration,
                        max_iters=state.max_iters,
                        previous_output=state.last_output,
                        skills_context=skills_context,
                        experience_context=experience_context,
                        memory_context=memory_context,
                        runtime_guidance=forced_guidance,
                    )
                    plan = replan
                    prompt_text = replan_prompt
                    token_usage = self._merge_token_usage(token_usage, replan_usage)
                    planner_attempts += replan_attempts
                if self._should_force_repair_replan(
                    previous_action_results=previous_action_results,
                    actions=plan.get("actions", []) if isinstance(plan, dict) else [],
                ):
                    self.store.log_event(
                        state.run_id,
                        f"plan gate triggered iteration={current_iteration} reason=repair_loop_required",
                    )
                    repair_guidance = (
                        f"{runtime_guidance}\n"
                        "Repair-loop gate: previous iteration failed; next plan must include a concrete corrective execution "
                        "action (not read/list only), then re-validate objective."
                    )
                    replan, replan_usage, replan_prompt, replan_attempts = self._build_plan_with_retry(
                        state=state,
                        task=state.task,
                        iteration=current_iteration,
                        max_iters=state.max_iters,
                        previous_output=state.last_output,
                        skills_context=skills_context,
                        experience_context=experience_context,
                        memory_context=memory_context,
                        runtime_guidance=repair_guidance,
                    )
                    plan = replan
                    prompt_text = replan_prompt
                    token_usage = self._merge_token_usage(token_usage, replan_usage)
                    planner_attempts += replan_attempts
                if self._should_replan_for_repeated_failed_sequence(
                    actions=plan.get("actions", []) if isinstance(plan, dict) else [],
                    failure_rows=failure_rows,
                ):
                    self.store.log_event(
                        state.run_id,
                        f"plan gate triggered iteration={current_iteration} reason=repeated_failed_sequence",
                    )
                    failed_patterns = self._describe_failure_action_patterns(failure_rows)
                    penalty_guidance = (
                        f"{runtime_guidance}\n"
                        "Strategy penalty: avoid action sequence patterns that repeatedly failed in similar tasks.\n"
                        f"{failed_patterns}\n"
                        "Choose a different sequence that advances objective contract."
                    )
                    replan, replan_usage, replan_prompt, replan_attempts = self._build_plan_with_retry(
                        state=state,
                        task=state.task,
                        iteration=current_iteration,
                        max_iters=state.max_iters,
                        previous_output=state.last_output,
                        skills_context=skills_context,
                        experience_context=experience_context,
                        memory_context=memory_context,
                        runtime_guidance=penalty_guidance,
                    )
                    plan = replan
                    prompt_text = replan_prompt
                    token_usage = self._merge_token_usage(token_usage, replan_usage)
                    planner_attempts += replan_attempts
                planner_ms = int((time.perf_counter() - plan_started_at) * 1000)
                if self._is_planner_parse_error(plan):
                    planner_parse_error_streak += 1
                else:
                    planner_parse_error_streak = 0

                parse_guard_threshold = max(2, int(self.settings.planner_parse_error_streak_threshold))
                if planner_parse_error_streak >= parse_guard_threshold:
                    state.status = RunStatus.FAILED
                    state.stop_reason = StopReason.NO_PROGRESS
                    state.last_output = (
                        "stopped: repeated planner_parse_error "
                        f"(streak={planner_parse_error_streak}); "
                        "model output could not be parsed as valid JSON plan"
                    )
                    state.updated_at = utc_now_iso()
                    self.store.write_state(state)
                    self.store.log_event(
                        state.run_id,
                        f"stopped: planner_parse_error streak={planner_parse_error_streak}",
                    )
                    return state

                actions = plan.get("actions", []) if isinstance(plan.get("actions", []), list) else []
                action_results = []
                required_output_baseline = self._collect_required_output_baseline(
                    workspace=Path(state.workspace),
                    required_outputs=required_outputs,
                )
                actions_started_at = time.perf_counter()
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
                        confidence, reason = self._estimate_action_confidence(prepared_action, result_payload)
                        result_payload["confidence"] = confidence
                        result_payload["confidence_reason"] = reason
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
                    result_payload = {
                        "name": result.name,
                        "ok": result.ok,
                        "output": result.output,
                        "error": result.error,
                    }
                    confidence, reason = self._estimate_action_confidence(prepared_action, result_payload)
                    result_payload["confidence"] = confidence
                    result_payload["confidence_reason"] = reason
                    action_results.append(
                        result_payload
                    )
                actions_ms = int((time.perf_counter() - actions_started_at) * 1000)
                successful_action_history.extend(
                    str(action.get("name", ""))
                    for action, result in zip(actions, action_results)
                    if bool(result.get("ok", False))
                )
                new_artifacts = self._snapshot_artifacts(state, actions, action_results)
                new_artifacts.update(
                    self._snapshot_updated_required_outputs(
                        state=state,
                        workspace=Path(state.workspace),
                        required_outputs=required_outputs,
                        baseline=required_output_baseline,
                    )
                )
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
                    elif self._has_low_confidence_results(action_results):
                        done = False
                        output = (
                            (output + "\n\n" if output else "")
                            + "[validation] failed; continue iterations\n"
                            + "- low confidence action results; require stronger evidence/validation"
                        )
                        self.store.log_event(state.run_id, "objective validation blocked by low confidence results")

                if done:
                    validation_report = self._evaluate_objective_validations(
                        task=state.task,
                        plan=plan,
                        workspace=Path(state.workspace),
                        produced_files=produced_files_in_run,
                        required_absent=required_absent,
                        required_python_modules=task_contract.required_python_modules,
                        expected_text_markers=task_contract.expected_text_markers,
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

                iteration_ms = int((time.perf_counter() - iteration_started_at) * 1000)
                if isinstance(plan, dict):
                    plan["timing"] = {
                        "planner_ms": planner_ms,
                        "actions_ms": actions_ms,
                        "iteration_ms": iteration_ms,
                        "planner_attempts": planner_attempts,
                    }
                self.store.log_event(
                    state.run_id,
                    "metrics iteration="
                    f"{current_iteration} planner_ms={planner_ms} actions_ms={actions_ms} "
                    f"total_ms={iteration_ms} planner_attempts={planner_attempts} actions_count={len(actions)}",
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
                previous_actions = actions
                previous_action_results = action_results

                if done:
                    state.status = RunStatus.COMPLETED
                    state.stop_reason = StopReason.COMPLETED
                    self._record_strategy_outcomes(active_strategy_keys, success=True, run_id=state.run_id)
                    self._record_success_experience(
                        state=state,
                        selected_skills=sorted(skills_seen_in_run),
                        action_history=successful_action_history,
                        produced_files=produced_files_in_run,
                    )
                    self.store.write_state(state)
                    return state

                if not has_failed_action:
                    auto_complete_report = self._evaluate_auto_complete_validations(
                        task=state.task,
                        workspace=Path(state.workspace),
                        produced_files=produced_files_in_run,
                        required_absent=required_absent,
                        required_python_modules=task_contract.required_python_modules,
                        expected_text_markers=task_contract.expected_text_markers,
                    )
                    if auto_complete_report.get("checks") and auto_complete_report.get("ok"):
                        state.status = RunStatus.COMPLETED
                        state.stop_reason = StopReason.COMPLETED
                        state.updated_at = utc_now_iso()
                        self._record_strategy_outcomes(active_strategy_keys, success=True, run_id=state.run_id)
                        self._record_success_experience(
                            state=state,
                            selected_skills=sorted(skills_seen_in_run),
                            action_history=successful_action_history,
                            produced_files=produced_files_in_run,
                        )
                        self.store.write_state(state)
                        self.store.log_event(
                            state.run_id,
                            "objective auto-completed from inferred validations",
                        )
                        return state

                self.store.write_state(state)
                previous_iteration_had_failed_action = has_failed_action
                objective_progress = self._objective_progress_snapshot(
                    workspace=Path(state.workspace),
                    required_outputs=required_outputs,
                    produced_files=produced_files_in_run,
                )
                progress_score = int(objective_progress.get("score", 0))
                if progress_score > best_objective_progress_score:
                    best_objective_progress_score = progress_score
                    objective_stagnation_streak = 0
                else:
                    objective_stagnation_streak += 1
                    threshold = max(2, int(self.settings.objective_stagnation_replan_threshold))
                    if objective_stagnation_streak >= threshold:
                        self.store.log_event(
                            state.run_id,
                            "objective stagnation detected "
                            f"streak={objective_stagnation_streak} "
                            f"required={objective_progress.get('required_total', 0)} "
                            f"existing={objective_progress.get('existing_count', 0)} "
                            f"non_empty={objective_progress.get('non_empty_count', 0)} "
                            f"produced_required={objective_progress.get('produced_required_count', 0)} "
                            f"produced={objective_progress.get('produced_count', 0)}",
                        )

                failure_fingerprint = self._build_capability_failure_fingerprint(action_results)
                latest_failure_fingerprint = failure_fingerprint
                if failure_fingerprint:
                    if failure_fingerprint == previous_capability_failure_fingerprint:
                        capability_failure_streak += 1
                    else:
                        capability_failure_streak = 1
                        previous_capability_failure_fingerprint = failure_fingerprint
                else:
                    capability_failure_streak = 0
                    previous_capability_failure_fingerprint = ""

                capability_guard_threshold = max(2, int(self.settings.capability_failure_streak_threshold))
                if capability_failure_streak >= capability_guard_threshold:
                    state.status = RunStatus.FAILED
                    state.stop_reason = StopReason.NO_PROGRESS
                    state.last_output = (
                        "stopped: repeated capability block "
                        f"(streak={capability_failure_streak}, fingerprint={failure_fingerprint})"
                    )
                    state.updated_at = utc_now_iso()
                    self.store.write_state(state)
                    self.store.log_event(
                        state.run_id,
                        "stopped: capability_block repeated="
                        f"{capability_failure_streak} fingerprint={failure_fingerprint}",
                    )
                    return state

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
            if self._should_auto_complete_answer_only_on_max_iters(
                task=state.task,
                required_outputs=required_outputs,
                last_output=state.last_output,
                last_action_results=previous_action_results,
            ):
                state.status = RunStatus.COMPLETED
                state.stop_reason = StopReason.COMPLETED
                state.updated_at = utc_now_iso()
                self._record_success_experience(
                    state=state,
                    selected_skills=sorted(skills_seen_in_run),
                    action_history=successful_action_history,
                    produced_files=produced_files_in_run,
                )
                self.store.write_state(state)
                self.store.log_event(
                    state.run_id,
                    "objective auto-completed at max_iters for answer-only task",
                )
                return state
            if required_outputs:
                progress = self._objective_progress_snapshot(
                    workspace=Path(state.workspace),
                    required_outputs=required_outputs,
                    produced_files=produced_files_in_run,
                )
                missing = ", ".join(progress.get("missing_paths", [])) or "-"
                diag = (
                    "[objective] incomplete at max_iters\n"
                    f"- required_outputs: {progress.get('required_total', 0)}\n"
                    f"- existing: {progress.get('existing_count', 0)}\n"
                    f"- non_empty: {progress.get('non_empty_count', 0)}\n"
                    f"- produced_in_run: {progress.get('produced_count', 0)}\n"
                    f"- missing: {missing}"
                )
                state.last_output = (state.last_output + "\n\n" if state.last_output else "") + diag
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
            if state.status == RunStatus.FAILED and self.settings.experience_enabled:
                failure_row = self._record_failure_experience(
                    state=state,
                    selected_skills=sorted(skills_seen_in_run),
                    actions=previous_actions,
                    action_results=previous_action_results,
                    failure_fingerprint=latest_failure_fingerprint,
                    produced_files=produced_files_in_run,
                )
                failure_class = str((failure_row or {}).get("failure_class", "")).strip()
                self._record_strategy_outcomes(
                    active_strategy_keys,
                    success=False,
                    run_id=state.run_id,
                    failure_class=failure_class,
                )
                if failure_class:
                    escalated = self._apply_auto_escalation_message(state=state, failure_class=failure_class)
                    if escalated:
                        self.store.write_state(state)
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

    def _collect_required_output_baseline(
        self,
        workspace: Path,
        required_outputs: list[str],
    ) -> dict[str, tuple[bool, int, int]]:
        root = workspace.resolve()
        baseline: dict[str, tuple[bool, int, int]] = {}
        for rel in required_outputs:
            target = (root / rel).resolve()
            if not self._is_within_root(target, root):
                baseline[rel] = (False, 0, 0)
                continue
            if not target.exists() or not target.is_file():
                baseline[rel] = (False, 0, 0)
                continue
            stat = target.stat()
            baseline[rel] = (True, int(stat.st_size), int(stat.st_mtime_ns))
        return baseline

    def _snapshot_updated_required_outputs(
        self,
        state: RunState,
        workspace: Path,
        required_outputs: list[str],
        baseline: dict[str, tuple[bool, int, int]],
    ) -> set[str]:
        root = workspace.resolve()
        snapshotted: set[str] = set()
        for rel in required_outputs:
            target = (root / rel).resolve()
            if not self._is_within_root(target, root):
                continue
            if not target.exists() or not target.is_file():
                continue
            stat = target.stat()
            prev_exists, prev_size, prev_mtime = baseline.get(rel, (False, 0, 0))
            changed = (not prev_exists) or (int(stat.st_size) != prev_size) or (int(stat.st_mtime_ns) != prev_mtime)
            if not changed:
                continue
            try:
                path = self.store.snapshot_workspace_file(state.run_id, root, rel)
                if path in snapshotted:
                    continue
                snapshotted.add(path)
                self.store.log_event(state.run_id, f"artifact saved: {path}")
            except Exception as exc:
                self.store.log_event(state.run_id, f"artifact snapshot failed: {exc}")
        return snapshotted

    def _evaluate_auto_complete_validations(
        self,
        task: str,
        workspace: Path,
        produced_files: set[str],
        required_absent: list[str] | None = None,
        required_python_modules: list[str] | None = None,
        expected_text_markers: list[str] | None = None,
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
            required_absent=required_absent or [],
            required_python_modules=required_python_modules or [],
            expected_text_markers=expected_text_markers or [],
        )

    def _should_auto_complete_answer_only_on_max_iters(
        self,
        task: str,
        required_outputs: list[str],
        last_output: str,
        last_action_results: list[dict[str, Any]],
    ) -> bool:
        if required_outputs:
            return False
        if not self._is_answer_only_task(task):
            return False
        output = (last_output or "").strip()
        if not output:
            return False
        lowered = output.lower()
        if "[validation] failed" in lowered or "planner_parse_error" in lowered:
            return False
        if any(not bool(item.get("ok", False)) for item in last_action_results):
            return False
        return True

    def _is_answer_only_task(self, task: str) -> bool:
        text = (task or "").lower()
        if not text:
            return False
        write_or_side_effect_markers = (
            "เขียน",
            "สร้างไฟล์",
            "บันทึก",
            "save",
            "write",
            "create",
            "script",
            ".py",
            ".md",
            ".txt",
            ".json",
            ".csv",
            "run ",
            "execute",
            "ติดตั้ง",
            "install",
            "ลบ",
            "delete",
            "remove",
            "ส่งอีเมล",
            "send email",
            "email",
        )
        if any(marker in text for marker in write_or_side_effect_markers):
            return False

        answer_markers = (
            "สรุป",
            "summary",
            "อธิบาย",
            "explain",
            "วิเคราะห์",
            "analy",
            "ข่าว",
            "news",
            "คืออะไร",
            "what is",
            "วันนี้วันที่เท่าไหร่",
            "date today",
        )
        if any(marker in text for marker in answer_markers):
            return True
        if ("http://" in text) or ("https://" in text) or ("www." in text):
            return True
        return False

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

    def _is_planner_parse_error(self, plan: dict[str, Any]) -> bool:
        if not isinstance(plan, dict):
            return False
        text = str(plan.get("final_output", "")).lower()
        if "planner_parse_error" not in text:
            return False
        actions = plan.get("actions", [])
        return not actions

    def _build_capability_failure_fingerprint(self, action_results: list[dict[str, Any]]) -> str:
        signals: list[str] = []
        for item in action_results:
            if bool(item.get("ok", False)):
                continue
            blob = (str(item.get("error", "")) + "\n" + str(item.get("output", ""))).strip().lower()
            if not blob:
                continue
            matched = False

            missing_module = re.search(r"no module named ['\"]?([a-z0-9_.-]+)['\"]?", blob)
            if missing_module:
                signals.append(f"missing_module:{missing_module.group(1)}")
                matched = True

            missing_bin = re.search(r"no such file or directory: ['\"]?([a-z0-9_.-]+)['\"]?", blob)
            if missing_bin:
                signals.append(f"missing_binary:{missing_bin.group(1)}")
                matched = True

            allowlist = re.search(r"command is not allowlisted:\s*([a-z0-9_.-]+)", blob)
            if allowlist:
                signals.append(f"blocked_command:{allowlist.group(1)}")
                matched = True

            if "certificate verify failed" in blob or "ssl:" in blob:
                signals.append("network_tls")
                matched = True

            if "planner_parse_error" in blob:
                signals.append("planner_parse_error")
                matched = True

            if not matched:
                signals.append(blob[:120])

        if not signals:
            return ""
        uniq = sorted(set(signals))
        return ",".join(uniq)

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

            args_raw = params.get("args")
            if isinstance(args_raw, list):
                mapped_args: list[str] = []
                for item in args_raw:
                    mapped_args.append(
                        self._rewrite_skill_path_token_to_workspace(
                            token=str(item),
                            skills_root=skills_root,
                            workspace=workspace,
                        )
                    )
                params["args"] = mapped_args

            command = self._normalize_shell_python_alias(command)
            command = self._rewrite_shell_skill_paths_in_command(
                command=command,
                skills_root=skills_root,
                workspace=workspace,
            )
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

        if name == "read_file":
            path_value = str(params.get("path", "")).strip()
            if path_value:
                params["path"] = self._rewrite_skill_path_token_to_workspace(
                    token=path_value,
                    skills_root=skills_root,
                    workspace=workspace,
                )
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
                script_code = skill_script.read_text(encoding="utf-8")
                secret_files = self._collect_skill_secret_files(skill_script=skill_script, skills_root=skills_root)
                params["code"] = self._with_embedded_files_prelude(
                    script_code,
                    embedded_files=secret_files,
                    var_name="__softnix_skill_secret_files",
                )
                params["skill_source_path"] = str(skill_script)
            else:
                code_text = str(params.get("code", ""))
                if code_text.strip():
                    params["code"] = self._rewrite_embedded_skill_script_refs(code_text, skills_root)
            return prepared

        return prepared

    def _rewrite_shell_skill_paths_in_command(self, command: str, skills_root: Path, workspace: Path) -> str:
        try:
            parts = shlex.split(command)
        except Exception:
            return command
        if not parts:
            return command
        mapped = [
            self._rewrite_skill_path_token_to_workspace(
                token=token,
                skills_root=skills_root,
                workspace=workspace,
            )
            for token in parts
        ]
        return shlex.join(mapped)

    def _rewrite_skill_path_token_to_workspace(self, token: str, skills_root: Path, workspace: Path) -> str:
        text = (token or "").strip()
        if not text:
            return token
        resolved = self._resolve_skill_file_path(value=text, skills_root=skills_root)
        if resolved is None:
            return token
        rel = self._materialize_skill_file_to_workspace(
            source_file=resolved,
            skills_root=skills_root,
            workspace=workspace,
        )
        return rel or token

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
        return self._resolve_skill_file_path(value=value, skills_root=skills_root, allowed_suffixes={".py"})

    def _resolve_skill_file_path(
        self,
        value: str,
        skills_root: Path,
        allowed_suffixes: set[str] | None = None,
    ) -> Path | None:
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
                if allowed_suffixes is not None and candidate.suffix.lower() not in allowed_suffixes:
                    continue
                return candidate
        return None

    def _materialize_skill_file_to_workspace(self, source_file: Path, skills_root: Path, workspace: Path) -> str:
        root = skills_root.resolve()
        src = source_file.resolve()
        if not self._is_within_root(src, root):
            return ""
        try:
            rel = src.relative_to(root)
        except ValueError:
            return ""
        dst_rel = Path(".softnix_skill_exec") / rel
        dst = (workspace.resolve() / dst_rel).resolve()
        if not self._is_within_root(dst, workspace.resolve()):
            return ""
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = src.read_text(encoding="utf-8")
            dst.write_text(content, encoding="utf-8")
        except Exception:
            return ""
        return str(dst_rel).replace("\\", "/")

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
            for sec_path, sec_content in self._collect_skill_secret_files(
                skill_script=resolved,
                skills_root=skills_root,
            ).items():
                embedded_files[sec_path] = sec_content

        if not replacements:
            return code

        rewritten = code
        for src, dst in replacements.items():
            rewritten = rewritten.replace(f"'{src}'", repr(dst))
            rewritten = rewritten.replace(f'"{src}"', repr(dst))

        return self._with_embedded_files_prelude(
            rewritten,
            embedded_files=embedded_files,
            var_name="__softnix_skill_files",
        )

    def _collect_skill_secret_files(self, skill_script: Path, skills_root: Path) -> dict[str, str]:
        root = skills_root.resolve()
        script = skill_script.resolve()
        if not self._is_within_root(script, root):
            return {}
        rel = script.relative_to(root)
        parts = rel.parts
        if not parts:
            return {}
        skill_name = parts[0]
        secret_dir = (root / skill_name / ".secret").resolve()
        if not self._is_within_root(secret_dir, root):
            return {}
        if not secret_dir.exists() or not secret_dir.is_dir():
            return {}

        files: dict[str, str] = {}
        for candidate in sorted(secret_dir.rglob("*")):
            if not candidate.is_file():
                continue
            try:
                rel_secret = candidate.relative_to(root / skill_name)
            except Exception:
                continue
            exec_rel = str(Path(".softnix_skill_exec") / skill_name / rel_secret).replace("\\", "/")
            files[exec_rel] = candidate.read_text(encoding="utf-8")
        return files

    def _with_embedded_files_prelude(
        self,
        code: str,
        embedded_files: dict[str, str],
        var_name: str = "__softnix_skill_files",
    ) -> str:
        if not embedded_files:
            return code
        prelude_lines = [
            "from pathlib import Path as __softnix_Path",
            f"{var_name} = {{",
        ]
        for path, content in embedded_files.items():
            prelude_lines.append(f"    {repr(path)}: {repr(content)},")
        prelude_lines.extend(
            [
                "}",
                f"for __p, __c in {var_name}.items():",
                "    __t = __softnix_Path(__p)",
                "    __t.parent.mkdir(parents=True, exist_ok=True)",
                "    __t.write_text(__c, encoding='utf-8')",
                "",
            ]
        )
        prelude = "\n".join(prelude_lines)
        return self._insert_prelude_after_future_imports(code=code, prelude=prelude)

    def _insert_prelude_after_future_imports(self, code: str, prelude: str) -> str:
        source = code or ""
        if not source.strip():
            return prelude
        try:
            tree = ast.parse(source)
        except Exception:
            return prelude + source

        insert_after_line = 0
        for node in tree.body:
            is_docstring = (
                isinstance(node, ast.Expr)
                and isinstance(getattr(node, "value", None), ast.Constant)
                and isinstance(getattr(node.value, "value", None), str)
            )
            if is_docstring:
                insert_after_line = max(insert_after_line, int(getattr(node, "end_lineno", node.lineno)))
                continue

            is_future = isinstance(node, ast.ImportFrom) and str(getattr(node, "module", "")) == "__future__"
            if is_future:
                insert_after_line = max(insert_after_line, int(getattr(node, "end_lineno", node.lineno)))
                continue
            break

        if insert_after_line <= 0:
            return prelude + source

        lines = source.splitlines(keepends=True)
        prefix = "".join(lines[:insert_after_line])
        suffix = "".join(lines[insert_after_line:])
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        return prefix + prelude + suffix

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
                any(tok in text for tok in {"email", "e-mail", "mail", "resend"})
                or any(("sendmail" in name or "mail" in name) for name in skill_names)
            ):
                # Sendmail skill needs third-party package(s) not present in python:slim.
                profile = "data"
            elif (
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

    def _build_plan_with_retry(
        self,
        state: RunState,
        task: str,
        iteration: int,
        max_iters: int,
        previous_output: str,
        skills_context: str,
        experience_context: str,
        memory_context: str,
        runtime_guidance: str,
    ) -> tuple[dict[str, Any], dict[str, int], str, int]:
        retry_enabled = bool(self.settings.planner_retry_on_parse_error)
        max_attempts = max(1, int(self.settings.planner_retry_max_attempts))
        attempts = max_attempts if retry_enabled else 1
        merged_usage: dict[str, int] = {}
        last_plan: dict[str, Any] = {}
        last_prompt = ""

        for attempt in range(1, attempts + 1):
            if attempt == 1:
                cur_prev = previous_output
                cur_skills = skills_context
                cur_experience = experience_context
                cur_memory = memory_context
                cur_guidance = runtime_guidance
            else:
                cur_prev = ""
                cur_skills = self._degraded_skills_context(skills_context)
                cur_experience = self._degraded_experience_context(experience_context)
                cur_memory = self._degraded_memory_context(memory_context)
                cur_guidance = self._degraded_runtime_guidance(runtime_guidance)
                self.store.log_event(
                    state.run_id,
                    f"planner retry attempt={attempt}/{attempts} mode=reduced_context",
                )

            plan, usage, prompt_text = self.planner.build_plan(
                task=task,
                iteration=iteration,
                max_iters=max_iters,
                previous_output=cur_prev,
                skills_context=cur_skills,
                experience_context=cur_experience,
                memory_context=cur_memory,
                runtime_guidance=cur_guidance,
            )
            merged_usage = self._merge_token_usage(merged_usage, usage)
            last_plan = plan
            last_prompt = prompt_text
            if not self._is_planner_parse_error(plan):
                if attempt > 1:
                    self.store.log_event(
                        state.run_id,
                        f"planner retry recovered attempt={attempt}",
                    )
                return plan, merged_usage, prompt_text, attempt

        return last_plan, merged_usage, last_prompt, attempts

    def _degraded_skills_context(self, skills_context: str) -> str:
        raw = (skills_context or "").strip()
        if not raw:
            return "- none"
        lines = [line for line in raw.splitlines() if line.strip()]
        keep = lines[: min(8, len(lines))]
        keep.append("- (degraded mode) return strict valid JSON plan only")
        return "\n".join(keep)

    def _degraded_memory_context(self, memory_context: str) -> str:
        raw = (memory_context or "").strip()
        if not raw:
            return "- none"
        lines = [line for line in raw.splitlines() if line.strip()]
        return "\n".join(lines[: min(8, len(lines))])

    def _degraded_experience_context(self, experience_context: str) -> str:
        raw = (experience_context or "").strip()
        if not raw or raw == "- none":
            return "- none"
        lines = [line for line in raw.splitlines() if line.strip()]
        return "\n".join(lines[: min(10, len(lines))])

    def _degraded_runtime_guidance(self, runtime_guidance: str) -> str:
        raw = (runtime_guidance or "").strip()
        if not raw:
            return "- none"
        lines = [line for line in raw.splitlines() if line.strip()]
        return "\n".join(lines[: min(12, len(lines))])

    def _build_experience_context(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "- none"
        lines: list[str] = ["Past successful patterns (similar tasks):"]
        for idx, row in enumerate(rows[: max(1, int(self.settings.experience_retrieval_top_k))], start=1):
            task = str(row.get("task", "")).strip()
            task_preview = task[:140] + ("..." if len(task) > 140 else "")
            skills = [str(x).strip() for x in row.get("selected_skills", []) if str(x).strip()]
            actions = [str(x).strip() for x in row.get("action_sequence", []) if str(x).strip()]
            summary = str(row.get("summary", "")).strip()
            lines.append(f"{idx}. task={task_preview or '(n/a)'}")
            if skills:
                lines.append(f"   skills={','.join(skills[:5])}")
            if actions:
                lines.append(f"   actions={','.join(actions[:8])}")
            if summary:
                short_summary = summary[:160] + ("..." if len(summary) > 160 else "")
                lines.append(f"   outcome_hint={short_summary}")
        lines.append("Reuse only if relevant; adapt inputs/paths for the current task.")
        return "\n".join(lines)

    def _record_success_experience(
        self,
        state: RunState,
        selected_skills: list[str],
        action_history: list[str],
        produced_files: set[str],
    ) -> None:
        if not self.settings.experience_enabled:
            return
        unique_actions: list[str] = []
        seen_action: set[str] = set()
        for action in action_history:
            name = str(action).strip()
            if not name or name in seen_action:
                continue
            seen_action.add(name)
            unique_actions.append(name)
        if not self._should_record_experience(
            task=state.task,
            action_sequence=unique_actions,
            produced_files=produced_files,
        ):
            self.store.log_event(
                state.run_id,
                "experience skipped reason=low_signal_or_preparatory_only",
            )
            return
        task_tokens = sorted(self._experience_task_tokens(state.task))
        payload = {
            "run_id": state.run_id,
            "status": "completed",
            "task": state.task,
            "task_tokens": task_tokens,
            "selected_skills": [str(x).strip() for x in selected_skills if str(x).strip()],
            "action_sequence": unique_actions[:20],
            "produced_files": sorted(str(x) for x in produced_files)[:50],
            "summary": (state.last_output or "")[:500],
        }
        self.store.append_success_experience(payload, max_items=self.settings.experience_store_max_items)
        self.store.log_event(
            state.run_id,
            "experience recorded "
            f"skills={len(payload['selected_skills'])} actions={len(payload['action_sequence'])}",
        )

    def _record_failure_experience(
        self,
        state: RunState,
        selected_skills: list[str],
        actions: list[dict[str, Any]],
        action_results: list[dict[str, Any]],
        failure_fingerprint: str,
        produced_files: set[str],
    ) -> dict[str, Any]:
        classification = self._classify_failure(
            stop_reason=state.stop_reason,
            last_output=state.last_output,
            action_results=action_results,
            failure_fingerprint=failure_fingerprint,
        )
        failure_class = str(classification.get("failure_class", "")).strip()
        if not failure_class:
            return {}
        strategy_key = self._strategy_key_for_failure_class(failure_class)
        payload = {
            "run_id": state.run_id,
            "status": "failed",
            "task": state.task,
            "task_tokens": sorted(self._experience_task_tokens(state.task)),
            "selected_skills": [str(x).strip() for x in selected_skills if str(x).strip()],
            "action_sequence": self._action_name_sequence(actions),
            "failure_class": failure_class,
            "strategy_key": strategy_key,
            "failure_signals": classification.get("signals", []),
            "recommended_strategy": classification.get("recommended_strategy", ""),
            "produced_files": sorted(str(x) for x in produced_files)[:50],
            "summary": (state.last_output or "")[:500],
        }
        self.store.append_failure_experience(payload, max_items=self.settings.experience_store_max_items)
        self.store.log_event(
            state.run_id,
            f"failure experience recorded class={failure_class} signals={len(payload['failure_signals'])}",
        )
        return payload

    def _classify_failure(
        self,
        stop_reason: StopReason,
        last_output: str,
        action_results: list[dict[str, Any]],
        failure_fingerprint: str,
    ) -> dict[str, Any]:
        blob = ((last_output or "") + "\n" + failure_fingerprint).lower()
        for item in action_results:
            if bool(item.get("ok", False)):
                continue
            blob += "\n" + str(item.get("error", "")).lower()
            blob += "\n" + str(item.get("output", "")).lower()

        if any(token in blob for token in ("unauthorized", "forbidden", "invalid api key", "authentication failed", "401", "403")):
            return {
                "failure_class": "auth_secret_invalid",
                "signals": ["auth/secret error"],
                "recommended_strategy": (
                    "Stop retry loop and request user to verify/rotate API key or permission, then resume."
                ),
            }
        if any(token in blob for token in ("network is unreachable", "name or service not known", "connection refused")):
            return {
                "failure_class": "network_restricted",
                "signals": ["network restricted"],
                "recommended_strategy": (
                    "Use network-enabled runtime/policy, then rerun objective command."
                ),
            }
        if "blocked by policy.allow.tools" in blob:
            return {
                "failure_class": "policy_block",
                "signals": ["policy blocked tool"],
                "recommended_strategy": (
                    "Use allowed tools or update allowlist policy before retry."
                ),
            }

        if "no module named" in blob:
            return {
                "failure_class": "missing_module",
                "signals": ["no module named"],
                "recommended_strategy": (
                    "Install missing Python module, then rerun the original objective command/script immediately."
                ),
            }
        if ("no such file or directory" in blob) or ("missing output file:" in blob):
            return {
                "failure_class": "missing_path",
                "signals": ["file not found"],
                "recommended_strategy": (
                    "Discover candidate file paths in workspace, switch to corrected path, then continue objective actions."
                ),
            }
        if "file should be absent but still exists" in blob:
            return {
                "failure_class": "absence_contract_failed",
                "signals": ["required file still exists"],
                "recommended_strategy": (
                    "Execute deletion/mutation action and verify absence before setting done=true."
                ),
            }
        if "planner_parse_error" in blob:
            return {
                "failure_class": "planner_parse_error",
                "signals": ["invalid planner json"],
                "recommended_strategy": (
                    "Return strict compact JSON plan with minimal actions; avoid markdown and long prose."
                ),
            }
        if "stopped: repeated capability block" in blob or "capability_block repeated" in blob:
            return {
                "failure_class": "capability_block",
                "signals": ["repeated capability block"],
                "recommended_strategy": (
                    "Do not repeat blocked action; choose an alternative allowed tool or different execution path."
                ),
            }
        if "validation] failed" in blob:
            return {
                "failure_class": "objective_validation_failed",
                "signals": ["objective validation failed"],
                "recommended_strategy": (
                    "Do not finish early; satisfy objective contract checks and regenerate missing/stale outputs in-run."
                ),
            }
        if stop_reason == StopReason.MAX_ITERS:
            return {
                "failure_class": "max_iters_no_completion",
                "signals": ["max iterations reached"],
                "recommended_strategy": (
                    "Prioritize objective execution within first iterations and ensure measurable progress each loop."
                ),
            }
        if stop_reason == StopReason.NO_PROGRESS:
            return {
                "failure_class": "no_progress",
                "signals": ["no progress stop"],
                "recommended_strategy": (
                    "Change strategy early when output/progress score does not improve; avoid repeating same action chain."
                ),
            }
        if stop_reason == StopReason.ERROR:
            return {
                "failure_class": "runtime_error",
                "signals": ["unhandled runtime error"],
                "recommended_strategy": "Inspect latest error, fix root cause, then rerun objective action.",
            }
        return {"failure_class": "", "signals": [], "recommended_strategy": ""}

    def _build_failure_strategy_guidance(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "- none"
        lines: list[str] = ["Failure avoidance strategies (similar failures):"]
        for idx, row in enumerate(rows[:2], start=1):
            failure_class = str(row.get("failure_class", "")).strip() or "unknown"
            strategy = str(row.get("recommended_strategy", "")).strip()
            task = str(row.get("task", "")).strip()
            task_preview = task[:100] + ("..." if len(task) > 100 else "")
            strategy_key = str(row.get("strategy_key", "")).strip()
            score = float(self.store.get_strategy_effectiveness_score(strategy_key)) if strategy_key else 0.0
            score_tag = f" score={score:+.2f}" if strategy_key else ""
            lines.append(f"{idx}. class={failure_class}{score_tag} task={task_preview or '(n/a)'}")
            if strategy:
                lines.append(f"   strategy={strategy}")
        lines.append("Avoid repeating the same failure pattern; adapt strategy to current objective.")
        return "\n".join(lines)

    def _strategy_key_for_failure_class(self, failure_class: str) -> str:
        value = str(failure_class or "").strip().lower()
        if not value:
            return ""
        return f"failure_class:{value}"

    def _record_strategy_outcomes(
        self,
        strategy_keys: set[str],
        *,
        success: bool,
        run_id: str,
        failure_class: str = "",
    ) -> None:
        for key in sorted(str(x).strip() for x in strategy_keys if str(x).strip()):
            self.store.append_strategy_outcome(
                strategy_key=key,
                success=success,
                failure_class=failure_class,
                run_id=run_id,
                max_items=max(500, int(self.settings.experience_store_max_items) * 4),
            )

    def _apply_auto_escalation_message(self, state: RunState, failure_class: str) -> bool:
        guidance_map = {
            "auth_secret_invalid": (
                "ต้องการการยืนยัน/แก้ไขจากผู้ใช้: ตรวจสอบ API key/secret และสิทธิ์ใช้งาน "
                "แล้วรันใหม่ (เช่น key หมดอายุ, unauthorized, forbidden)"
            ),
            "network_restricted": (
                "ต้องการการยืนยันจากผู้ใช้: งานต้องใช้งานเครือข่ายแต่ถูกจำกัด "
                "ให้เปิด network policy/runtime network แล้วรันใหม่"
            ),
            "policy_block": (
                "ต้องการการยืนยันจากผู้ใช้: action ถูกบล็อกโดย policy.allow.tools "
                "ให้ปรับ policy หรือเปลี่ยนแนวทางที่อยู่ใน allowlist"
            ),
        }
        note = guidance_map.get(str(failure_class).strip().lower())
        if not note:
            return False
        output = (state.last_output or "").strip()
        if note in output:
            return False
        state.last_output = f"{output}\n\n[auto-escalation]\n- {note}".strip()
        return True

    def _action_name_sequence(self, actions: list[dict[str, Any]]) -> list[str]:
        rows: list[str] = []
        for item in actions:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            rows.append(name)
        return rows[:20]

    def _should_replan_for_repeated_failed_sequence(
        self,
        actions: list[dict[str, Any]],
        failure_rows: list[dict[str, Any]],
    ) -> bool:
        planned = self._action_name_sequence(actions)
        if not planned:
            return False
        planned_sig = self._action_sequence_signature(planned)
        if not planned_sig:
            return False
        for row in failure_rows:
            failed = [str(x).strip() for x in row.get("action_sequence", []) if str(x).strip()]
            failed_sig = self._action_sequence_signature(failed)
            if failed_sig and failed_sig == planned_sig:
                return True
        return False

    def _action_sequence_signature(self, names: list[str], max_len: int = 4) -> str:
        rows = [str(x).strip().lower() for x in names if str(x).strip()]
        if not rows:
            return ""
        return ",".join(rows[: max(1, int(max_len))])

    def _describe_failure_action_patterns(self, failure_rows: list[dict[str, Any]], limit: int = 3) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for row in failure_rows:
            sequence = [str(x).strip() for x in row.get("action_sequence", []) if str(x).strip()]
            sig = self._action_sequence_signature(sequence)
            if not sig or sig in seen:
                continue
            seen.add(sig)
            failure_class = str(row.get("failure_class", "")).strip() or "unknown"
            lines.append(f"- avoid pattern [{sig}] class={failure_class}")
            if len(lines) >= max(1, int(limit)):
                break
        if not lines:
            return "- avoid repeating identical failed action sequence"
        return "\n".join(lines)

    def _should_record_experience(
        self,
        task: str,
        action_sequence: list[str],
        produced_files: set[str],
    ) -> bool:
        if produced_files:
            return True
        actions = [str(x).strip() for x in action_sequence if str(x).strip()]
        if not actions:
            return self._is_answer_only_task(task) and (not self._task_requires_document_read(task))
        preparatory_only = {"list_dir", "read_file"}
        if all(action in preparatory_only for action in actions):
            return False
        return True

    def _task_requires_document_read(self, task: str) -> bool:
        text = (task or "").lower()
        if not text:
            return False
        markers = (
            "pdf",
            "เอกสาร",
            "file",
            "ไฟล์",
            "อ่านข้อมูล",
            "extract",
            "ocr",
        )
        return any(marker in text for marker in markers)

    def _experience_task_tokens(self, text: str) -> set[str]:
        raw = re.findall(r"[a-z0-9ก-๙_-]+", (text or "").lower())
        tokens: set[str] = set()
        for token in raw:
            item = token.strip()
            if len(item) < 2:
                continue
            tokens.add(item)
        return tokens

    def _merge_token_usage(self, current: dict[str, int], incoming: dict[str, int]) -> dict[str, int]:
        merged = dict(current)
        for k, v in (incoming or {}).items():
            try:
                merged[k] = int(merged.get(k, 0)) + int(v)
            except Exception:
                continue
        return merged

    def _build_runtime_guidance(
        self,
        task: str,
        workspace: Path,
        required_outputs: list[str],
        produced_files: set[str],
        previous_actions: list[dict[str, Any]],
        previous_action_results: list[dict[str, Any]],
        objective_stagnation_streak: int,
        required_absent: list[str] | None = None,
        hinted_directories: list[str] | None = None,
    ) -> str:
        guidance: list[str] = []
        if not self._is_answer_only_task(task):
            guidance.append(
                "Repair loop protocol: diagnose root cause -> apply concrete fix -> execute objective -> validate evidence."
            )
        progress = self._objective_progress_snapshot(
            workspace=workspace,
            required_outputs=required_outputs,
            produced_files=produced_files,
        )

        if required_outputs:
            missing = progress.get("missing_paths", [])
            guidance.append(
                "Objective contract:"
                f" required={progress.get('required_total', 0)}"
                f" existing={progress.get('existing_count', 0)}"
                f" non_empty={progress.get('non_empty_count', 0)}"
                f" produced_required={progress.get('produced_required_count', 0)}"
                f" produced_in_run={progress.get('produced_count', 0)}"
            )
            if missing:
                guidance.append(f"Missing outputs: {', '.join(missing[:8])}")
            stale = progress.get("stale_paths", [])
            if stale:
                guidance.append(f"Existing but stale outputs (must regenerate in this run): {', '.join(stale[:8])}")
        absent_targets = required_absent or []
        if absent_targets:
            guidance.append(
                "Absence contract:"
                f" required_absent={len(absent_targets)}"
                f" targets={', '.join(absent_targets[:8])}"
            )
        elif not self._is_answer_only_task(task):
            guidance.append(
                "Execution objective: this task requires performing an operation "
                "(not only reading/analyzing). Execute the target command/script and verify success."
            )

        if self._is_preparatory_only_iteration(previous_actions=previous_actions, previous_action_results=previous_action_results):
            guidance.append(
                "Previous iteration was preparatory only (inspection/install/date checks). "
                "Now execute the real objective action."
            )

        if self._has_recent_dependency_install(previous_actions=previous_actions, previous_action_results=previous_action_results):
            guidance.append(
                "Dependency installation succeeded in the previous iteration. "
                "Immediately rerun the original objective command/script now."
            )

        missing_paths = self._extract_missing_paths_from_results(previous_action_results)
        if missing_paths:
            guidance.append("Previous iteration had missing file/path errors.")
            for missing in missing_paths[:5]:
                candidates = self._find_workspace_file_candidates(
                    workspace=workspace,
                    missing_path=missing,
                    limit=3,
                    hinted_directories=hinted_directories,
                )
                if candidates:
                    guidance.append(f"Path recovery: {missing} -> candidates: {', '.join(candidates)}")
                else:
                    guidance.append(f"Path recovery: {missing} -> no candidates found yet")
            guidance.append("Recovery policy: discover actual file path first, then continue execution with corrected path.")

        threshold = max(2, int(self.settings.objective_stagnation_replan_threshold))
        if objective_stagnation_streak >= threshold:
            guidance.append(
                "Stagnation detected: previous plans did not improve objective progress. "
                "Re-plan with a different strategy and execute actions that create or validate required outputs."
            )

        if not guidance:
            return "- none"
        return "\n".join(guidance)

    def _estimate_action_confidence(self, action: dict[str, Any], result: dict[str, Any]) -> tuple[float, str]:
        ok = bool(result.get("ok", False))
        if not ok:
            return 0.0, "action failed"
        name = str(action.get("name", "")).strip().lower()
        output = str(result.get("output", "")).lower()
        if name in {"write_workspace_file", "write_file"}:
            return 0.95, "direct file write succeeded"
        if name in {"read_file", "list_dir"}:
            return 0.55, "read/inspect only"
        if name in {"run_python_code", "run_safe_command", "run_shell_command"}:
            if "error=" in output or "traceback" in output:
                return 0.25, "runtime error indicators in output"
            if "redirected output:" in output or "written:" in output or "created" in output:
                return 0.78, "execution reported tangible output"
            return 0.62, "execution succeeded but evidence is limited"
        return 0.6, "default confidence"

    def _has_low_confidence_results(self, action_results: list[dict[str, Any]], threshold: float = 0.45) -> bool:
        for row in action_results:
            if not bool(row.get("ok", False)):
                continue
            conf = row.get("confidence")
            try:
                value = float(conf)
            except Exception:
                continue
            if value < threshold:
                return True
        return False

    def _is_preparatory_only_iteration(
        self,
        previous_actions: list[dict[str, Any]],
        previous_action_results: list[dict[str, Any]],
    ) -> bool:
        if not previous_actions:
            return False

        paired = list(zip(previous_actions, previous_action_results))
        if not paired:
            return False

        all_ok = all(bool(result.get("ok", False)) for _, result in paired)
        if not all_ok:
            return False

        prepared_action_names = {"read_file", "list_dir"}
        for action, result in paired:
            action_name = str(action.get("name", "")).strip().lower()
            result_name = str(result.get("name", "")).strip().lower()
            effective_name = action_name or result_name
            if effective_name in prepared_action_names:
                continue
            if effective_name in {"run_shell_command", "run_safe_command"}:
                params = action.get("params", {}) if isinstance(action.get("params"), dict) else {}
                command = str(params.get("command", "")).strip().lower()
                args = params.get("args")
                if self._is_pip_install_command(command=command, args=args):
                    continue
            return False
        return True

    def _has_recent_dependency_install(
        self,
        previous_actions: list[dict[str, Any]],
        previous_action_results: list[dict[str, Any]],
    ) -> bool:
        for action, result in zip(previous_actions, previous_action_results):
            if not bool(result.get("ok", False)):
                continue
            params = action.get("params", {}) if isinstance(action.get("params"), dict) else {}
            command = str(params.get("command", "")).strip().lower()
            args = params.get("args")
            if not self._is_pip_install_command(command=command, args=args):
                continue
            output = str(result.get("output", "")).lower()
            if "successfully installed" in output:
                return True
        return False

    def _is_pip_install_command(self, command: str, args: Any) -> bool:
        cmd = (command or "").strip().lower()
        arg_list = [str(a).strip().lower() for a in args] if isinstance(args, list) else []

        if cmd in {"pip", "pip3"}:
            return bool(arg_list) and arg_list[0] == "install"

        parts = [p for p in cmd.split() if p]
        if len(parts) >= 3 and parts[0] in {"python", "python3"} and parts[1] == "-m" and parts[2] == "pip":
            if len(parts) >= 4 and parts[3] == "install":
                return True
            return bool(arg_list) and arg_list[0] == "install"
        return False

    def _should_force_execution_replan(
        self,
        task: str,
        iteration: int,
        required_outputs: list[str],
        actions: list[dict[str, Any]],
    ) -> bool:
        if iteration <= 1:
            return False
        if self._is_answer_only_task(task):
            return False
        # For operational tasks without explicit output contract, block preparatory-only loops.
        if required_outputs:
            return False
        return self._is_preparatory_plan_actions(actions)

    def _should_force_repair_replan(
        self,
        previous_action_results: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> bool:
        if not previous_action_results:
            return False
        had_failure = any(not bool(item.get("ok", False)) for item in previous_action_results)
        if not had_failure:
            return False
        return self._is_preparatory_plan_actions(actions)

    def _is_preparatory_plan_actions(self, actions: list[dict[str, Any]]) -> bool:
        if not actions:
            return True
        for action in actions:
            if not isinstance(action, dict):
                return False
            name = str(action.get("name", "")).strip().lower()
            params = action.get("params", {}) if isinstance(action.get("params"), dict) else {}
            if name in {"read_file", "list_dir"}:
                continue
            if name in {"run_shell_command", "run_safe_command"}:
                command = str(params.get("command", "")).strip().lower()
                if self._is_pip_install_command(command=command, args=params.get("args")):
                    continue
                if command in {"pwd", "date", "ls", "cat"}:
                    continue
                return False
            if name == "run_python_code":
                path = str(params.get("path", "")).strip()
                if path:
                    return False
                code = str(params.get("code", "")).lower()
                mutating_markers = (
                    "write_text(",
                    ".write(",
                    "open(",
                    "subprocess",
                    "os.system",
                    "resend.emails.send",
                    "requests.",
                    "httpx.",
                    "web_fetch",
                )
                if any(marker in code for marker in mutating_markers):
                    return False
                prep_markers = ("datetime", "date.today", "timedelta", "print(")
                if any(marker in code for marker in prep_markers):
                    continue
                return False
            return False
        return True

    def _objective_progress_snapshot(
        self,
        workspace: Path,
        required_outputs: list[str],
        produced_files: set[str],
    ) -> dict[str, Any]:
        root = workspace.resolve()
        existing_count = 0
        non_empty_count = 0
        produced_required_count = 0
        missing_paths: list[str] = []
        stale_paths: list[str] = []
        for raw in required_outputs:
            target = (root / raw).resolve()
            if not self._is_within_root(target, root):
                missing_paths.append(raw)
                continue
            if not target.exists() or not target.is_file():
                missing_paths.append(raw)
                continue
            existing_count += 1
            if raw in produced_files:
                produced_required_count += 1
            else:
                stale_paths.append(raw)
            require_non_empty = self._should_require_non_empty_output(raw)
            if not require_non_empty:
                non_empty_count += 1
                continue
            if target.stat().st_size > 0:
                non_empty_count += 1
            else:
                missing_paths.append(raw)

        produced_count = len(produced_files)
        # Weighted score: prioritize required objective completion over side artifacts.
        score = (produced_required_count * 4) + (existing_count * 2) + (non_empty_count * 3) + produced_count
        return {
            "required_total": len(required_outputs),
            "existing_count": existing_count,
            "non_empty_count": non_empty_count,
            "produced_required_count": produced_required_count,
            "produced_count": produced_count,
            "missing_paths": missing_paths,
            "stale_paths": stale_paths,
            "score": score,
        }

    def _extract_missing_paths_from_results(self, action_results: list[dict[str, Any]]) -> list[str]:
        paths: list[str] = []
        patterns = [
            re.compile(r"FileNotFoundError: .*?No such file or directory: ['\"]([^'\"]+)['\"]", flags=re.IGNORECASE),
            re.compile(r"No such file or directory: ['\"]([^'\"]+)['\"]", flags=re.IGNORECASE),
            re.compile(r"Not a file:\s*([^\n]+)", flags=re.IGNORECASE),
        ]
        for item in action_results:
            if bool(item.get("ok", False)):
                continue
            blob = (str(item.get("error", "")) + "\n" + str(item.get("output", ""))).strip()
            if not blob:
                continue
            for pattern in patterns:
                for match in pattern.finditer(blob):
                    candidate = match.group(1).strip()
                    if candidate:
                        paths.append(candidate)

        seen: set[str] = set()
        uniq: list[str] = []
        for path in paths:
            normalized = path.strip().strip("'\"")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            uniq.append(normalized)
        return uniq

    def _find_workspace_file_candidates(
        self,
        workspace: Path,
        missing_path: str,
        limit: int = 3,
        hinted_directories: list[str] | None = None,
    ) -> list[str]:
        return self._path_discovery_policy.find_candidates(
            workspace=workspace,
            missing_path=missing_path,
            hinted_directories=hinted_directories or [],
            limit=limit,
        )

    def _evaluate_objective_validations(
        self,
        task: str,
        plan: dict[str, Any],
        workspace: Path,
        produced_files: set[str] | None = None,
        required_absent: list[str] | None = None,
        required_python_modules: list[str] | None = None,
        expected_text_markers: list[str] | None = None,
    ) -> dict[str, Any]:
        checks = self._collect_validation_checks(
            task=task,
            plan=plan,
            produced_files=produced_files,
            required_absent=required_absent or [],
            required_python_modules=required_python_modules or [],
            expected_text_markers=expected_text_markers or [],
        )
        if not checks:
            return {"ok": True, "failures": [], "checks": []}

        failures: list[str] = []
        inferred_paths = self._infer_output_files_from_task(task)
        if produced_files is not None and inferred_paths:
            missing_in_run = sorted(path for path in inferred_paths if path not in produced_files)
            for path in missing_in_run:
                failures.append(f"inferred output not produced in this run: {path}")

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
            raw_path_text = str(check.get("path", "")).strip()
            path_text = self._resolve_validation_path(raw_path_text, produced_files)
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
            if ctype == "file_absent":
                if target.exists():
                    failures.append(f"file should be absent but still exists: {path_text}")
                continue
            if ctype == "file_non_empty":
                if not target.exists() or not target.is_file():
                    failures.append(f"missing output file: {path_text}")
                    continue
                if target.stat().st_size <= 0:
                    failures.append(f"output file is empty: {path_text}")
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
            if ctype in {"json_key_exists", "json_key_equals"}:
                if not target.exists() or not target.is_file():
                    failures.append(f"missing output file: {path_text}")
                    continue
                key = str(check.get("key", "")).strip()
                if not key:
                    failures.append(f"validation missing key for {path_text}")
                    continue
                try:
                    payload = json.loads(target.read_text(encoding="utf-8"))
                except Exception:
                    failures.append(f"invalid json in {path_text}")
                    continue
                if not isinstance(payload, dict):
                    failures.append(f"json root is not object in {path_text}")
                    continue
                if key not in payload:
                    failures.append(f"json key not found in {path_text}: {key}")
                    continue
                if ctype == "json_key_equals":
                    expected = str(check.get("value", ""))
                    actual = str(payload.get(key))
                    if actual != expected:
                        failures.append(
                            f"json key mismatch in {path_text}: {key} expected={expected!r} actual={actual!r}"
                        )
                continue
            failures.append(f"unknown validation type: {ctype}")

        return {"ok": len(failures) == 0, "failures": failures, "checks": checks}

    def _collect_validation_checks(
        self,
        task: str,
        plan: dict[str, Any],
        produced_files: set[str] | None = None,
        required_absent: list[str] | None = None,
        required_python_modules: list[str] | None = None,
        expected_text_markers: list[str] | None = None,
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
                key = str(item.get("key", "")).strip()
                value = str(item.get("value", ""))
                if ctype in {
                    "file_exists",
                    "file_absent",
                    "file_non_empty",
                    "text_in_file",
                    "python_import",
                    "json_key_exists",
                    "json_key_equals",
                } and path:
                    payload = {"type": ctype, "path": path}
                    if ctype == "text_in_file":
                        payload["contains"] = contains
                    if ctype == "python_import":
                        payload["module"] = module
                    if ctype in {"json_key_exists", "json_key_equals"}:
                        payload["key"] = key
                    if ctype == "json_key_equals":
                        payload["value"] = value
                    checks.append(payload)

        inferred_files = self._infer_output_files_from_task(task)
        for path in inferred_files:
            checks.append({"type": "file_exists", "path": path})
            if self._should_require_non_empty_output(path):
                checks.append({"type": "file_non_empty", "path": path})

        for path in (required_absent or []):
            checks.append({"type": "file_absent", "path": path})

        lowered_task = (task or "").lower()
        if "pytest" in lowered_task:
            for path in inferred_files:
                if path.endswith("result.txt"):
                    checks.append({"type": "text_in_file", "path": path, "contains": "pytest"})

        required_modules = [
            str(x).strip().lower()
            for x in (required_python_modules or self._infer_required_python_modules_from_task(task))
            if str(x).strip()
        ]
        if required_modules:
            python_files = [path for path in inferred_files if path.endswith(".py")]
            if produced_files:
                python_files = [path for path in python_files if path in produced_files]
            for path in python_files:
                for module in required_modules:
                    checks.append({"type": "python_import", "path": path, "module": module})

        markers = [str(x).strip() for x in (expected_text_markers or []) if str(x).strip()]
        if markers:
            text_targets = [
                path
                for path in inferred_files
                if Path(path).suffix.lower() in {".txt", ".md", ".log", ".csv", ".json"}
            ]
            if produced_files:
                text_targets = [path for path in text_targets if path in produced_files]
            if len(text_targets) == 1:
                target = text_targets[0]
                for marker in markers:
                    checks.append({"type": "text_in_file", "path": target, "contains": marker})

        # For fetch-first web-intel tasks, require script-generated markers
        # so "manual summary/meta writing" does not silently pass objective checks.
        is_web_intel_task = self._task_requires_web_intel_contract(task)
        if is_web_intel_task:
            lowered_task = (task or "").lower()
            has_meta = ("web_intel/meta.json" in inferred_files) or ("web_intel/meta.json" in lowered_task)
            has_summary = ("web_intel/summary.md" in inferred_files) or ("web_intel/summary.md" in lowered_task)
            if has_meta:
                checks.append(
                    {
                        "type": "json_key_equals",
                        "path": "web_intel/meta.json",
                        "key": "generated_by",
                        "value": "web_intel_fetch.py",
                    }
                )
                checks.append(
                    {
                        "type": "json_key_exists",
                        "path": "web_intel/meta.json",
                        "key": "timestamp",
                    }
                )
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
                item.get("key", ""),
                item.get("value", ""),
            )
            if sig in seen:
                continue
            seen.add(sig)
            uniq.append(item)
        return uniq

    def _infer_required_python_modules_from_task(self, task: str) -> list[str]:
        contract = self._task_contract_parser.parse(task=task, enforce_web_intel_contract=False)
        return [str(x).strip().lower() for x in contract.required_python_modules if str(x).strip()]

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
        contract = self._task_contract_parser.parse(
            task=task,
            enforce_web_intel_contract=self._task_requires_web_intel_contract(task),
        )
        return list(contract.required_outputs)

    def _infer_output_files_from_selected_skills(self, selected_skills: list[Any]) -> list[str]:
        rows: list[str] = []
        for skill in selected_skills:
            artifacts = getattr(skill, "success_artifacts", []) or []
            if not isinstance(artifacts, list):
                continue
            for raw in artifacts:
                candidate = str(raw or "").strip().replace("\\", "/")
                if not candidate:
                    continue
                if candidate.startswith(("/", "../")):
                    continue
                rows.append(candidate)
        seen: set[str] = set()
        uniq: list[str] = []
        for item in rows:
            if item in seen:
                continue
            seen.add(item)
            uniq.append(item)
        return uniq

    def _merge_required_outputs(self, left: list[str], right: list[str]) -> list[str]:
        rows = list(left or []) + list(right or [])
        seen: set[str] = set()
        uniq: list[str] = []
        for raw in rows:
            item = str(raw or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            uniq.append(item)
        return uniq

    def _infer_input_file_refs_from_task(self, text: str, candidates: list[str]) -> set[str]:
        lowered = (text or "").lower()
        output_intents = ("write", "create", "generate", "save", "บันทึก", "สร้าง", "เขียน")
        has_output_intent = any(k in lowered for k in output_intents)
        source_exts = {
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".png",
            ".jpg",
            ".jpeg",
            ".tif",
            ".tiff",
            ".gif",
            ".bmp",
        }

        source_refs: set[str] = set()
        for token in candidates:
            escaped = re.escape(token)
            quoted = rf"[\"'“”‘’]?\s*{escaped}\s*[\"'“”‘’]?"
            input_patterns = (
                rf"(?:from|read|use|using|input|source|extract(?:ed)?\s+from)\s+{quoted}",
                rf"(?:จาก|อ่าน|ใช้|อินพุต|ไฟล์ต้นฉบับ|จากไฟล์)\s*{quoted}",
            )
            if any(re.search(p, text, flags=re.IGNORECASE) for p in input_patterns):
                source_refs.add(token)
                continue

            if has_output_intent and Path(token).suffix.lower() in source_exts:
                source_refs.add(token)

        return source_refs

    def _should_require_non_empty_output(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in {".txt", ".md", ".json", ".csv", ".html", ".xml", ".yaml", ".yml", ".log"}

    def _looks_like_skill_script_input_ref(self, task: str, token: str) -> bool:
        lowered_token = (token or "").strip().lower().replace("\\", "/")
        if not lowered_token:
            return False
        if lowered_token.startswith(("skillpacks/", "examples/skills/", ".softnix_skill_exec/")):
            return True
        escaped = re.escape(token)
        if re.search(rf"(?:^|\s)python(?:3)?\s+{escaped}(?:\s|$)", task, flags=re.IGNORECASE):
            return True
        return False

    def _task_requires_web_intel_contract(self, task: str) -> bool:
        lowered = (task or "").lower()
        if not lowered:
            return False
        triggers = ("fetch-first", "web_fetch", "web-intel", "web_intel")
        if any(token in lowered for token in triggers):
            return True
        # If task explicitly asks to read these files, enforce contract as well.
        return ("web_intel/meta.json" in lowered) or ("web_intel/summary.md" in lowered)

    def _sanitize_task_and_materialize_secrets(self, task: str, workspace: Path) -> tuple[str, list[str]]:
        text = (task or "").strip()
        if not text:
            return text, []
        secret_map = self._extract_secrets_from_task_text(text)
        if not secret_map:
            return text, []

        secret_root = workspace.resolve() / ".secret"
        secret_root.mkdir(parents=True, exist_ok=True)
        redacted = text
        names: list[str] = []
        for key_name, secret_value in secret_map.items():
            (secret_root / key_name).write_text(f"{secret_value}\n", encoding="utf-8")
            redacted = redacted.replace(secret_value, f"<REDACTED:{key_name}>")
            names.append(key_name)

        guidance = [
            "",
            "[Security policy applied]",
            "Detected secret values in task were redacted and stored in workspace .secret files:",
        ]
        for key_name in names:
            guidance.append(f"- .secret/{key_name}")
        guidance.append("Do not hardcode secret values in generated code or output.")
        return redacted + "\n" + "\n".join(guidance), names

    def _extract_secrets_from_task_text(self, text: str) -> dict[str, str]:
        task = str(text or "")
        found: dict[str, str] = {}

        for m in re.finditer(
            r"\b(?P<name>[A-Z][A-Z0-9_]{2,64}(?:API_KEY|TOKEN|SECRET_KEY))\s*[:=]\s*[\"']?(?P<value>[^\s\"',}]+)",
            task,
        ):
            key_name = str(m.group("name") or "").strip().upper()
            key_value = str(m.group("value") or "").strip()
            if not self._looks_like_secret_value(key_value):
                continue
            found.setdefault(key_name, key_value)

        resend_key_match = re.search(r"resend\.api_key\s*=\s*[\"']([^\"']+)[\"']", task, flags=re.IGNORECASE)
        if resend_key_match:
            key_value = str(resend_key_match.group(1) or "").strip()
            if self._looks_like_secret_value(key_value):
                found.setdefault("RESEND_API_KEY", key_value)

        for key_name, pattern in self._SECRET_TOKEN_PATTERNS:
            for m in pattern.finditer(task):
                key_value = str(m.group(0) or "").strip()
                if self._looks_like_secret_value(key_value):
                    found.setdefault(key_name, key_value)

        return found

    def _looks_like_secret_value(self, value: str) -> bool:
        token = str(value or "").strip()
        if len(token) < 12:
            return False
        lowered = token.lower()
        if lowered in {"__set_me__", "your_api_key", "api_key_here", "changeme", "placeholder"}:
            return False
        if token.startswith("<") and token.endswith(">"):
            return False
        if any(ch.isspace() for ch in token):
            return False
        has_alpha = any(ch.isalpha() for ch in token)
        has_digit = any(ch.isdigit() for ch in token)
        has_sep = any(ch in {"_", "-", "."} for ch in token)
        return has_alpha and (has_digit or has_sep)

    def _looks_like_workspace_output_candidate(self, token: str) -> bool:
        value = (token or "").strip().lower()
        if not value:
            return False
        ext = Path(value).suffix.lower().lstrip(".")
        if not ext:
            return False
        # If the candidate has no directory component, require a known output-like extension.
        # This prevents domain/identifier tokens (e.g. gmail.com, resend.api_key) from
        # being treated as required output artifacts.
        if "/" not in value:
            return ext in self._COMMON_OUTPUT_EXTENSIONS
        return True

    def _resolve_validation_path(self, path_text: str, produced_files: set[str] | None) -> str:
        raw = (path_text or "").strip()
        if not raw:
            return ""
        if raw.startswith("./"):
            raw = raw[2:]
        if raw.startswith("/"):
            return raw
        if not produced_files:
            return raw
        if raw in produced_files:
            return raw

        normalized = raw.replace("\\", "/")
        if normalized in produced_files:
            return normalized

        suffix = f"/{normalized}"
        suffix_matches = sorted(path for path in produced_files if path.endswith(suffix))
        if len(suffix_matches) == 1:
            return suffix_matches[0]

        name = Path(normalized).name
        if not name:
            return raw
        name_matches = sorted(path for path in produced_files if Path(path).name == name)
        if len(name_matches) == 1:
            return name_matches[0]
        return raw

    def _is_within_root(self, path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False
