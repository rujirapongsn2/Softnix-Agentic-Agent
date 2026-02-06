from __future__ import annotations

from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from softnix_agentic_agent.config import load_settings
from softnix_agentic_agent.runtime import build_runner
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore


class RunCreateRequest(BaseModel):
    task: str
    provider: str = Field(default="openai")
    model: str | None = None
    max_iters: int = Field(default=10, ge=1)
    workspace: str = "."
    skills_dir: str = "examples/skills"


app = FastAPI(title="Softnix Agentic Agent API", version="0.1.0")
_settings = load_settings()
_store = FilesystemStore(_settings.runs_dir)
_threads: dict[str, threading.Thread] = {}


def _background_execute(run_id: str, provider: str, model: str | None) -> None:
    runner = build_runner(_settings, provider_name=provider, model=model)
    runner.execute_prepared_run(run_id)


@app.post("/runs")
def create_run(payload: RunCreateRequest) -> dict:
    runner = build_runner(_settings, provider_name=payload.provider, model=payload.model)
    state = runner.prepare_run(
        task=payload.task,
        provider_name=payload.provider,
        model=payload.model or _settings.model,
        workspace=Path(payload.workspace),
        skills_dir=Path(payload.skills_dir),
        max_iters=payload.max_iters,
    )
    t = threading.Thread(
        target=_background_execute,
        args=(state.run_id, payload.provider, payload.model),
        daemon=True,
    )
    _threads[state.run_id] = t
    t.start()
    return {"run_id": state.run_id, "status": "started"}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    try:
        return _store.read_state(run_id).to_dict()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@app.get("/runs/{run_id}/iterations")
def get_iterations(run_id: str) -> dict:
    return {"items": _store.read_iterations(run_id)}


@app.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict:
    try:
        _store.request_cancel(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    return {"run_id": run_id, "status": "cancel_requested"}
