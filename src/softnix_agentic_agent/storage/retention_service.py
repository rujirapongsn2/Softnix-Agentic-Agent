from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import threading
from typing import Any

from softnix_agentic_agent.types import RunStatus


@dataclass
class RetentionConfig:
    enabled: bool = False
    interval_sec: float = 300.0
    keep_finished_days: int = 14
    max_runs: int = 500
    max_bytes: int = 2 * 1024 * 1024 * 1024
    skill_builds_keep_finished_days: int = 14
    skill_builds_max_jobs: int = 300
    skill_builds_max_bytes: int = 1 * 1024 * 1024 * 1024
    experience_success_max_items: int = 1000
    experience_failure_max_items: int = 1000
    experience_strategy_max_items: int = 4000


class RunRetentionService:
    def __init__(
        self,
        runs_dir: Path,
        config: RetentionConfig,
        *,
        skill_builds_dir: Path | None = None,
    ) -> None:
        self.runs_dir = runs_dir
        self.config = config
        self.skill_builds_dir = skill_builds_dir
        self.experience_dir = self.runs_dir.parent / "experience"
        self._lock = threading.Lock()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.experience_dir.mkdir(parents=True, exist_ok=True)
        if self.skill_builds_dir is not None:
            self.skill_builds_dir.mkdir(parents=True, exist_ok=True)

    def report(self, now: datetime | None = None) -> dict[str, Any]:
        now_utc = now or datetime.now(timezone.utc)
        runs_items = self._collect_run_items(now_utc)
        runs_selected = self._select_run_deletions(runs_items, now_utc)
        runs_selected_ids = {str(row["run_id"]) for row in runs_selected}
        runs_total_bytes = sum(int(row["size_bytes"]) for row in runs_items)
        runs_reclaimable_bytes = sum(int(row["size_bytes"]) for row in runs_selected)
        runs_remaining = len(runs_items) - len(runs_selected)
        runs_remaining_bytes = runs_total_bytes - runs_reclaimable_bytes

        skill_items = self._collect_skill_build_items(now_utc)
        skill_selected = self._select_skill_build_deletions(skill_items, now_utc)
        skill_selected_ids = {str(row["job_id"]) for row in skill_selected}
        skill_total_bytes = sum(int(row["size_bytes"]) for row in skill_items)
        skill_reclaimable_bytes = sum(int(row["size_bytes"]) for row in skill_selected)
        skill_remaining = len(skill_items) - len(skill_selected)
        skill_remaining_bytes = skill_total_bytes - skill_reclaimable_bytes

        experience_report = self._build_experience_report()

        total_reclaimable = (
            runs_reclaimable_bytes
            + skill_reclaimable_bytes
            + int(experience_report["summary"]["planned_reclaim_bytes"])
        )
        planned_delete_units = len(runs_selected) + len(skill_selected) + int(
            experience_report["summary"]["planned_trim_files"]
        )
        return {
            "policy": {
                "enabled": self.config.enabled,
                "interval_sec": float(self.config.interval_sec),
                "keep_finished_days": int(self.config.keep_finished_days),
                "max_runs": int(self.config.max_runs),
                "max_bytes": int(self.config.max_bytes),
                "skill_builds_keep_finished_days": int(self.config.skill_builds_keep_finished_days),
                "skill_builds_max_jobs": int(self.config.skill_builds_max_jobs),
                "skill_builds_max_bytes": int(self.config.skill_builds_max_bytes),
                "experience_success_max_items": int(self.config.experience_success_max_items),
                "experience_failure_max_items": int(self.config.experience_failure_max_items),
                "experience_strategy_max_items": int(self.config.experience_strategy_max_items),
            },
            "summary": {
                "total_runs": len(runs_items),
                "total_bytes": runs_total_bytes,
                "active_runs": sum(1 for row in runs_items if str(row["status"]) == RunStatus.RUNNING.value),
                "finished_runs": sum(1 for row in runs_items if bool(row["finished"])),
                "planned_delete_runs": len(runs_selected),
                "planned_reclaim_bytes": runs_reclaimable_bytes,
                "remaining_runs_after_cleanup": runs_remaining,
                "remaining_bytes_after_cleanup": runs_remaining_bytes,
            },
            "items": runs_items,
            "planned_deletions": runs_selected,
            "planned_deletion_ids": sorted(runs_selected_ids),
            "skill_builds": {
                "summary": {
                    "total_jobs": len(skill_items),
                    "total_bytes": skill_total_bytes,
                    "active_jobs": sum(1 for row in skill_items if str(row["status"]) in {"queued", "running"}),
                    "finished_jobs": sum(1 for row in skill_items if bool(row["finished"])),
                    "planned_delete_jobs": len(skill_selected),
                    "planned_reclaim_bytes": skill_reclaimable_bytes,
                    "remaining_jobs_after_cleanup": skill_remaining,
                    "remaining_bytes_after_cleanup": skill_remaining_bytes,
                },
                "items": skill_items,
                "planned_deletions": skill_selected,
                "planned_deletion_ids": sorted(skill_selected_ids),
            },
            "experience": experience_report,
            "overall": {
                "planned_delete_units": planned_delete_units,
                "planned_reclaim_bytes": total_reclaimable,
            },
        }

    def run_cleanup(self, *, dry_run: bool = True, now: datetime | None = None) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            return {"status": "busy", "dry_run": dry_run}
        try:
            payload = self.report(now=now)
            planned_runs = payload.get("planned_deletions", [])
            planned_skill_builds = payload.get("skill_builds", {}).get("planned_deletions", [])
            planned_experience = payload.get("experience", {}).get("planned_trims", [])
            deleted: list[str] = []
            deleted_skill_build_ids: list[str] = []
            trimmed_experience_files: list[dict[str, Any]] = []
            deleted_bytes = 0
            errors: list[dict[str, str]] = []
            if not dry_run:
                for row in planned_runs:
                    run_id = str(row.get("run_id", "")).strip()
                    if not run_id:
                        continue
                    target = self.runs_dir / run_id
                    try:
                        if target.exists() and target.is_dir():
                            size_bytes = int(row.get("size_bytes", 0))
                            shutil.rmtree(target)
                            deleted.append(run_id)
                            deleted_bytes += max(0, size_bytes)
                    except Exception as exc:  # pragma: no cover
                        errors.append({"run_id": run_id, "error": str(exc)})
                for row in planned_skill_builds:
                    job_id = str(row.get("job_id", "")).strip()
                    if not job_id or self.skill_builds_dir is None:
                        continue
                    target = self.skill_builds_dir / job_id
                    try:
                        if target.exists() and target.is_dir():
                            size_bytes = int(row.get("size_bytes", 0))
                            shutil.rmtree(target)
                            deleted_skill_build_ids.append(job_id)
                            deleted_bytes += max(0, size_bytes)
                    except Exception as exc:  # pragma: no cover
                        errors.append({"job_id": job_id, "error": str(exc)})
                for row in planned_experience:
                    rel_path = str(row.get("path", "")).strip()
                    if not rel_path:
                        continue
                    file_path = self.experience_dir / rel_path
                    max_items = int(row.get("max_items", 0))
                    try:
                        trimmed = self._trim_jsonl_file(file_path, max_items=max_items)
                        if trimmed > 0:
                            trimmed_experience_files.append(
                                {"path": rel_path, "trimmed_lines": trimmed}
                            )
                            deleted_bytes += int(row.get("planned_reclaim_bytes", 0))
                    except Exception as exc:  # pragma: no cover
                        errors.append({"path": rel_path, "error": str(exc)})
            return {
                "status": "ok",
                "dry_run": dry_run,
                "report": payload,
                "deleted_run_ids": deleted,
                "deleted_skill_build_ids": deleted_skill_build_ids,
                "trimmed_experience_files": trimmed_experience_files,
                "deleted_bytes": deleted_bytes,
                "errors": errors,
            }
        finally:
            self._lock.release()

    def _collect_run_items(self, now: datetime) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not self.runs_dir.exists():
            return items

        for run_path in sorted(self.runs_dir.iterdir(), key=lambda p: p.name):
            if not run_path.is_dir():
                continue
            state_path = run_path / "state.json"
            if not state_path.exists():
                continue
            state = self._read_state_safe(state_path)
            if state is None:
                continue
            status = str(state.get("status", "")).strip().lower()
            updated_at_raw = str(state.get("updated_at", "")).strip()
            created_at_raw = str(state.get("created_at", "")).strip()
            updated_at = _parse_iso_datetime(updated_at_raw) or _parse_iso_datetime(created_at_raw)
            if updated_at is None:
                updated_at = datetime.fromtimestamp(run_path.stat().st_mtime, tz=timezone.utc)
            age_days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
            size_bytes = _dir_size_bytes(run_path)
            finished = status in {
                RunStatus.COMPLETED.value,
                RunStatus.FAILED.value,
                RunStatus.CANCELED.value,
            }
            items.append(
                {
                    "run_id": run_path.name,
                    "status": status or RunStatus.RUNNING.value,
                    "finished": finished,
                    "updated_at": updated_at.isoformat(),
                    "age_days": round(age_days, 3),
                    "size_bytes": size_bytes,
                    "path": str(run_path),
                }
            )

        items.sort(key=lambda row: str(row["updated_at"]))
        return items

    def _select_run_deletions(self, items: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
        if not items:
            return []

        candidates = [row for row in items if bool(row.get("finished"))]
        if not candidates:
            return []

        keep_days = max(0, int(self.config.keep_finished_days))
        cutoff = now - timedelta(days=keep_days)

        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()

        # Rule 1: age-based cleanup for finished runs.
        for row in candidates:
            updated_at = _parse_iso_datetime(str(row.get("updated_at", "")))
            if updated_at is None:
                continue
            if updated_at <= cutoff:
                run_id = str(row["run_id"])
                selected.append(row)
                selected_ids.add(run_id)

        # Rule 2: total run count cap (protect running runs).
        max_runs = max(1, int(self.config.max_runs))
        remaining_count = len(items) - len(selected)
        if remaining_count > max_runs:
            needed = remaining_count - max_runs
            for row in candidates:
                run_id = str(row["run_id"])
                if run_id in selected_ids:
                    continue
                selected.append(row)
                selected_ids.add(run_id)
                needed -= 1
                if needed <= 0:
                    break

        # Rule 3: bytes cap, delete oldest finished runs until under threshold.
        max_bytes = max(0, int(self.config.max_bytes))
        remaining_bytes = sum(int(row["size_bytes"]) for row in items if str(row["run_id"]) not in selected_ids)
        if max_bytes > 0 and remaining_bytes > max_bytes:
            for row in candidates:
                run_id = str(row["run_id"])
                if run_id in selected_ids:
                    continue
                selected.append(row)
                selected_ids.add(run_id)
                remaining_bytes -= int(row["size_bytes"])
                if remaining_bytes <= max_bytes:
                    break

        selected.sort(key=lambda row: str(row["updated_at"]))
        return selected

    def _collect_skill_build_items(self, now: datetime) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if self.skill_builds_dir is None or not self.skill_builds_dir.exists():
            return items

        for job_dir in sorted(self.skill_builds_dir.iterdir(), key=lambda p: p.name):
            if not job_dir.is_dir():
                continue
            state_path = job_dir / "state.json"
            if not state_path.exists():
                continue
            state = self._read_state_safe(state_path)
            if state is None:
                continue
            status = str(state.get("status", "")).strip().lower()
            updated_at_raw = str(state.get("updated_at", "")).strip()
            created_at_raw = str(state.get("created_at", "")).strip()
            updated_at = _parse_iso_datetime(updated_at_raw) or _parse_iso_datetime(created_at_raw)
            if updated_at is None:
                updated_at = datetime.fromtimestamp(job_dir.stat().st_mtime, tz=timezone.utc)
            age_days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
            size_bytes = _dir_size_bytes(job_dir)
            finished = status in {"completed", "failed"}
            items.append(
                {
                    "job_id": job_dir.name,
                    "status": status or "queued",
                    "finished": finished,
                    "updated_at": updated_at.isoformat(),
                    "age_days": round(age_days, 3),
                    "size_bytes": size_bytes,
                    "path": str(job_dir),
                }
            )
        items.sort(key=lambda row: str(row["updated_at"]))
        return items

    def _select_skill_build_deletions(self, items: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
        if not items:
            return []
        candidates = [row for row in items if bool(row.get("finished"))]
        if not candidates:
            return []

        keep_days = max(0, int(self.config.skill_builds_keep_finished_days))
        cutoff = now - timedelta(days=keep_days)
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()

        for row in candidates:
            updated_at = _parse_iso_datetime(str(row.get("updated_at", "")))
            if updated_at is None:
                continue
            if updated_at <= cutoff:
                job_id = str(row["job_id"])
                selected.append(row)
                selected_ids.add(job_id)

        max_jobs = max(1, int(self.config.skill_builds_max_jobs))
        remaining_count = len(items) - len(selected)
        if remaining_count > max_jobs:
            needed = remaining_count - max_jobs
            for row in candidates:
                job_id = str(row["job_id"])
                if job_id in selected_ids:
                    continue
                selected.append(row)
                selected_ids.add(job_id)
                needed -= 1
                if needed <= 0:
                    break

        max_bytes = max(0, int(self.config.skill_builds_max_bytes))
        remaining_bytes = sum(int(row["size_bytes"]) for row in items if str(row["job_id"]) not in selected_ids)
        if max_bytes > 0 and remaining_bytes > max_bytes:
            for row in candidates:
                job_id = str(row["job_id"])
                if job_id in selected_ids:
                    continue
                selected.append(row)
                selected_ids.add(job_id)
                remaining_bytes -= int(row["size_bytes"])
                if remaining_bytes <= max_bytes:
                    break

        selected.sort(key=lambda row: str(row["updated_at"]))
        return selected

    def _build_experience_report(self) -> dict[str, Any]:
        files = [
            ("success_cases.jsonl", int(self.config.experience_success_max_items)),
            ("failure_cases.jsonl", int(self.config.experience_failure_max_items)),
            ("strategy_outcomes.jsonl", int(self.config.experience_strategy_max_items)),
        ]
        items: list[dict[str, Any]] = []
        planned_trims: list[dict[str, Any]] = []
        reclaim_bytes = 0
        for rel_path, max_items in files:
            path = self.experience_dir / rel_path
            line_count, size_bytes = _jsonl_stats(path)
            over_limit = max(0, line_count - max(1, max_items))
            avg_line_bytes = int(size_bytes / max(1, line_count)) if line_count > 0 else 0
            planned_reclaim = over_limit * avg_line_bytes
            entry = {
                "path": rel_path,
                "max_items": max(1, max_items),
                "line_count": line_count,
                "size_bytes": size_bytes,
                "over_limit": over_limit,
                "planned_reclaim_bytes": planned_reclaim,
            }
            items.append(entry)
            if over_limit > 0:
                planned_trims.append(entry)
                reclaim_bytes += planned_reclaim
        return {
            "summary": {
                "tracked_files": len(items),
                "planned_trim_files": len(planned_trims),
                "planned_reclaim_bytes": reclaim_bytes,
            },
            "items": items,
            "planned_trims": planned_trims,
        }

    def _trim_jsonl_file(self, path: Path, *, max_items: int) -> int:
        if not path.exists():
            return 0
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        cap = max(1, int(max_items))
        if len(lines) <= cap:
            return 0
        kept = lines[-cap:]
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        return len(lines) - len(kept)

    def _read_state_safe(self, state_path: Path) -> dict[str, Any] | None:
        try:
            raw = state_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            return None
        except Exception:
            return None


def _parse_iso_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for node in path.rglob("*"):
            if node.is_file():
                total += node.stat().st_size
    except Exception:
        return total
    return total


def _jsonl_stats(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return 0, 0
    lines = [line for line in raw.splitlines() if line.strip()]
    return len(lines), path.stat().st_size if path.exists() else 0
