from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from typing import Any

from softnix_agentic_agent.types import IterationRecord, RunState, utc_now_iso


class FilesystemStore:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.context_refs_dir = self.runs_dir.parent / "context_refs"
        self.context_refs_dir.mkdir(parents=True, exist_ok=True)
        self.experience_dir = self.runs_dir.parent / "experience"
        self.experience_dir.mkdir(parents=True, exist_ok=True)
        self.experience_file = self.experience_dir / "success_cases.jsonl"
        self.failure_experience_file = self.experience_dir / "failure_cases.jsonl"
        self.strategy_outcomes_file = self.experience_dir / "strategy_outcomes.jsonl"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def list_run_ids(self) -> list[str]:
        if not self.runs_dir.exists():
            return []
        ids = [p.name for p in self.runs_dir.iterdir() if p.is_dir() and (p / "state.json").exists()]
        return sorted(ids)

    def init_run(self, state: RunState) -> None:
        rd = self.run_dir(state.run_id)
        (rd / "artifacts").mkdir(parents=True, exist_ok=True)
        self.write_state(state)
        self.log_event(state.run_id, f"run initialized task={state.task!r}")

    def write_state(self, state: RunState) -> None:
        rd = self.run_dir(state.run_id)
        rd.mkdir(parents=True, exist_ok=True)
        p = rd / "state.json"
        with p.open("w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)

    def read_state(self, run_id: str) -> RunState:
        p = self.run_dir(run_id) / "state.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        return RunState.from_dict(data)

    def append_iteration(self, record: IterationRecord) -> None:
        p = self.run_dir(record.run_id) / "iterations.jsonl"
        with p.open("a", encoding="utf-8") as f:
            line = {
                "run_id": record.run_id,
                "iteration": record.iteration,
                "timestamp": record.timestamp,
                "prompt": record.prompt,
                "plan": record.plan,
                "actions": record.actions,
                "action_results": record.action_results,
                "output": record.output,
                "done": record.done,
                "error": record.error,
                "token_usage": record.token_usage,
            }
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def read_iterations(self, run_id: str) -> list[dict[str, Any]]:
        p = self.run_dir(run_id) / "iterations.jsonl"
        if not p.exists():
            return []
        rows = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def read_events(self, run_id: str) -> list[str]:
        p = self.run_dir(run_id) / "events.log"
        if not p.exists():
            return []
        return [line for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

    def list_artifacts(self, run_id: str) -> list[str]:
        artifacts_dir = self.run_dir(run_id) / "artifacts"
        if not artifacts_dir.exists():
            return []
        files = [str(p.relative_to(artifacts_dir)) for p in artifacts_dir.rglob("*") if p.is_file()]
        return sorted(files)

    def list_artifact_entries(self, run_id: str) -> list[dict[str, Any]]:
        artifacts_dir = self.run_dir(run_id) / "artifacts"
        if not artifacts_dir.exists():
            return []
        entries: list[dict[str, Any]] = []
        for path in artifacts_dir.rglob("*"):
            if not path.is_file():
                continue
            stat = path.stat()
            entries.append(
                {
                    "path": str(path.relative_to(artifacts_dir)),
                    "size": int(stat.st_size),
                    "modified_at": stat.st_mtime,
                }
            )
        entries.sort(key=lambda e: str(e["path"]))
        return entries

    def resolve_artifact_path(self, run_id: str, artifact_path: str) -> Path:
        artifacts_dir = (self.run_dir(run_id) / "artifacts").resolve()
        target = (artifacts_dir / artifact_path).resolve()
        if not _is_within(target, artifacts_dir):
            raise ValueError("artifact path escapes artifacts directory")
        return target

    def snapshot_workspace_file(self, run_id: str, workspace: Path, file_path: str) -> str:
        workspace_root = workspace.resolve()
        source = (workspace_root / file_path).resolve()
        if not _is_within(source, workspace_root):
            raise ValueError("workspace file path escapes workspace")
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"workspace file not found: {source}")

        rel = str(source.relative_to(workspace_root))
        dest = self.run_dir(run_id) / "artifacts" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        return rel

    def log_event(self, run_id: str, message: str) -> None:
        p = self.run_dir(run_id) / "events.log"
        with p.open("a", encoding="utf-8") as f:
            f.write(f"{utc_now_iso()} {message}\n")

    def append_memory_audit(self, run_id: str, payload: dict[str, Any]) -> None:
        p = self.run_dir(run_id) / "memory_audit.jsonl"
        line = {"ts": utc_now_iso(), **payload}
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def write_reference_context(self, channel: str, owner_id: str, payload: dict[str, Any]) -> None:
        p = self._context_ref_path(channel=channel, owner_id=owner_id)
        row = {"ts": utc_now_iso(), **(payload or {})}
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(row, f, indent=2, ensure_ascii=False)

    def read_reference_context(self, channel: str, owner_id: str) -> dict[str, Any]:
        p = self._context_ref_path(channel=channel, owner_id=owner_id)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _context_ref_path(self, channel: str, owner_id: str) -> Path:
        c = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(channel or "").strip()) or "default"
        o = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(owner_id or "").strip()) or "default"
        return self.context_refs_dir / f"{c}__{o}.json"

    def read_memory_audit(self, run_id: str) -> list[dict[str, Any]]:
        p = self.run_dir(run_id) / "memory_audit.jsonl"
        if not p.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        return rows

    def request_cancel(self, run_id: str) -> None:
        state = self.read_state(run_id)
        state.cancel_requested = True
        state.updated_at = utc_now_iso()
        self.write_state(state)
        self.log_event(run_id, "cancel requested")

    def append_success_experience(self, payload: dict[str, Any], max_items: int = 1000) -> None:
        line = {"ts": utc_now_iso(), **payload}
        with self.experience_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

        cap = max(10, int(max_items))
        rows = self.read_success_experiences(limit=cap + 50)
        if len(rows) <= cap:
            return
        kept = rows[-cap:]
        with self.experience_file.open("w", encoding="utf-8") as f:
            for row in kept:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def read_success_experiences(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.experience_file.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.experience_file.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        if limit <= 0:
            return rows
        return rows[-int(limit) :]

    def retrieve_success_experiences(
        self,
        task: str,
        selected_skills: list[str],
        top_k: int = 3,
        max_scan: int = 300,
        task_intent: str = "",
        min_quality_score: float = 0.55,
    ) -> list[dict[str, Any]]:
        if top_k <= 0:
            return []
        task_tokens = _experience_tokens(task)
        if not task_tokens:
            return []
        current_skills = {str(x).strip().lower() for x in selected_skills if str(x).strip()}
        rows = self.read_success_experiences(limit=max(10, int(max_scan)))
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            if str(row.get("status", "")).lower() not in {"completed", "success", "ok"}:
                continue
            if not _experience_quality_ok(row):
                continue
            row_quality = _experience_quality_score(row)
            if row_quality < float(min_quality_score):
                continue
            if not _experience_intent_compatible(row=row, task_intent=task_intent):
                continue
            past_tokens = {str(x).strip().lower() for x in row.get("task_tokens", []) if str(x).strip()}
            token_overlap = len(task_tokens.intersection(past_tokens))
            if token_overlap <= 0:
                continue
            past_skills = {str(x).strip().lower() for x in row.get("selected_skills", []) if str(x).strip()}
            skill_overlap = len(current_skills.intersection(past_skills)) if current_skills else 0
            intent_bonus = _experience_intent_bonus(row=row, task_intent=task_intent)
            score = token_overlap + (skill_overlap * 3) + intent_bonus + row_quality
            scored.append((score, row))
        scored.sort(key=lambda item: (item[0], str(item[1].get("ts", ""))), reverse=True)
        return [row for _, row in scored[: int(top_k)]]

    def append_failure_experience(self, payload: dict[str, Any], max_items: int = 1000) -> None:
        line = {"ts": utc_now_iso(), **payload}
        with self.failure_experience_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

        cap = max(10, int(max_items))
        rows = self.read_failure_experiences(limit=cap + 50)
        if len(rows) <= cap:
            return
        kept = rows[-cap:]
        with self.failure_experience_file.open("w", encoding="utf-8") as f:
            for row in kept:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def read_failure_experiences(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.failure_experience_file.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.failure_experience_file.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        if limit <= 0:
            return rows
        return rows[-int(limit) :]

    def retrieve_failure_experiences(
        self,
        task: str,
        selected_skills: list[str],
        top_k: int = 2,
        max_scan: int = 300,
        task_intent: str = "",
    ) -> list[dict[str, Any]]:
        if top_k <= 0:
            return []
        task_tokens = _experience_tokens(task)
        if not task_tokens:
            return []
        current_skills = {str(x).strip().lower() for x in selected_skills if str(x).strip()}
        rows = self.read_failure_experiences(limit=max(10, int(max_scan)))
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            if str(row.get("status", "")).lower() not in {"failed", "error"}:
                continue
            if not _experience_intent_compatible(row=row, task_intent=task_intent):
                continue
            past_tokens = {str(x).strip().lower() for x in row.get("task_tokens", []) if str(x).strip()}
            token_overlap = len(task_tokens.intersection(past_tokens))
            if token_overlap <= 0:
                continue
            past_skills = {str(x).strip().lower() for x in row.get("selected_skills", []) if str(x).strip()}
            skill_overlap = len(current_skills.intersection(past_skills)) if current_skills else 0
            has_strategy = 1 if str(row.get("recommended_strategy", "")).strip() else 0
            strategy_key = str(row.get("strategy_key", "")).strip()
            strategy_score = self.get_strategy_effectiveness_score(strategy_key) if strategy_key else 0.0
            intent_bonus = _experience_intent_bonus(row=row, task_intent=task_intent)
            score = token_overlap + (skill_overlap * 2) + (has_strategy * 2) + strategy_score + intent_bonus
            scored.append((score, row))
        scored.sort(key=lambda item: (item[0], str(item[1].get("ts", ""))), reverse=True)
        return [row for _, row in scored[: int(top_k)]]

    def append_strategy_outcome(
        self,
        *,
        strategy_key: str,
        success: bool,
        failure_class: str = "",
        run_id: str = "",
        max_items: int = 4000,
    ) -> None:
        key = str(strategy_key).strip()
        if not key:
            return
        line = {
            "ts": utc_now_iso(),
            "strategy_key": key,
            "success": bool(success),
            "failure_class": str(failure_class).strip(),
            "run_id": str(run_id).strip(),
        }
        with self.strategy_outcomes_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

        cap = max(50, int(max_items))
        rows = self.read_strategy_outcomes(limit=cap + 100)
        if len(rows) <= cap:
            return
        kept = rows[-cap:]
        with self.strategy_outcomes_file.open("w", encoding="utf-8") as f:
            for row in kept:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def read_strategy_outcomes(self, limit: int = 1000) -> list[dict[str, Any]]:
        if not self.strategy_outcomes_file.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.strategy_outcomes_file.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        if limit <= 0:
            return rows
        return rows[-int(limit) :]

    def get_strategy_effectiveness_score(self, strategy_key: str, max_scan: int = 1200) -> float:
        key = str(strategy_key).strip()
        if not key:
            return 0.0
        rows = self.read_strategy_outcomes(limit=max_scan)
        wins = 0
        losses = 0
        for row in rows:
            if str(row.get("strategy_key", "")).strip() != key:
                continue
            if bool(row.get("success", False)):
                wins += 1
            else:
                losses += 1
        total = wins + losses
        if total <= 0:
            return 0.0
        win_rate = wins / total
        confidence = min(1.0, total / 8.0)
        # normalized around 0; positive means historically effective.
        return (win_rate - 0.5) * 6.0 * confidence


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _experience_tokens(text: str) -> set[str]:
    raw = re.findall(r"[a-z0-9ก-๙_-]+", (text or "").lower())
    out: set[str] = set()
    for token in raw:
        item = token.strip()
        if len(item) < 2:
            continue
        out.add(item)
    return out


def _experience_quality_ok(row: dict[str, Any]) -> bool:
    produced_files = [str(x).strip() for x in row.get("produced_files", []) if str(x).strip()]
    action_sequence = [str(x).strip() for x in row.get("action_sequence", []) if str(x).strip()]
    if produced_files:
        return True
    if not action_sequence:
        return False
    preparatory_only = {"list_dir", "read_file"}
    if all(action in preparatory_only for action in action_sequence):
        return False
    return True


def _experience_quality_score(row: dict[str, Any]) -> float:
    raw = row.get("quality_score")
    try:
        value = float(raw)
        if value < 0:
            return 0.0
        if value > 1:
            return 1.0
        return value
    except Exception:
        # Backward compatibility for legacy rows without quality_score.
        return 0.6


def _experience_intent_compatible(row: dict[str, Any], task_intent: str) -> bool:
    intent = str(task_intent or "").strip().lower()
    if not intent:
        return True
    row_intent = str(row.get("task_intent", "")).strip().lower()
    if not row_intent:
        return True
    return row_intent == intent


def _experience_intent_bonus(row: dict[str, Any], task_intent: str) -> float:
    intent = str(task_intent or "").strip().lower()
    if not intent:
        return 0.0
    row_intent = str(row.get("task_intent", "")).strip().lower()
    if not row_intent:
        return 0.0
    return 4.0 if row_intent == intent else -4.0
