from pathlib import Path

from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.types import IterationRecord, RunState, RunStatus, utc_now_iso


def test_store_write_and_resume(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path)
    state = RunState(
        run_id="abc123",
        task="t",
        provider="openai",
        model="m",
        workspace=str(tmp_path),
        skills_dir=str(tmp_path),
        max_iters=3,
    )
    store.init_run(state)

    loaded = store.read_state("abc123")
    assert loaded.task == "t"

    rec = IterationRecord(
        run_id="abc123",
        iteration=1,
        timestamp=utc_now_iso(),
        prompt="p",
        plan={"done": False},
        actions=[],
        action_results=[],
        output="o",
        done=False,
    )
    store.append_iteration(rec)
    items = store.read_iterations("abc123")
    assert len(items) == 1

    store.request_cancel("abc123")
    canceled = store.read_state("abc123")
    assert canceled.cancel_requested is True


def test_state_roundtrip_enum(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path)
    state = RunState(
        run_id="r2",
        task="t2",
        provider="openai",
        model="m",
        workspace=str(tmp_path),
        skills_dir=str(tmp_path),
        max_iters=1,
        status=RunStatus.COMPLETED,
    )
    store.init_run(state)
    loaded = store.read_state("r2")
    assert loaded.status == RunStatus.COMPLETED


def test_snapshot_workspace_file(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True, exist_ok=True)
    created = workspace / "sub" / "demo.txt"
    created.parent.mkdir(parents=True, exist_ok=True)
    created.write_text("hello", encoding="utf-8")

    store = FilesystemStore(tmp_path / "runs")
    state = RunState(
        run_id="r3",
        task="t3",
        provider="openai",
        model="m",
        workspace=str(workspace),
        skills_dir=str(workspace),
        max_iters=1,
    )
    store.init_run(state)

    rel = store.snapshot_workspace_file("r3", workspace, "sub/demo.txt")
    assert rel == "sub/demo.txt"
    assert "sub/demo.txt" in store.list_artifacts("r3")


def test_snapshot_workspace_file_rejects_prefix_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    outside = tmp_path / "ws2"
    workspace.mkdir(parents=True, exist_ok=True)
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "secret.txt").write_text("secret", encoding="utf-8")

    store = FilesystemStore(tmp_path / "runs")
    state = RunState(
        run_id="r4",
        task="t4",
        provider="openai",
        model="m",
        workspace=str(workspace),
        skills_dir=str(workspace),
        max_iters=1,
    )
    store.init_run(state)

    try:
        store.snapshot_workspace_file("r4", workspace, "../ws2/secret.txt")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "escapes workspace" in str(exc)


def test_resolve_artifact_path_rejects_prefix_escape(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    state = RunState(
        run_id="r5",
        task="t5",
        provider="openai",
        model="m",
        workspace=str(tmp_path),
        skills_dir=str(tmp_path),
        max_iters=1,
    )
    store.init_run(state)

    artifacts_dir = store.run_dir("r5") / "artifacts"
    target_outside = artifacts_dir.parent / "artifacts-evil" / "x.txt"
    target_outside.parent.mkdir(parents=True, exist_ok=True)
    target_outside.write_text("x", encoding="utf-8")

    try:
        store.resolve_artifact_path("r5", "../artifacts-evil/x.txt")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "escapes artifacts directory" in str(exc)


def test_store_append_and_retrieve_success_experiences(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    store.append_success_experience(
        {
            "run_id": "r1",
            "status": "completed",
            "task": "สรุปข่าว AI วันนี้",
            "task_tokens": ["สรุป", "ข่าว", "ai", "วันนี้"],
            "selected_skills": ["tavily-search", "web-summary"],
            "action_sequence": ["web_fetch", "write_workspace_file"],
            "summary": "done",
        },
        max_items=100,
    )
    store.append_success_experience(
        {
            "run_id": "r2",
            "status": "completed",
            "task": "ส่งอีเมลแจ้งเตือน",
            "task_tokens": ["ส่ง", "อีเมล", "แจ้งเตือน"],
            "selected_skills": ["resend-email"],
            "action_sequence": ["run_python_code"],
            "summary": "done",
        },
        max_items=100,
    )

    rows = store.read_success_experiences(limit=10)
    assert len(rows) == 2

    matched = store.retrieve_success_experiences(
        task="ช่วยสรุปข่าว AI ให้หน่อย",
        selected_skills=["tavily-search"],
        top_k=1,
        max_scan=10,
    )
    assert len(matched) == 1
    assert matched[0]["run_id"] == "r1"


def test_store_retrieve_experiences_skips_preparatory_only_rows(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    store.append_success_experience(
        {
            "run_id": "bad1",
            "status": "completed",
            "task": "ช่วยหาไฟล์ pdf แล้วสรุป",
            "task_tokens": ["ช่วย", "หาไฟล์", "pdf", "สรุป"],
            "selected_skills": ["web-summary"],
            "action_sequence": ["list_dir", "read_file"],
            "produced_files": [],
            "summary": "ไม่พบไฟล์",
        },
        max_items=100,
    )
    store.append_success_experience(
        {
            "run_id": "good1",
            "status": "completed",
            "task": "ช่วยหาไฟล์ pdf แล้วสรุป",
            "task_tokens": ["ช่วย", "หาไฟล์", "pdf", "สรุป"],
            "selected_skills": ["web-summary"],
            "action_sequence": ["list_dir", "run_python_code"],
            "produced_files": ["summary.txt"],
            "summary": "สรุปแล้ว",
        },
        max_items=100,
    )

    matched = store.retrieve_success_experiences(
        task="ช่วยหาไฟล์ pdf แล้วสรุป",
        selected_skills=["web-summary"],
        top_k=5,
        max_scan=100,
    )
    ids = [row.get("run_id") for row in matched]
    assert "bad1" not in ids
    assert "good1" in ids


def test_store_append_and_retrieve_failure_experiences(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    store.append_failure_experience(
        {
            "run_id": "f1",
            "status": "failed",
            "task": "สรุปข่าว AI จากเว็บ",
            "task_tokens": ["สรุป", "ข่าว", "ai", "เว็บ"],
            "selected_skills": ["web-summary"],
            "failure_class": "missing_path",
            "recommended_strategy": "discover path first",
        },
        max_items=100,
    )
    store.append_failure_experience(
        {
            "run_id": "f2",
            "status": "failed",
            "task": "ส่งอีเมลแจ้งเตือน",
            "task_tokens": ["ส่ง", "อีเมล", "แจ้งเตือน"],
            "selected_skills": ["resend-email"],
            "failure_class": "missing_module",
            "recommended_strategy": "install module",
        },
        max_items=100,
    )

    rows = store.read_failure_experiences(limit=10)
    assert len(rows) == 2

    matched = store.retrieve_failure_experiences(
        task="ช่วยสรุปข่าว AI ให้หน่อย",
        selected_skills=["web-summary"],
        top_k=1,
        max_scan=10,
    )
    assert len(matched) == 1
    assert matched[0]["run_id"] == "f1"


def test_store_strategy_effectiveness_score(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    key = "failure_class:missing_path"
    store.append_strategy_outcome(strategy_key=key, success=True, run_id="r1")
    store.append_strategy_outcome(strategy_key=key, success=True, run_id="r2")
    store.append_strategy_outcome(strategy_key=key, success=False, run_id="r3")
    score = store.get_strategy_effectiveness_score(key)
    assert score > 0


def test_retrieve_success_experiences_filters_by_intent_and_quality(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    store.append_success_experience(
        {
            "run_id": "high_quality_web",
            "status": "completed",
            "task": "สรุปข่าว AI วันนี้",
            "task_intent": "web_research",
            "task_tokens": ["สรุป", "ข่าว", "ai", "วันนี้"],
            "selected_skills": ["tavily-search"],
            "action_sequence": ["run_python_code", "write_workspace_file"],
            "produced_files": ["ai_news.txt"],
            "quality_score": 0.9,
            "summary": "done",
        }
    )
    store.append_success_experience(
        {
            "run_id": "low_quality_web",
            "status": "completed",
            "task": "สรุปข่าว AI วันนี้",
            "task_intent": "web_research",
            "task_tokens": ["สรุป", "ข่าว", "ai", "วันนี้"],
            "selected_skills": ["tavily-search"],
            "action_sequence": ["read_file"],
            "produced_files": [],
            "quality_score": 0.2,
            "summary": "weak",
        }
    )
    store.append_success_experience(
        {
            "run_id": "high_quality_other_intent",
            "status": "completed",
            "task": "สรุปข่าว AI วันนี้",
            "task_intent": "code_execution",
            "task_tokens": ["สรุป", "ข่าว", "ai", "วันนี้"],
            "selected_skills": ["tavily-search"],
            "action_sequence": ["run_python_code", "write_workspace_file"],
            "produced_files": ["ai_news.txt"],
            "quality_score": 0.95,
            "summary": "done",
        }
    )

    matched = store.retrieve_success_experiences(
        task="ช่วยสรุปข่าว AI วันนี้",
        selected_skills=["tavily-search"],
        top_k=5,
        max_scan=50,
        task_intent="web_research",
        min_quality_score=0.55,
    )
    ids = [str(row.get("run_id")) for row in matched]
    assert "high_quality_web" in ids
    assert "low_quality_web" not in ids
    assert "high_quality_other_intent" not in ids


def test_retrieve_failure_experiences_prefers_matching_intent(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    store.append_failure_experience(
        {
            "run_id": "f-web",
            "status": "failed",
            "task": "สรุปข่าว AI วันนี้",
            "task_intent": "web_research",
            "task_tokens": ["สรุป", "ข่าว", "ai", "วันนี้"],
            "selected_skills": ["tavily-search"],
            "failure_class": "missing_path",
            "recommended_strategy": "discover path first",
        }
    )
    store.append_failure_experience(
        {
            "run_id": "f-code",
            "status": "failed",
            "task": "สรุปข่าว AI วันนี้",
            "task_intent": "code_execution",
            "task_tokens": ["สรุป", "ข่าว", "ai", "วันนี้"],
            "selected_skills": ["tavily-search"],
            "failure_class": "missing_module",
            "recommended_strategy": "install module",
        }
    )

    matched = store.retrieve_failure_experiences(
        task="สรุปข่าว AI วันนี้",
        selected_skills=["tavily-search"],
        top_k=5,
        max_scan=50,
        task_intent="web_research",
    )
    ids = [str(row.get("run_id")) for row in matched]
    assert "f-web" in ids
    assert "f-code" not in ids

    bad_key = "failure_class:bad_strategy"
    store.append_strategy_outcome(strategy_key=bad_key, success=False, run_id="r4")
    store.append_strategy_outcome(strategy_key=bad_key, success=False, run_id="r5")
    bad_score = store.get_strategy_effectiveness_score(bad_key)
    assert bad_score < 0
