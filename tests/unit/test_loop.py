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
