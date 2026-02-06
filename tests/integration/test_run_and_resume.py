import json
from pathlib import Path

from softnix_agentic_agent.agent.loop import AgentLoopRunner
from softnix_agentic_agent.agent.planner import Planner
from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.providers.base import LLMProvider
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.types import LLMResponse, ProviderStatus


class SeqProvider(LLMProvider):
    def __init__(self) -> None:
        self.count = 0

    def generate(self, messages, model, tools=None, temperature=0.2, max_tokens=1024):  # type: ignore[override]
        self.count += 1
        if self.count == 1:
            data = {"done": False, "actions": []}
        else:
            data = {"done": True, "final_output": "ok", "actions": []}
        return LLMResponse(content=json.dumps(data), usage={"total_tokens": 2})

    def healthcheck(self) -> ProviderStatus:
        return ProviderStatus(ok=True, message="ok")


def test_run_then_resume(tmp_path: Path) -> None:
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path, max_iters=5)
    store = FilesystemStore(settings.runs_dir)
    planner = Planner(provider=SeqProvider(), model="m")
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    prepared = runner.prepare_run(
        task="task",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=2,
    )

    state_after = runner.execute_prepared_run(prepared.run_id)
    assert state_after.iteration == 2

    resumed = runner.resume_run(prepared.run_id)
    assert resumed.iteration == 2
