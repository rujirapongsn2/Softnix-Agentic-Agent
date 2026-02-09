from __future__ import annotations

import json
from pathlib import Path
import re
import secrets
import threading
import time

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from softnix_agentic_agent.config import load_settings
from softnix_agentic_agent.memory.markdown_store import MarkdownMemoryStore
from softnix_agentic_agent.memory.service import CoreMemoryService
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
    skills_dir: str = "skillpacks"


class MemoryDecisionRequest(BaseModel):
    key: str
    reason: str | None = None


app = FastAPI(title="Softnix Agentic Agent API", version="0.1.0")
_settings = load_settings()
_store = FilesystemStore(_settings.runs_dir)
_threads: dict[str, threading.Thread] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=_settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _is_public_path(path: str) -> bool:
    return path in {"/health", "/docs", "/redoc", "/openapi.json"}


@app.middleware("http")
async def security_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    if request.method != "OPTIONS" and _settings.api_key and not _is_public_path(request.url.path):
        provided = request.headers.get("x-api-key", "") or request.query_params.get("api_key", "")
        if not secrets.compare_digest(provided, _settings.api_key):
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


def _background_execute(run_id: str, provider: str, model: str | None) -> None:
    runner = build_runner(_settings, provider_name=provider, model=model)
    runner.execute_prepared_run(run_id)


def _background_resume(run_id: str) -> None:
    state = _store.read_state(run_id)
    runner = build_runner(_settings, provider_name=state.provider, model=state.model)
    runner.resume_run(run_id)


_SKILLS_EVENT_RE = re.compile(r"skills selected iteration=\d+ names=(.+)$")


def _parse_selected_skills(events: list[str]) -> list[str]:
    for event in reversed(events):
        marker = _SKILLS_EVENT_RE.search(event)
        if not marker:
            continue
        raw = marker.group(1).strip()
        if not raw or raw == "(none)":
            return []
        names = [x.strip() for x in raw.split(",") if x.strip()]
        # preserve order, deduplicate
        uniq: list[str] = []
        seen = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            uniq.append(name)
        return uniq
    return []


def _state_payload(state, events: list[str] | None = None) -> dict:
    payload = state.to_dict()
    run_events = events if events is not None else _store.read_events(state.run_id)
    payload["selected_skills"] = _parse_selected_skills(run_events)
    return payload


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
    states = []
    for run_id in reversed(_store.list_run_ids()):
        try:
            states.append(_store.read_state(run_id))
        except FileNotFoundError:
            continue
    states.sort(key=lambda s: (s.updated_at or s.created_at or "", s.created_at or ""), reverse=True)
    return {"items": [_state_payload(s) for s in states]}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    try:
        state = _store.read_state(run_id)
        return _state_payload(state)
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

            run_events = _store.read_events(run_id)
            state_data = _state_payload(state, events=run_events)
            state_sig = (
                f"{state_data['status']}|{state_data['stop_reason']}|"
                f"{state_data['iteration']}|{state_data['updated_at']}|"
                f"{state_data['cancel_requested']}|{','.join(state_data.get('selected_skills', []))}"
            )
            if state_sig != last_state_sig:
                payload = emit("state", state_data)
                if payload is not None:
                    yield payload
                    changed = True
                last_state_sig = state_sig

            if len(run_events) > sent_event_count:
                for msg in run_events[sent_event_count:]:
                    payload = emit("event", {"message": msg})
                    if payload is not None:
                        yield payload
                        changed = True
                sent_event_count = len(run_events)

            if state.status.value in {"completed", "failed", "canceled"}:
                payload = emit("done", _state_payload(state, events=run_events))
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


def _require_memory_admin_key(x_memory_admin_key: str | None, query_key: str | None) -> None:
    expected = _settings.memory_admin_key or ""
    if not expected:
        raise HTTPException(status_code=403, detail="memory admin key not configured")
    provided = (x_memory_admin_key or query_key or "").strip()
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/runs/{run_id}/events")
def get_events(run_id: str) -> dict:
    return {"items": _store.read_events(run_id)}


@app.post("/admin/memory/policy/reload")
def reload_memory_policy(
    x_memory_admin_key: str | None = Header(default=None, alias="x-memory-admin-key"),
    memory_admin_key: str | None = Query(default=None),
) -> dict:
    _require_memory_admin_key(x_memory_admin_key, memory_admin_key)
    memory_store = MarkdownMemoryStore(
        workspace=_settings.workspace,
        policy_path=_settings.memory_policy_path,
        profile_file=_settings.memory_profile_file,
        session_file=_settings.memory_session_file,
    )
    memory = CoreMemoryService(
        memory_store,
        _store,
        run_id="admin-policy-reload",
        inferred_min_confidence=_settings.memory_inferred_min_confidence,
    )
    memory.ensure_ready()
    policy_entries = memory_store.load_scope("policy")
    allow_tools = sorted(memory.get_policy_allow_tools() or [])
    policy_file = _settings.memory_policy_path.resolve()
    return {
        "status": "reloaded",
        "policy_path": str(policy_file),
        "policy_entry_count": len(policy_entries),
        "policy_allow_tools": allow_tools,
        "policy_modified_at": policy_file.stat().st_mtime if policy_file.exists() else 0,
    }


@app.get("/runs/{run_id}/memory/pending")
def get_pending_memory(run_id: str) -> dict:
    try:
        state = _store.read_state(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc

    memory_store = MarkdownMemoryStore(
        workspace=Path(state.workspace),
        policy_path=_settings.memory_policy_path,
        profile_file=_settings.memory_profile_file,
        session_file=_settings.memory_session_file,
    )
    memory = CoreMemoryService(
        memory_store,
        _store,
        run_id,
        inferred_min_confidence=_settings.memory_inferred_min_confidence,
    )
    memory.ensure_ready()
    return {"items": memory.list_pending()}


@app.post("/runs/{run_id}/memory/confirm")
def confirm_pending_memory(run_id: str, payload: MemoryDecisionRequest) -> dict:
    try:
        state = _store.read_state(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc

    memory_store = MarkdownMemoryStore(
        workspace=Path(state.workspace),
        policy_path=_settings.memory_policy_path,
        profile_file=_settings.memory_profile_file,
        session_file=_settings.memory_session_file,
    )
    memory = CoreMemoryService(
        memory_store,
        _store,
        run_id,
        inferred_min_confidence=_settings.memory_inferred_min_confidence,
    )
    memory.ensure_ready()
    changed = memory.apply_pending_decision(action="confirm", key=payload.key, reason=payload.reason or "")
    if changed is None:
        raise HTTPException(status_code=404, detail="pending memory not found")
    _store.log_event(run_id, f"memory pending confirmed key={payload.key}")
    return {"status": "confirmed", "item": changed}


@app.post("/runs/{run_id}/memory/reject")
def reject_pending_memory(run_id: str, payload: MemoryDecisionRequest) -> dict:
    try:
        state = _store.read_state(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc

    memory_store = MarkdownMemoryStore(
        workspace=Path(state.workspace),
        policy_path=_settings.memory_policy_path,
        profile_file=_settings.memory_profile_file,
        session_file=_settings.memory_session_file,
    )
    memory = CoreMemoryService(
        memory_store,
        _store,
        run_id,
        inferred_min_confidence=_settings.memory_inferred_min_confidence,
    )
    memory.ensure_ready()
    changed = memory.apply_pending_decision(action="reject", key=payload.key, reason=payload.reason or "")
    if changed is None:
        raise HTTPException(status_code=404, detail="pending memory not found")
    _store.log_event(run_id, f"memory pending rejected key={payload.key}")
    return {"status": "rejected", "item": changed}


@app.get("/runs/{run_id}/memory/metrics")
def get_memory_metrics(run_id: str) -> dict:
    try:
        state = _store.read_state(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc

    memory_store = MarkdownMemoryStore(
        workspace=Path(state.workspace),
        policy_path=_settings.memory_policy_path,
        profile_file=_settings.memory_profile_file,
        session_file=_settings.memory_session_file,
    )
    memory = CoreMemoryService(
        memory_store,
        _store,
        run_id,
        inferred_min_confidence=_settings.memory_inferred_min_confidence,
    )
    memory.ensure_ready()
    metrics = memory.collect_metrics(pending_alert_threshold=_settings.memory_pending_alert_threshold)
    return metrics


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
    items = _store.list_artifacts(run_id)
    return {"items": items, "entries": _store.list_artifact_entries(run_id)}


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
        "exec_runtime": _settings.exec_runtime,
        "exec_container_lifecycle": _settings.exec_container_lifecycle,
        "exec_container_image": _settings.exec_container_image,
        "exec_container_image_profile": _settings.exec_container_image_profile,
        "exec_container_image_base": _settings.exec_container_image_base,
        "exec_container_image_web": _settings.exec_container_image_web,
        "exec_container_image_data": _settings.exec_container_image_data,
        "exec_container_image_scraping": _settings.exec_container_image_scraping,
        "exec_container_image_ml": _settings.exec_container_image_ml,
        "exec_container_image_qa": _settings.exec_container_image_qa,
        "exec_container_network": _settings.exec_container_network,
        "exec_container_cpus": _settings.exec_container_cpus,
        "exec_container_memory": _settings.exec_container_memory,
        "exec_container_pids_limit": _settings.exec_container_pids_limit,
        "exec_container_cache_dir": str(_settings.exec_container_cache_dir),
        "exec_container_pip_cache_enabled": _settings.exec_container_pip_cache_enabled,
        "memory_policy_path": str(_settings.memory_policy_path),
        "memory_profile_file": _settings.memory_profile_file,
        "memory_session_file": _settings.memory_session_file,
        "memory_prompt_max_items": _settings.memory_prompt_max_items,
        "memory_inferred_min_confidence": _settings.memory_inferred_min_confidence,
        "memory_pending_alert_threshold": _settings.memory_pending_alert_threshold,
        "no_progress_repeat_threshold": _settings.no_progress_repeat_threshold,
        "memory_admin_configured": bool(_settings.memory_admin_key),
    }
