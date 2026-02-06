from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from softnix_agentic_agent.types import IterationRecord, RunState, utc_now_iso


class FilesystemStore:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)

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

    def resolve_artifact_path(self, run_id: str, artifact_path: str) -> Path:
        artifacts_dir = (self.run_dir(run_id) / "artifacts").resolve()
        target = (artifacts_dir / artifact_path).resolve()
        if not str(target).startswith(str(artifacts_dir)):
            raise ValueError("artifact path escapes artifacts directory")
        return target

    def log_event(self, run_id: str, message: str) -> None:
        p = self.run_dir(run_id) / "events.log"
        with p.open("a", encoding="utf-8") as f:
            f.write(f"{utc_now_iso()} {message}\n")

    def request_cancel(self, run_id: str) -> None:
        state = self.read_state(run_id)
        state.cancel_requested = True
        state.updated_at = utc_now_iso()
        self.write_state(state)
        self.log_event(run_id, "cancel requested")
