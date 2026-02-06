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
