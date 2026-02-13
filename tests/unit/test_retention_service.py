from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from softnix_agentic_agent.storage.retention_service import RetentionConfig, RunRetentionService


def _write_run(
    runs_dir: Path,
    run_id: str,
    *,
    status: str,
    updated_at: datetime,
    artifact_text: str = "x",
) -> None:
    run_dir = runs_dir / run_id
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts" / "a.txt").write_text(artifact_text, encoding="utf-8")
    payload = {
        "run_id": run_id,
        "task": "t",
        "provider": "openai",
        "model": "m",
        "workspace": ".",
        "skills_dir": "skillpacks",
        "max_iters": 10,
        "iteration": 1,
        "status": status,
        "stop_reason": "completed" if status == "completed" else None,
        "created_at": updated_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "last_output": "",
        "cancel_requested": False,
    }
    (run_dir / "state.json").write_text(json.dumps(payload), encoding="utf-8")


def test_retention_report_keeps_running_and_marks_old_finished(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    now = datetime(2026, 2, 13, 12, 0, tzinfo=timezone.utc)

    _write_run(runs_dir, "old-done", status="completed", updated_at=now - timedelta(days=30), artifact_text="aaa")
    _write_run(runs_dir, "new-done", status="failed", updated_at=now - timedelta(days=2), artifact_text="bbb")
    _write_run(runs_dir, "active", status="running", updated_at=now - timedelta(days=40), artifact_text="ccc")

    service = RunRetentionService(
        runs_dir=runs_dir,
        config=RetentionConfig(enabled=True, keep_finished_days=14, max_runs=50, max_bytes=10_000_000),
    )
    report = service.report(now=now)

    planned_ids = report["planned_deletion_ids"]
    assert planned_ids == ["old-done"]
    assert report["summary"]["active_runs"] == 1
    assert report["summary"]["planned_delete_runs"] == 1


def test_retention_cleanup_applies_count_and_byte_caps(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    now = datetime(2026, 2, 13, 12, 0, tzinfo=timezone.utc)

    _write_run(runs_dir, "r1", status="completed", updated_at=now - timedelta(days=4), artifact_text="1" * 10)
    _write_run(runs_dir, "r2", status="completed", updated_at=now - timedelta(days=3), artifact_text="2" * 10)
    _write_run(runs_dir, "r3", status="completed", updated_at=now - timedelta(days=2), artifact_text="3" * 10)
    _write_run(runs_dir, "r4", status="running", updated_at=now - timedelta(days=1), artifact_text="4" * 10)

    service = RunRetentionService(
        runs_dir=runs_dir,
        config=RetentionConfig(enabled=True, keep_finished_days=365, max_runs=3, max_bytes=10_000_000),
    )
    dry = service.run_cleanup(dry_run=True, now=now)
    assert dry["status"] == "ok"
    assert set(dry["report"]["planned_deletion_ids"]) == {"r1"}
    assert (runs_dir / "r1").exists()
    assert (runs_dir / "r2").exists()

    actual = service.run_cleanup(dry_run=False, now=now)
    assert actual["status"] == "ok"
    assert set(actual["deleted_run_ids"]) == {"r1"}
    assert not (runs_dir / "r1").exists()
    assert (runs_dir / "r2").exists()
    assert (runs_dir / "r3").exists()
    assert (runs_dir / "r4").exists()


def test_retention_cleanup_skill_builds_and_experience(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    builds_dir = tmp_path / "skill-builds"
    experience_dir = tmp_path / "experience"
    now = datetime(2026, 2, 13, 12, 0, tzinfo=timezone.utc)

    _write_run(runs_dir, "active", status="running", updated_at=now - timedelta(days=1), artifact_text="a")

    old_build = builds_dir / "job-old"
    old_build.mkdir(parents=True, exist_ok=True)
    (old_build / "state.json").write_text(
        json.dumps(
            {
                "id": "job-old",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (old_build / "events.log").write_text("x\n", encoding="utf-8")

    active_build = builds_dir / "job-active"
    active_build.mkdir(parents=True, exist_ok=True)
    (active_build / "state.json").write_text(
        json.dumps(
            {
                "id": "job-active",
                "status": "running",
                "created_at": "2026-02-13T00:00:00+00:00",
                "updated_at": "2026-02-13T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    experience_dir.mkdir(parents=True, exist_ok=True)
    (experience_dir / "success_cases.jsonl").write_text(
        "\n".join(['{"i":1}', '{"i":2}', '{"i":3}', '{"i":4}', '{"i":5}']) + "\n",
        encoding="utf-8",
    )
    (experience_dir / "failure_cases.jsonl").write_text(
        "\n".join(['{"f":1}', '{"f":2}', '{"f":3}', '{"f":4}']) + "\n",
        encoding="utf-8",
    )
    (experience_dir / "strategy_outcomes.jsonl").write_text(
        "\n".join(['{"s":1}', '{"s":2}', '{"s":3}', '{"s":4}', '{"s":5}', '{"s":6}']) + "\n",
        encoding="utf-8",
    )

    service = RunRetentionService(
        runs_dir=runs_dir,
        skill_builds_dir=builds_dir,
        config=RetentionConfig(
            enabled=True,
            keep_finished_days=365,
            max_runs=100,
            max_bytes=1_000_000,
            skill_builds_keep_finished_days=14,
            skill_builds_max_jobs=50,
            skill_builds_max_bytes=1_000_000,
            experience_success_max_items=3,
            experience_failure_max_items=2,
            experience_strategy_max_items=4,
        ),
    )
    dry = service.run_cleanup(dry_run=True, now=now)
    assert dry["status"] == "ok"
    skill_ids = set(dry["report"]["skill_builds"]["planned_deletion_ids"])
    assert "job-old" in skill_ids
    assert "job-active" not in skill_ids
    assert len(dry["report"]["experience"]["planned_trims"]) == 3

    applied = service.run_cleanup(dry_run=False, now=now)
    assert "job-old" in applied["deleted_skill_build_ids"]
    assert (builds_dir / "job-active").exists()
    assert not (builds_dir / "job-old").exists()

    success_lines = (experience_dir / "success_cases.jsonl").read_text(encoding="utf-8").splitlines()
    failure_lines = (experience_dir / "failure_cases.jsonl").read_text(encoding="utf-8").splitlines()
    strategy_lines = (experience_dir / "strategy_outcomes.jsonl").read_text(encoding="utf-8").splitlines()
    assert len([x for x in success_lines if x.strip()]) == 3
    assert len([x for x in failure_lines if x.strip()]) == 2
    assert len([x for x in strategy_lines if x.strip()]) == 4
