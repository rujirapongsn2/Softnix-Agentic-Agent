from __future__ import annotations

from softnix_agentic_agent.agent.loop import AgentLoopRunner
from softnix_agentic_agent.agent.planner import Planner
from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.providers.factory import create_provider
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore


def build_runner(settings: Settings, provider_name: str, model: str | None = None) -> AgentLoopRunner:
    provider = create_provider(provider_name, settings)
    planner = Planner(provider=provider, model=model or settings.model)
    store = FilesystemStore(runs_dir=settings.runs_dir)
    return AgentLoopRunner(settings=settings, planner=planner, store=store)
