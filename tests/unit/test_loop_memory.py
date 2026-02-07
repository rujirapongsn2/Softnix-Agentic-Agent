import json
from pathlib import Path

from softnix_agentic_agent.agent.loop import AgentLoopRunner
from softnix_agentic_agent.agent.planner import Planner
from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.providers.base import LLMProvider
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.types import LLMResponse, ProviderStatus, StopReason


class CaptureProvider(LLMProvider):
    def __init__(self) -> None:
        self.last_user_prompt = ""

    def generate(self, messages, model, tools=None, temperature=0.2, max_tokens=1024):  # type: ignore[override]
        for msg in messages:
            if msg.get("role") == "user":
                self.last_user_prompt = str(msg.get("content", ""))
        data = {"done": True, "final_output": "done", "actions": []}
        return LLMResponse(content=json.dumps(data), usage={"total_tokens": 1})

    def healthcheck(self) -> ProviderStatus:
        return ProviderStatus(ok=True, message="ok")


def test_loop_applies_memory_from_task_and_injects_to_prompt(tmp_path: Path) -> None:
    provider = CaptureProvider()
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        memory_policy_path=tmp_path / "system" / "POLICY.md",
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="จำไว้ว่า response.tone = concise",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert "response.tone=concise" in provider.last_user_prompt

    profile = (tmp_path / "PROFILE.md").read_text(encoding="utf-8")
    assert "response.tone" in profile

    audit_path = tmp_path / "runs" / state.run_id / "memory_audit.jsonl"
    assert audit_path.exists()
    assert "response.tone" in audit_path.read_text(encoding="utf-8")


def test_loop_stages_inferred_memory_as_pending(tmp_path: Path) -> None:
    provider = CaptureProvider()
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        memory_policy_path=tmp_path / "system" / "POLICY.md",
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ช่วยสรุปสั้นๆ",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    session = (tmp_path / "SESSION.md").read_text(encoding="utf-8")
    assert "memory.pending.response.verbosity" in session

    # pending memory should not be injected as effective preference yet
    assert "memory.pending.response.verbosity" not in provider.last_user_prompt
