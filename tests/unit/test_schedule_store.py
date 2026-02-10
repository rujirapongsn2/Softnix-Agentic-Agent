from datetime import datetime, timezone
from pathlib import Path

from softnix_agentic_agent.storage.schedule_store import CronSpec, ScheduleStore, compute_next_run_at


def test_compute_next_run_at_one_time() -> None:
    next_run = compute_next_run_at(
        schedule_type="one_time",
        timezone_name="Asia/Bangkok",
        run_at="2026-02-10T09:00:00+07:00",
    )
    assert next_run == "2026-02-10T02:00:00+00:00"


def test_cron_spec_next_after() -> None:
    spec = CronSpec.parse("0 9 * * *")
    now = datetime(2026, 2, 10, 1, 10, tzinfo=timezone.utc)
    next_run = spec.next_after(now, "Asia/Bangkok")
    assert next_run == datetime(2026, 2, 10, 2, 0, tzinfo=timezone.utc)


def test_schedule_store_create_list_and_mark_dispatched(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "schedules")
    item = store.create_schedule(
        {
            "task": "daily summary",
            "schedule_type": "cron",
            "timezone": "Asia/Bangkok",
            "cron_expr": "0 9 * * *",
            "run_at": None,
            "next_run_at": "2026-02-10T02:00:00+00:00",
        }
    )
    all_items = store.list_schedules()
    assert len(all_items) == 1
    assert all_items[0]["id"] == item["id"]

    due = store.list_due_schedules(datetime(2026, 2, 10, 2, 0, tzinfo=timezone.utc))
    assert len(due) == 1

    updated = store.mark_dispatched(item["id"], datetime(2026, 2, 10, 2, 0, tzinfo=timezone.utc))
    assert updated["last_dispatched_at"] == "2026-02-10T02:00:00+00:00"
    assert updated["next_run_at"] == "2026-02-11T02:00:00+00:00"
