from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from softnix_agentic_agent.types import utc_now_iso


class SkillBuildStore:
    def __init__(self, builds_dir: Path) -> None:
        self.builds_dir = builds_dir
        self.builds_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def build_dir(self, job_id: str) -> Path:
        return self.builds_dir / job_id

    def state_path(self, job_id: str) -> Path:
        return self.build_dir(job_id) / "state.json"

    def events_path(self, job_id: str) -> Path:
        return self.build_dir(job_id) / "events.log"

    def staging_dir(self, job_id: str) -> Path:
        return self.build_dir(job_id) / "staging"

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            job_id = uuid.uuid4().hex[:12]
            now = utc_now_iso()
            item = {
                "id": job_id,
                "task": str(payload.get("task", "")),
                "skill_name": str(payload.get("skill_name", "")),
                "status": "queued",
                "stage": "queued",
                "install_on_success": bool(payload.get("install_on_success", True)),
                "allow_overwrite": bool(payload.get("allow_overwrite", False)),
                "api_key_name": str(payload.get("api_key_name", "")),
                "api_key_provided": bool(payload.get("api_key_provided", False)),
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
                "error": None,
                "validation": None,
                "installed_path": None,
            }
            build_dir = self.build_dir(job_id)
            build_dir.mkdir(parents=True, exist_ok=True)
            self.state_path(job_id).write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
            self.events_path(job_id).write_text("", encoding="utf-8")
            return item

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self.state_path(job_id)
        if not path.exists():
            raise FileNotFoundError(job_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            item = self.get_job(job_id)
            for key, value in updates.items():
                item[key] = value
            item["updated_at"] = utc_now_iso()
            if item.get("status") in {"completed", "failed"} and not item.get("completed_at"):
                item["completed_at"] = item["updated_at"]
            self.state_path(job_id).write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
            return item

    def append_event(self, job_id: str, message: str) -> None:
        path = self.events_path(job_id)
        line = f"{utc_now_iso()} {message}\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)

    def read_events(self, job_id: str) -> list[str]:
        path = self.events_path(job_id)
        if not path.exists():
            return []
        return [line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.builds_dir.glob("*/state.json")):
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        rows.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
        return rows[: max(1, int(limit))]
