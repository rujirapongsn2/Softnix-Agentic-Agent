from __future__ import annotations

import json
from pathlib import Path
import threading
import time

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from softnix_agentic_agent.config import load_settings
from softnix_agentic_agent.providers.factory import create_provider
from softnix_agentic_agent.runtime import build_runner
from softnix_agentic_agent.skills.loader import SkillLoader
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore


class RunCreateRequest(BaseModel):
    task: str
    provider: str = Field(default="openai")
    model: str | None = None
    max_iters: int = Field(default=10, ge=1)
    workspace: str | None = None
    skills_dir: str = "examples/skills"


app = FastAPI(title="Softnix Agentic Agent API", version="0.1.0")
_settings = load_settings()
_store = FilesystemStore(_settings.runs_dir)
_threads: dict[str, threading.Thread] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _background_execute(run_id: str, provider: str, model: str | None) -> None:
    runner = build_runner(_settings, provider_name=provider, model=model)
    runner.execute_prepared_run(run_id)


def _background_resume(run_id: str) -> None:
    state = _store.read_state(run_id)
    runner = build_runner(_settings, provider_name=state.provider, model=state.model)
    runner.resume_run(run_id)


@app.post("/runs")
def create_run(payload: RunCreateRequest) -> dict:
    runner = build_runner(_settings, provider_name=payload.provider, model=payload.model)
    state = runner.prepare_run(
        task=payload.task,
        provider_name=payload.provider,
        model=payload.model or _settings.model,
        # Web/API runtime always uses backend configured workspace.
        workspace=_settings.workspace,
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
    return {"run_id": state.run_id, "status": "started", "workspace": str(_settings.workspace)}


@app.get("/runs")
def list_runs() -> dict:
    items = []
    for run_id in reversed(_store.list_run_ids()):
        try:
            items.append(_store.read_state(run_id).to_dict())
        except FileNotFoundError:
            continue
    return {"items": items}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    try:
        return _store.read_state(run_id).to_dict()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@app.get("/runs/{run_id}/iterations")
def get_iterations(run_id: str) -> dict:
    return {"items": _store.read_iterations(run_id)}


def _sse_pack(event: str, data: dict, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False)
    for line in payload.splitlines():
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


@app.get("/runs/{run_id}/stream")
def stream_run(
    run_id: str,
    poll_ms: int = Query(500, ge=100, le=5000),
    max_events: int = Query(0, ge=0, le=10000),
    last_event_id: int = Query(0, ge=0, alias="last_event_id"),
    header_last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    try:
        _ = _store.read_state(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc

    effective_last_event_id = max(last_event_id, _safe_int(header_last_event_id))

    def event_gen():
        event_id = 1
        sent_iteration = -1
        sent_event_count = 0
        last_state_sig = ""
        emitted = 0

        def emit(event: str, data: dict) -> str | None:
            nonlocal event_id, emitted
            current_id = event_id
            event_id += 1
            if current_id <= effective_last_event_id:
                return None
            emitted += 1
            return _sse_pack(event, data, event_id=current_id)

        while True:
            if max_events > 0 and emitted >= max_events:
                break

            state = _store.read_state(run_id)
            changed = False

            if state.iteration != sent_iteration:
                items = _store.read_iterations(run_id)
                if items:
                    payload = emit("iteration", items[-1])
                    if payload is not None:
                        yield payload
                        changed = True
                sent_iteration = state.iteration

            state_data = state.to_dict()
            state_sig = (
                f"{state_data['status']}|{state_data['stop_reason']}|"
                f"{state_data['iteration']}|{state_data['updated_at']}|"
                f"{state_data['cancel_requested']}"
            )
            if state_sig != last_state_sig:
                payload = emit("state", state_data)
                if payload is not None:
                    yield payload
                    changed = True
                last_state_sig = state_sig

            run_events = _store.read_events(run_id)
            if len(run_events) > sent_event_count:
                for msg in run_events[sent_event_count:]:
                    payload = emit("event", {"message": msg})
                    if payload is not None:
                        yield payload
                        changed = True
                sent_event_count = len(run_events)

            if state.status.value in {"completed", "failed", "canceled"}:
                payload = emit("done", state.to_dict())
                if payload is not None:
                    yield payload
                break

            if not changed:
                yield ": keep-alive\n\n"
                emitted += 1
            time.sleep(poll_ms / 1000)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


def _safe_int(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return max(0, int(value.strip()))
    except Exception:
        return 0


@app.get("/runs/{run_id}/events")
def get_events(run_id: str) -> dict:
    return {"items": _store.read_events(run_id)}


@app.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict:
    try:
        _store.request_cancel(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    return {"run_id": run_id, "status": "cancel_requested"}


@app.post("/runs/{run_id}/resume")
def resume_run(run_id: str) -> dict:
    try:
        _ = _store.read_state(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc

    t = threading.Thread(target=_background_resume, args=(run_id,), daemon=True)
    _threads[run_id] = t
    t.start()
    return {"run_id": run_id, "status": "resumed"}


@app.get("/skills")
def list_skills() -> dict:
    loader = SkillLoader(_settings.skills_dir)
    skills = loader.list_skills()
    items = [{"name": s.name, "description": s.description, "path": str(s.path)} for s in skills]
    return {"items": items}


@app.get("/artifacts/{run_id}")
def list_artifacts(run_id: str) -> dict:
    try:
        _ = _store.read_state(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    return {"items": _store.list_artifacts(run_id)}


@app.get("/artifacts/{run_id}/{artifact_path:path}")
def download_artifact(run_id: str, artifact_path: str):
    try:
        _ = _store.read_state(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc

    try:
        target = _store.resolve_artifact_path(run_id, artifact_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path=str(target), filename=target.name)


@app.get("/health")
def health() -> dict:
    providers = {}
    for name in ("openai", "claude", "custom"):
        try:
            p = create_provider(name, _settings)
            status = p.healthcheck()
            providers[name] = {"ok": status.ok, "message": status.message}
        except Exception as exc:
            providers[name] = {"ok": False, "message": str(exc)}
    return {"ok": True, "providers": providers}


@app.get("/system/config")
def system_config() -> dict:
    return {
        "provider": _settings.provider,
        "model": _settings.model,
        "workspace": str(_settings.workspace),
        "runs_dir": str(_settings.runs_dir),
        "skills_dir": str(_settings.skills_dir),
        "max_iters": _settings.max_iters,
        "safe_commands": _settings.safe_commands,
    }
