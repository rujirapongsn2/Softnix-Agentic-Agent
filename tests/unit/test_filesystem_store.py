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
