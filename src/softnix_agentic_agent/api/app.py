from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import secrets
import threading
import time
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from softnix_agentic_agent.config import load_settings
from softnix_agentic_agent.integrations.skill_build_service import SkillBuildService
from softnix_agentic_agent.integrations.telegram_gateway import TelegramGateway
from softnix_agentic_agent.integrations.schedule_parser import parse_natural_schedule_text
from softnix_agentic_agent.memory.admin_control import AdminPrincipal, MemoryAdminControlPlane
from softnix_agentic_agent.memory.markdown_store import MarkdownMemoryStore
from softnix_agentic_agent.memory.service import CoreMemoryService
from softnix_agentic_agent.providers.factory import create_provider
from softnix_agentic_agent.runtime import build_runner
from softnix_agentic_agent.skills.loader import SkillLoader
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.storage.retention_service import RetentionConfig, RunRetentionService
from softnix_agentic_agent.storage.schedule_store import ScheduleStore, compute_next_run_at
from softnix_agentic_agent.storage.skill_build_store import SkillBuildStore


class RunCreateRequest(BaseModel):
    task: str
    provider: str = Field(default="openai")
    model: str | None = None
    max_iters: int = Field(default=10, ge=1)
    workspace: str | None = None
    skills_dir: str = "skillpacks"


class ScheduleCreateRequest(BaseModel):
    task: str
    schedule_type: str = Field(default="one_time")
    run_at: str | None = None
    cron_expr: str | None = None
    timezone: str | None = None
    enabled: bool = True
    owner_type: str = "system"
    owner_id: str = "default"
    delivery_channel: str = "web_ui"
    delivery_target: str | None = None


class ScheduleUpdateRequest(BaseModel):
    task: str | None = None
    run_at: str | None = None
    cron_expr: str | None = None
    timezone: str | None = None
    enabled: bool | None = None
    delivery_channel: str | None = None
    delivery_target: str | None = None


class ScheduleParseRequest(BaseModel):
    text: str
    timezone: str | None = None


class ScheduleCreateFromTextRequest(BaseModel):
    text: str
    timezone: str | None = None
    enabled: bool = True
    owner_type: str = "system"
    owner_id: str = "default"
    delivery_channel: str = "web_ui"
    delivery_target: str | None = None


class MemoryDecisionRequest(BaseModel):
    key: str
    reason: str | None = None


class AdminRotateKeyRequest(BaseModel):
    new_key: str
    note: str = ""


class AdminRevokeKeyRequest(BaseModel):
    key_id: str
    reason: str = ""


class FileUploadRequest(BaseModel):
    filename: str
    content_base64: str
    path: str | None = None


class SkillBuildRequest(BaseModel):
    task: str
    skill_name: str | None = None
    description: str | None = None
    guidance: str | None = None
    api_key_name: str | None = None
    api_key_value: str | None = None
    endpoint_template: str | None = None
    install_on_success: bool = True
    allow_overwrite: bool = False


app = FastAPI(title="Softnix Agentic Agent API", version="0.1.0")
_settings = load_settings()
_store = FilesystemStore(_settings.runs_dir)
_schedule_store = ScheduleStore(_settings.scheduler_dir)
_skill_build_store = SkillBuildStore(_settings.skill_builds_dir)
_threads: dict[str, threading.Thread] = {}
_telegram_gateway: TelegramGateway | None = None
_memory_admin: MemoryAdminControlPlane | None = None
_skill_build_service: SkillBuildService | None = None
_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()
_retention_thread: threading.Thread | None = None
_retention_stop = threading.Event()
_run_retention: RunRetentionService | None = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=_settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _is_public_path(path: str) -> bool:
    return path in {"/health", "/docs", "/redoc", "/openapi.json", "/telegram/webhook"}


def _is_within_workspace(path: Path) -> bool:
    try:
        path.resolve().relative_to(_settings.workspace.resolve())
        return True
    except Exception:
        return False


def _resolve_upload_target(raw_path: str) -> Path:
    candidate = (raw_path or "").strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="path is required")
    target = (_settings.workspace / candidate).resolve()
    if not _is_within_workspace(target):
        raise HTTPException(status_code=400, detail="path escapes workspace")
    return target


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


def _background_execute_and_notify_telegram(
    run_id: str,
    provider: str,
    model: str | None,
    chat_id: str,
) -> None:
    runner = build_runner(_settings, provider_name=provider, model=model)
    runner.execute_prepared_run(run_id)
    try:
        gateway = _build_telegram_gateway()
        gateway.notify_run_finished(chat_id=chat_id, run_id=run_id)
    except Exception:
        return


def _background_resume(run_id: str) -> None:
    state = _store.read_state(run_id)
    runner = build_runner(_settings, provider_name=state.provider, model=state.model)
    runner.resume_run(run_id)


def _normalize_run_at(run_at: str, timezone_name: str) -> str:
    text = run_at.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(timezone_name))
    return dt.astimezone(timezone.utc).isoformat()


def _validate_schedule_inputs(
    schedule_type: str,
    run_at: str | None,
    cron_expr: str | None,
    timezone_name: str,
) -> tuple[str | None, str | None, str]:
    schedule_type_value = schedule_type.strip().lower()
    if schedule_type_value not in {"one_time", "cron"}:
        raise HTTPException(status_code=400, detail="schedule_type must be one_time or cron")
    try:
        _ = ZoneInfo(timezone_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid timezone") from exc

    run_at_value = run_at
    cron_expr_value = cron_expr
    if schedule_type_value == "one_time":
        if not run_at:
            raise HTTPException(status_code=400, detail="run_at is required for one_time schedule")
        try:
            run_at_value = _normalize_run_at(run_at, timezone_name)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid run_at datetime") from exc
        cron_expr_value = None
    else:
        if not cron_expr:
            raise HTTPException(status_code=400, detail="cron_expr is required for cron schedule")
        run_at_value = None
    try:
        _ = compute_next_run_at(
            schedule_type=schedule_type_value,
            timezone_name=timezone_name,
            run_at=run_at_value,
            cron_expr=cron_expr_value,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid schedule expression: {exc}") from exc
    return run_at_value, cron_expr_value, schedule_type_value


def _start_run_from_schedule(schedule: dict) -> str:
    provider_name = _settings.provider
    model = _settings.model
    runner = build_runner(_settings, provider_name=provider_name, model=model)
    state = runner.prepare_run(
        task=str(schedule["task"]),
        provider_name=provider_name,
        model=model,
        workspace=_settings.workspace,
        skills_dir=_settings.skills_dir,
        max_iters=_settings.max_iters,
    )
    _schedule_store.append_schedule_run(schedule_id=schedule["id"], run_id=state.run_id, status="queued")
    delivery_channel = str(schedule.get("delivery_channel", "")).strip().lower()
    delivery_target = str(schedule.get("delivery_target", "")).strip()
    if delivery_channel == "telegram" and delivery_target:
        thread_target = _background_execute_and_notify_telegram
        thread_args = (state.run_id, provider_name, model, delivery_target)
    else:
        thread_target = _background_execute
        thread_args = (state.run_id, provider_name, model)
    t = threading.Thread(
        target=thread_target,
        args=thread_args,
        daemon=True,
    )
    _threads[state.run_id] = t
    t.start()
    return state.run_id


def _scheduler_loop() -> None:
    while not _scheduler_stop.is_set():
        try:
            now_utc = datetime.now(timezone.utc)
            due_items = _schedule_store.list_due_schedules(
                now_utc=now_utc,
                limit=max(1, int(_settings.scheduler_max_dispatch_per_tick)),
            )
            for item in due_items:
                try:
                    _start_run_from_schedule(item)
                    _schedule_store.mark_dispatched(item["id"], now_utc)
                except Exception:
                    continue
        except Exception:
            pass
        _scheduler_stop.wait(max(1.0, float(_settings.scheduler_poll_interval_sec)))


def _retention_loop() -> None:
    while not _retention_stop.is_set():
        try:
            _build_run_retention().run_cleanup(dry_run=False)
        except Exception:
            pass
        _retention_stop.wait(max(5.0, float(_settings.run_retention_interval_sec)))


@app.on_event("startup")
def _startup_scheduler() -> None:
    global _scheduler_thread
    if not _settings.scheduler_enabled:
        return
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()


@app.on_event("shutdown")
def _shutdown_scheduler() -> None:
    _scheduler_stop.set()


@app.on_event("startup")
def _startup_retention() -> None:
    global _retention_thread
    if not _settings.run_retention_enabled:
        return
    if _retention_thread is not None and _retention_thread.is_alive():
        return
    _retention_stop.clear()
    _retention_thread = threading.Thread(target=_retention_loop, daemon=True)
    _retention_thread.start()


@app.on_event("shutdown")
def _shutdown_retention() -> None:
    _retention_stop.set()


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


@app.post("/files/upload")
def upload_file_to_workspace(payload: FileUploadRequest) -> dict:
    filename = payload.filename.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="file name is required")
    target_raw = (payload.path or "").strip() or filename
    target = _resolve_upload_target(target_raw)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = base64.b64decode(payload.content_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid content_base64") from exc
    target.write_bytes(data)
    rel = str(target.relative_to(_settings.workspace.resolve()))
    return {"status": "uploaded", "path": rel, "size": len(data)}


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


@app.post("/schedules")
def create_schedule(payload: ScheduleCreateRequest) -> dict:
    timezone_name = (payload.timezone or _settings.scheduler_default_timezone).strip()
    run_at_value, cron_expr_value, schedule_type = _validate_schedule_inputs(
        schedule_type=payload.schedule_type,
        run_at=payload.run_at,
        cron_expr=payload.cron_expr,
        timezone_name=timezone_name,
    )
    next_run_at = compute_next_run_at(
        schedule_type=schedule_type,
        timezone_name=timezone_name,
        run_at=run_at_value,
        cron_expr=cron_expr_value,
    )
    item = _schedule_store.create_schedule(
        {
            "task": payload.task,
            "schedule_type": schedule_type,
            "run_at": run_at_value,
            "cron_expr": cron_expr_value,
            "timezone": timezone_name,
            "enabled": payload.enabled,
            "next_run_at": next_run_at if payload.enabled else None,
            "owner_type": payload.owner_type,
            "owner_id": payload.owner_id,
            "delivery_channel": payload.delivery_channel,
            "delivery_target": payload.delivery_target,
        }
    )
    return {"item": item}


@app.post("/schedules/parse")
def parse_schedule(payload: ScheduleParseRequest) -> dict:
    timezone_name = (payload.timezone or _settings.scheduler_default_timezone).strip()
    try:
        parsed = parse_natural_schedule_text(payload.text, timezone_name=timezone_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": parsed.to_dict()}


@app.post("/schedules/from-text")
def create_schedule_from_text(payload: ScheduleCreateFromTextRequest) -> dict:
    timezone_name = (payload.timezone or _settings.scheduler_default_timezone).strip()
    try:
        parsed = parse_natural_schedule_text(payload.text, timezone_name=timezone_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    next_run_at = compute_next_run_at(
        schedule_type=parsed.schedule_type,
        timezone_name=parsed.timezone,
        run_at=parsed.run_at,
        cron_expr=parsed.cron_expr,
    )
    item = _schedule_store.create_schedule(
        {
            "task": parsed.task,
            "schedule_type": parsed.schedule_type,
            "run_at": parsed.run_at,
            "cron_expr": parsed.cron_expr,
            "timezone": parsed.timezone,
            "enabled": payload.enabled,
            "next_run_at": next_run_at if payload.enabled else None,
            "owner_type": payload.owner_type,
            "owner_id": payload.owner_id,
            "delivery_channel": payload.delivery_channel,
            "delivery_target": payload.delivery_target,
        }
    )
    return {"item": item, "parsed": parsed.to_dict()}


@app.get("/schedules")
def list_schedules(include_disabled: bool = Query(default=True)) -> dict:
    return {"items": _schedule_store.list_schedules(include_disabled=include_disabled)}


@app.get("/schedules/{schedule_id}")
def get_schedule(schedule_id: str) -> dict:
    try:
        item = _schedule_store.get_schedule(schedule_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="schedule not found") from exc
    return {"item": item}


@app.patch("/schedules/{schedule_id}")
def update_schedule(schedule_id: str, payload: ScheduleUpdateRequest) -> dict:
    try:
        current = _schedule_store.get_schedule(schedule_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="schedule not found") from exc

    next_task = payload.task if payload.task is not None else str(current["task"])
    next_timezone = (payload.timezone if payload.timezone is not None else current["timezone"]).strip()
    next_enabled = bool(payload.enabled) if payload.enabled is not None else bool(current.get("enabled", True))
    next_schedule_type = str(current["schedule_type"])
    next_run_at = payload.run_at if payload.run_at is not None else current.get("run_at")
    next_cron_expr = payload.cron_expr if payload.cron_expr is not None else current.get("cron_expr")

    normalized_run_at, normalized_cron_expr, schedule_type = _validate_schedule_inputs(
        schedule_type=next_schedule_type,
        run_at=next_run_at,
        cron_expr=next_cron_expr,
        timezone_name=next_timezone,
    )
    computed_next_run_at = compute_next_run_at(
        schedule_type=schedule_type,
        timezone_name=next_timezone,
        run_at=normalized_run_at,
        cron_expr=normalized_cron_expr,
    )

    updates = {
        "task": next_task,
        "timezone": next_timezone,
        "run_at": normalized_run_at,
        "cron_expr": normalized_cron_expr,
        "enabled": next_enabled,
        "next_run_at": computed_next_run_at if next_enabled else None,
    }
    if payload.delivery_channel is not None:
        updates["delivery_channel"] = payload.delivery_channel
    if payload.delivery_target is not None:
        updates["delivery_target"] = payload.delivery_target

    item = _schedule_store.update_schedule(schedule_id, updates)
    return {"item": item}


@app.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: str) -> dict:
    try:
        item = _schedule_store.delete_schedule(schedule_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="schedule not found") from exc
    return {"status": "deleted", "item": item}


@app.post("/schedules/{schedule_id}/run-now")
def run_schedule_now(schedule_id: str) -> dict:
    try:
        item = _schedule_store.get_schedule(schedule_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="schedule not found") from exc
    run_id = _start_run_from_schedule(item)
    _schedule_store.mark_dispatched(schedule_id, datetime.now(timezone.utc))
    return {"status": "started", "schedule_id": schedule_id, "run_id": run_id}


@app.get("/schedules/{schedule_id}/runs")
def list_schedule_runs(schedule_id: str, limit: int = Query(default=50, ge=1, le=200)) -> dict:
    try:
        _ = _schedule_store.get_schedule(schedule_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="schedule not found") from exc
    rows = _schedule_store.read_schedule_runs(schedule_id, limit=limit)
    enriched: list[dict] = []
    for row in rows:
        run_id = row.get("run_id")
        if not run_id:
            enriched.append(row)
            continue
        try:
            state = _store.read_state(str(run_id))
            row = {**row, "run_status": state.status.value, "run_stop_reason": state.stop_reason.value if state.stop_reason else None}
        except FileNotFoundError:
            pass
        enriched.append(row)
    return {"items": enriched}


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


def _build_telegram_gateway() -> TelegramGateway:
    global _telegram_gateway
    if not _settings.telegram_enabled:
        raise HTTPException(status_code=503, detail="telegram gateway disabled")
    if not _settings.telegram_bot_token:
        raise HTTPException(status_code=503, detail="telegram bot token not configured")
    if not _settings.telegram_allowed_chat_ids:
        raise HTTPException(status_code=503, detail="telegram allowed chat ids not configured")
    if _telegram_gateway is None:
        _telegram_gateway = TelegramGateway(settings=_settings, store=_store, thread_registry=_threads)
    return _telegram_gateway


def _build_skill_build_service() -> SkillBuildService:
    global _skill_build_service
    if _skill_build_service is None:
        _skill_build_service = SkillBuildService(settings=_settings, store=_skill_build_store)
    return _skill_build_service


def _build_memory_admin() -> MemoryAdminControlPlane:
    global _memory_admin
    if _memory_admin is None:
        _memory_admin = MemoryAdminControlPlane(
            keys_path=_settings.memory_admin_keys_path,
            audit_path=_settings.memory_admin_audit_path,
            legacy_admin_key=_settings.memory_admin_key,
            external_admin_keys=_settings.memory_admin_keys,
        )
    return _memory_admin


def _build_run_retention() -> RunRetentionService:
    global _run_retention
    if _run_retention is None:
        _run_retention = RunRetentionService(
            runs_dir=_settings.runs_dir,
            skill_builds_dir=_settings.skill_builds_dir,
            config=RetentionConfig(
                enabled=_settings.run_retention_enabled,
                interval_sec=_settings.run_retention_interval_sec,
                keep_finished_days=_settings.run_retention_keep_finished_days,
                max_runs=_settings.run_retention_max_runs,
                max_bytes=_settings.run_retention_max_bytes,
                skill_builds_keep_finished_days=_settings.skill_build_retention_keep_finished_days,
                skill_builds_max_jobs=_settings.skill_build_retention_max_jobs,
                skill_builds_max_bytes=_settings.skill_build_retention_max_bytes,
                experience_success_max_items=_settings.experience_success_max_items,
                experience_failure_max_items=_settings.experience_failure_max_items,
                experience_strategy_max_items=_settings.experience_strategy_max_items,
            ),
        )
    return _run_retention


def _require_memory_admin_key(
    x_memory_admin_key: str | None,
    query_key: str | None,
) -> AdminPrincipal:
    admin = _build_memory_admin()
    if not admin.is_configured():
        raise HTTPException(status_code=403, detail="memory admin key not configured")
    provided = (x_memory_admin_key or query_key or "").strip()
    principal = admin.authenticate(provided)
    if principal is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return principal


@app.get("/runs/{run_id}/events")
def get_events(run_id: str) -> dict:
    return {"items": _store.read_events(run_id)}


@app.post("/admin/memory/policy/reload")
def reload_memory_policy(
    x_memory_admin_key: str | None = Header(default=None, alias="x-memory-admin-key"),
    memory_admin_key: str | None = Query(default=None),
) -> dict:
    principal = _require_memory_admin_key(x_memory_admin_key, memory_admin_key)
    admin = _build_memory_admin()
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
    admin.audit(
        action="policy_reload",
        actor=principal,
        status="ok",
        detail={
            "policy_path": str(policy_file),
            "policy_entry_count": len(policy_entries),
        },
    )
    return {
        "status": "reloaded",
        "policy_path": str(policy_file),
        "policy_entry_count": len(policy_entries),
        "policy_allow_tools": allow_tools,
        "policy_modified_at": policy_file.stat().st_mtime if policy_file.exists() else 0,
    }


@app.get("/admin/memory/keys")
def list_memory_admin_keys(
    x_memory_admin_key: str | None = Header(default=None, alias="x-memory-admin-key"),
    memory_admin_key: str | None = Query(default=None),
) -> dict:
    principal = _require_memory_admin_key(x_memory_admin_key, memory_admin_key)
    admin = _build_memory_admin()
    admin.audit(action="list_keys", actor=principal, status="ok", detail={})
    return {"items": admin.list_keys()}


@app.post("/admin/memory/keys/rotate")
def rotate_memory_admin_key(
    payload: AdminRotateKeyRequest,
    x_memory_admin_key: str | None = Header(default=None, alias="x-memory-admin-key"),
    memory_admin_key: str | None = Query(default=None),
) -> dict:
    principal = _require_memory_admin_key(x_memory_admin_key, memory_admin_key)
    admin = _build_memory_admin()
    try:
        created = admin.rotate_key(new_key=payload.new_key, note=payload.note, actor=principal)
    except ValueError as exc:
        admin.audit(
            action="rotate_key",
            actor=principal,
            status="error",
            detail={"reason": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "rotated", "item": created}


@app.post("/admin/memory/keys/revoke")
def revoke_memory_admin_key(
    payload: AdminRevokeKeyRequest,
    x_memory_admin_key: str | None = Header(default=None, alias="x-memory-admin-key"),
    memory_admin_key: str | None = Query(default=None),
) -> dict:
    principal = _require_memory_admin_key(x_memory_admin_key, memory_admin_key)
    admin = _build_memory_admin()
    try:
        changed = admin.revoke_key(key_id=payload.key_id, reason=payload.reason, actor=principal)
    except ValueError as exc:
        admin.audit(
            action="revoke_key",
            actor=principal,
            status="error",
            detail={"reason": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        admin.audit(
            action="revoke_key",
            actor=principal,
            status="error",
            detail={"reason": "key not found", "key_id": payload.key_id},
        )
        raise HTTPException(status_code=404, detail="key not found") from exc
    return {"status": "revoked", "item": changed}


@app.get("/admin/memory/audit")
def get_memory_admin_audit(
    limit: int = Query(default=100, ge=1, le=1000),
    x_memory_admin_key: str | None = Header(default=None, alias="x-memory-admin-key"),
    memory_admin_key: str | None = Query(default=None),
) -> dict:
    principal = _require_memory_admin_key(x_memory_admin_key, memory_admin_key)
    admin = _build_memory_admin()
    admin.audit(action="read_audit", actor=principal, status="ok", detail={"limit": limit})
    return {"items": admin.read_audit(limit=limit)}


@app.get("/admin/storage/retention/report")
def retention_report(
    x_memory_admin_key: str | None = Header(default=None, alias="x-memory-admin-key"),
    memory_admin_key: str | None = Query(default=None),
) -> dict:
    principal = _require_memory_admin_key(x_memory_admin_key, memory_admin_key)
    admin = _build_memory_admin()
    report = _build_run_retention().report()
    admin.audit(
        action="retention_report",
        actor=principal,
        status="ok",
        detail={"planned_delete_runs": report.get("summary", {}).get("planned_delete_runs", 0)},
    )
    return {"status": "ok", "report": report}


@app.post("/admin/storage/retention/run")
def retention_run(
    dry_run: bool = Query(default=True),
    x_memory_admin_key: str | None = Header(default=None, alias="x-memory-admin-key"),
    memory_admin_key: str | None = Query(default=None),
) -> dict:
    principal = _require_memory_admin_key(x_memory_admin_key, memory_admin_key)
    admin = _build_memory_admin()
    result = _build_run_retention().run_cleanup(dry_run=dry_run)
    report = result.get("report", {}) if isinstance(result, dict) else {}
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    admin.audit(
        action="retention_run",
        actor=principal,
        status=str(result.get("status", "ok")),
        detail={
            "dry_run": dry_run,
            "planned_delete_runs": summary.get("planned_delete_runs", 0),
            "deleted_runs": len(result.get("deleted_run_ids", []) or []),
        },
    )
    return result


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


@app.post("/skills/build")
def create_skill_build(payload: SkillBuildRequest) -> dict:
    service = _build_skill_build_service()
    try:
        item = service.start_build(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@app.get("/skills/builds")
def list_skill_builds(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    service = _build_skill_build_service()
    return {"items": service.list_builds(limit=limit)}


@app.get("/skills/builds/{job_id}")
def get_skill_build(job_id: str) -> dict:
    service = _build_skill_build_service()
    try:
        item = service.get_build(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="skill build job not found") from exc
    return {"item": item}


@app.get("/skills/builds/{job_id}/events")
def get_skill_build_events(job_id: str) -> dict:
    service = _build_skill_build_service()
    try:
        _ = service.get_build(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="skill build job not found") from exc
    return {"items": service.read_events(job_id)}


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


@app.post("/telegram/webhook")
def telegram_webhook(
    payload: dict,
    x_telegram_bot_api_secret_token: str | None = Header(default=None, alias="x-telegram-bot-api-secret-token"),
) -> dict:
    gateway = _build_telegram_gateway()
    expected = (_settings.telegram_webhook_secret or "").strip()
    if expected:
        provided = (x_telegram_bot_api_secret_token or "").strip()
        if not secrets.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="invalid telegram webhook secret")
    handled = gateway.handle_update(payload)
    return {"ok": True, "handled": handled}


@app.post("/telegram/poll")
def telegram_poll(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    gateway = _build_telegram_gateway()
    return gateway.poll_once(limit=limit)


@app.get("/telegram/metrics")
def telegram_metrics() -> dict:
    gateway = _build_telegram_gateway()
    return gateway.get_metrics()


@app.get("/system/config")
def system_config() -> dict:
    admin = _build_memory_admin()
    return {
        "provider": _settings.provider,
        "model": _settings.model,
        "workspace": str(_settings.workspace),
        "runs_dir": str(_settings.runs_dir),
        "skill_builds_dir": str(_settings.skill_builds_dir),
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
        "exec_container_run_venv_enabled": _settings.exec_container_run_venv_enabled,
        "exec_container_auto_install_enabled": _settings.exec_container_auto_install_enabled,
        "exec_container_auto_install_max_modules": _settings.exec_container_auto_install_max_modules,
        "memory_policy_path": str(_settings.memory_policy_path),
        "memory_profile_file": _settings.memory_profile_file,
        "memory_session_file": _settings.memory_session_file,
        "memory_prompt_max_items": _settings.memory_prompt_max_items,
        "memory_inferred_min_confidence": _settings.memory_inferred_min_confidence,
        "memory_pending_alert_threshold": _settings.memory_pending_alert_threshold,
        "no_progress_repeat_threshold": _settings.no_progress_repeat_threshold,
        "run_max_wall_time_sec": _settings.run_max_wall_time_sec,
        "planner_parse_error_streak_threshold": _settings.planner_parse_error_streak_threshold,
        "capability_failure_streak_threshold": _settings.capability_failure_streak_threshold,
        "objective_stagnation_replan_threshold": _settings.objective_stagnation_replan_threshold,
        "planner_retry_on_parse_error": _settings.planner_retry_on_parse_error,
        "planner_retry_max_attempts": _settings.planner_retry_max_attempts,
        "memory_admin_configured": admin.is_configured(),
        "memory_admin_keys_path": str(_settings.memory_admin_keys_path),
        "memory_admin_audit_path": str(_settings.memory_admin_audit_path),
        "memory_admin_external_keys_count": len(_settings.memory_admin_keys),
        "telegram_enabled": _settings.telegram_enabled,
        "telegram_mode": _settings.telegram_mode,
        "telegram_allowed_chat_ids_count": len(_settings.telegram_allowed_chat_ids),
        "telegram_bot_token_configured": bool(_settings.telegram_bot_token),
        "telegram_webhook_secret_configured": bool(_settings.telegram_webhook_secret),
        "telegram_poll_interval_sec": _settings.telegram_poll_interval_sec,
        "telegram_max_task_chars": _settings.telegram_max_task_chars,
        "telegram_natural_mode_enabled": _settings.telegram_natural_mode_enabled,
        "telegram_risky_confirmation_enabled": _settings.telegram_risky_confirmation_enabled,
        "telegram_confirmation_ttl_sec": _settings.telegram_confirmation_ttl_sec,
        "scheduler_enabled": _settings.scheduler_enabled,
        "scheduler_dir": str(_settings.scheduler_dir),
        "scheduler_poll_interval_sec": _settings.scheduler_poll_interval_sec,
        "scheduler_max_dispatch_per_tick": _settings.scheduler_max_dispatch_per_tick,
        "scheduler_default_timezone": _settings.scheduler_default_timezone,
        "run_retention_enabled": _settings.run_retention_enabled,
        "run_retention_interval_sec": _settings.run_retention_interval_sec,
        "run_retention_keep_finished_days": _settings.run_retention_keep_finished_days,
        "run_retention_max_runs": _settings.run_retention_max_runs,
        "run_retention_max_bytes": _settings.run_retention_max_bytes,
        "skill_build_retention_keep_finished_days": _settings.skill_build_retention_keep_finished_days,
        "skill_build_retention_max_jobs": _settings.skill_build_retention_max_jobs,
        "skill_build_retention_max_bytes": _settings.skill_build_retention_max_bytes,
        "experience_success_max_items": _settings.experience_success_max_items,
        "experience_failure_max_items": _settings.experience_failure_max_items,
        "experience_strategy_max_items": _settings.experience_strategy_max_items,
    }
