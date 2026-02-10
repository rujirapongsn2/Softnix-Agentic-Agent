from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from softnix_agentic_agent.types import utc_now_iso


def _parse_iso_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _cron_weekday(dt: datetime) -> int:
    # Python: Monday=0..Sunday=6 -> Cron: Sunday=0..Saturday=6
    return (dt.weekday() + 1) % 7


def _expand_cron_field(raw: str, min_value: int, max_value: int) -> set[int]:
    values: set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue

        step = 1
        if "/" in token:
            token, step_raw = token.split("/", 1)
            step = int(step_raw.strip())
            if step <= 0:
                raise ValueError("cron step must be > 0")

        if token == "*":
            start, end = min_value, max_value
        elif "-" in token:
            start_raw, end_raw = token.split("-", 1)
            start = int(start_raw.strip())
            end = int(end_raw.strip())
        else:
            single = int(token.strip())
            start, end = single, single

        if start < min_value or end > max_value or start > end:
            raise ValueError("cron field value out of range")
        values.update(range(start, end + 1, step))

    if not values:
        raise ValueError("empty cron field")
    return values


@dataclass
class CronSpec:
    minute: set[int]
    hour: set[int]
    day_of_month: set[int]
    month: set[int]
    day_of_week: set[int]
    dom_any: bool
    dow_any: bool

    @classmethod
    def parse(cls, expr: str) -> "CronSpec":
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError("cron expression must have 5 fields")
        minute_raw, hour_raw, dom_raw, month_raw, dow_raw = parts
        return cls(
            minute=_expand_cron_field(minute_raw, 0, 59),
            hour=_expand_cron_field(hour_raw, 0, 23),
            day_of_month=_expand_cron_field(dom_raw, 1, 31),
            month=_expand_cron_field(month_raw, 1, 12),
            day_of_week=_expand_cron_field(dow_raw, 0, 6),
            dom_any=dom_raw.strip() == "*",
            dow_any=dow_raw.strip() == "*",
        )

    def matches(self, dt: datetime) -> bool:
        if dt.minute not in self.minute or dt.hour not in self.hour:
            return False
        if dt.month not in self.month:
            return False

        dom_match = dt.day in self.day_of_month
        dow_match = _cron_weekday(dt) in self.day_of_week
        if self.dom_any and self.dow_any:
            day_match = True
        elif self.dom_any:
            day_match = dow_match
        elif self.dow_any:
            day_match = dom_match
        else:
            day_match = dom_match or dow_match
        return day_match

    def next_after(self, now: datetime, tz_name: str) -> datetime:
        tz = ZoneInfo(tz_name)
        cursor = now.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
        max_steps = 60 * 24 * 366
        for _ in range(max_steps):
            if self.matches(cursor):
                return cursor.astimezone(timezone.utc)
            cursor += timedelta(minutes=1)
        raise ValueError("unable to compute next cron run within one year")


def compute_next_run_at(
    schedule_type: str,
    timezone_name: str,
    run_at: str | None = None,
    cron_expr: str | None = None,
    now_utc: datetime | None = None,
) -> str | None:
    now = now_utc or datetime.now(timezone.utc)
    if schedule_type == "one_time":
        if not run_at:
            raise ValueError("run_at is required for one_time schedule")
        dt = _parse_iso_datetime(run_at).astimezone(timezone.utc)
        return dt.isoformat()
    if schedule_type == "cron":
        if not cron_expr:
            raise ValueError("cron_expr is required for cron schedule")
        spec = CronSpec.parse(cron_expr)
        return spec.next_after(now, timezone_name).isoformat()
    raise ValueError("schedule_type must be one_time or cron")


class ScheduleStore:
    def __init__(self, schedules_dir: Path) -> None:
        self.schedules_dir = schedules_dir
        self.schedules_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _schedule_path(self, schedule_id: str) -> Path:
        return self.schedules_dir / f"{schedule_id}.json"

    def _runs_path(self, schedule_id: str) -> Path:
        return self.schedules_dir / f"{schedule_id}.runs.jsonl"

    def create_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            schedule_id = uuid.uuid4().hex[:12]
            now_iso = utc_now_iso()
            item = {
                "id": schedule_id,
                "task": str(payload["task"]),
                "schedule_type": str(payload["schedule_type"]),
                "timezone": str(payload["timezone"]),
                "run_at": payload.get("run_at"),
                "cron_expr": payload.get("cron_expr"),
                "enabled": bool(payload.get("enabled", True)),
                "next_run_at": payload.get("next_run_at"),
                "owner_type": str(payload.get("owner_type", "system")),
                "owner_id": str(payload.get("owner_id", "default")),
                "delivery_channel": str(payload.get("delivery_channel", "web_ui")),
                "delivery_target": payload.get("delivery_target"),
                "created_at": now_iso,
                "updated_at": now_iso,
                "last_dispatched_at": None,
                "deleted_at": None,
            }
            self._schedule_path(schedule_id).write_text(
                json.dumps(item, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return item

    def list_schedules(self, include_disabled: bool = True) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.schedules_dir.glob("*.json")):
            if path.name.endswith(".runs.json"):
                continue
            if path.name.endswith(".runs.jsonl"):
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not include_disabled and not bool(item.get("enabled", True)):
                continue
            if item.get("deleted_at"):
                continue
            items.append(item)
        items.sort(key=lambda x: (x.get("updated_at", ""), x.get("created_at", "")), reverse=True)
        return items

    def get_schedule(self, schedule_id: str) -> dict[str, Any]:
        path = self._schedule_path(schedule_id)
        if not path.exists():
            raise FileNotFoundError(schedule_id)
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("deleted_at"):
            raise FileNotFoundError(schedule_id)
        return item

    def update_schedule(self, schedule_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            item = self.get_schedule(schedule_id)
            for key, value in updates.items():
                item[key] = value
            item["updated_at"] = utc_now_iso()
            self._schedule_path(schedule_id).write_text(
                json.dumps(item, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return item

    def delete_schedule(self, schedule_id: str) -> dict[str, Any]:
        with self._lock:
            item = self.get_schedule(schedule_id)
            item["enabled"] = False
            item["deleted_at"] = utc_now_iso()
            item["updated_at"] = item["deleted_at"]
            self._schedule_path(schedule_id).write_text(
                json.dumps(item, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return item

    def list_due_schedules(self, now_utc: datetime, limit: int = 20) -> list[dict[str, Any]]:
        due: list[dict[str, Any]] = []
        for item in self.list_schedules(include_disabled=False):
            next_run_at = item.get("next_run_at")
            if not next_run_at:
                continue
            try:
                due_time = _parse_iso_datetime(next_run_at).astimezone(timezone.utc)
            except Exception:
                continue
            if due_time <= now_utc:
                due.append(item)
            if len(due) >= limit:
                break
        return due

    def mark_dispatched(self, schedule_id: str, now_utc: datetime) -> dict[str, Any]:
        with self._lock:
            item = self.get_schedule(schedule_id)
            now_iso = now_utc.astimezone(timezone.utc).isoformat()
            item["last_dispatched_at"] = now_iso
            if item["schedule_type"] == "one_time":
                item["enabled"] = False
                item["next_run_at"] = None
            else:
                next_run_at = compute_next_run_at(
                    schedule_type="cron",
                    timezone_name=item["timezone"],
                    cron_expr=item.get("cron_expr"),
                    now_utc=now_utc,
                )
                item["next_run_at"] = next_run_at
            item["updated_at"] = utc_now_iso()
            self._schedule_path(schedule_id).write_text(
                json.dumps(item, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return item

    def append_schedule_run(self, schedule_id: str, run_id: str, status: str = "queued") -> dict[str, Any]:
        row = {
            "id": uuid.uuid4().hex[:12],
            "schedule_id": schedule_id,
            "run_id": run_id,
            "status": status,
            "created_at": utc_now_iso(),
        }
        path = self._runs_path(schedule_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def read_schedule_runs(self, schedule_id: str, limit: int = 100) -> list[dict[str, Any]]:
        path = self._runs_path(schedule_id)
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except Exception:
                continue
        rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return rows[:limit]
