import json
from pathlib import Path

from softnix_agentic_agent.agent.loop import AgentLoopRunner
from softnix_agentic_agent.agent.planner import Planner
from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.providers.base import LLMProvider
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.types import LLMResponse, ProviderStatus, StopReason


class FakeProvider(LLMProvider):
    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = outputs
        self.i = 0

    def generate(self, messages, model, tools=None, temperature=0.2, max_tokens=1024):  # type: ignore[override]
        item = self.outputs[min(self.i, len(self.outputs) - 1)]
        self.i += 1
        return LLMResponse(content=json.dumps(item), usage={"total_tokens": 1})

    def healthcheck(self) -> ProviderStatus:
        return ProviderStatus(ok=True, message="ok")


def test_loop_completes(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "actions": [{"name": "list_dir", "params": {"path": "."}}],
            },
            {"done": True, "final_output": "done", "actions": []},
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="demo",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=3,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert state.iteration == 2


def test_loop_max_iters(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": False, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="demo",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=2,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert state.iteration == 2


def test_loop_write_workspace_file_is_snapshotted_as_artifact(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "1111.text", "content": "ok"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="create file",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert "1111.text" in store.list_artifacts(state.run_id)


def test_loop_write_file_alias_is_snapshotted_as_artifact(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_file",
                        "params": {"path": "result.txt", "content": "ok"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="create result",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert "result.txt" in store.list_artifacts(state.run_id)


def test_loop_autofills_rm_targets_from_task_when_missing(tmp_path: Path) -> None:
    script = tmp_path / "script.py"
    result = tmp_path / "result.txt"
    script.write_text("print('x')", encoding="utf-8")
    result.write_text("x", encoding="utf-8")

    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "run_safe_command",
                        "params": {"command": "rm -f"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        safe_commands=["rm", "ls", "python", "echo"],
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ลบ script.py และลบ result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert script.exists() is False
    assert result.exists() is False
