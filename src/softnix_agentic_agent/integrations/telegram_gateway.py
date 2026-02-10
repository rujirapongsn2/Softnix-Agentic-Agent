from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.integrations.schedule_parser import parse_natural_schedule_text
from softnix_agentic_agent.integrations.telegram_client import TelegramClient
from softnix_agentic_agent.integrations.telegram_parser import TelegramCommand, parse_telegram_command
from softnix_agentic_agent.integrations.telegram_templates import (
    final_run_text,
    help_text,
    pending_text,
    started_text,
    status_text,
)
from softnix_agentic_agent.memory.markdown_store import MarkdownMemoryStore
from softnix_agentic_agent.memory.service import CoreMemoryService
from softnix_agentic_agent.runtime import build_runner
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.storage.schedule_store import ScheduleStore, compute_next_run_at


class TelegramGateway:
    def __init__(
        self,
        settings: Settings,
        store: FilesystemStore,
        thread_registry: dict[str, threading.Thread],
        client: TelegramClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.thread_registry = thread_registry
        self.client = client or TelegramClient(bot_token=settings.telegram_bot_token or "")
        self._next_offset = 0
        self.schedule_store = ScheduleStore(settings.scheduler_dir)
        self._run_chat_map: dict[str, str] = {}
        self._metrics_lock = threading.Lock()
        self._metrics: dict[str, Any] = {
            "commands_total": 0,
            "commands_by_name": {},
            "command_errors": 0,
            "unauthorized_chats": 0,
            "latency_total_ms": 0.0,
            "latency_count": 0,
            "last_error": "",
            "run_notifications_sent": 0,
            "artifact_documents_sent": 0,
        }

    def poll_once(self, limit: int = 20) -> dict[str, Any]:
        updates = self.client.get_updates(offset=self._next_offset, timeout=0, limit=limit)
        handled = 0
        for update in updates:
            update_id = int(update.get("update_id") or 0)
            if update_id > 0:
                self._next_offset = max(self._next_offset, update_id + 1)
            if self.handle_update(update):
                handled += 1
        return {"updates": len(updates), "handled": handled}

    def handle_update(self, update: dict[str, Any]) -> bool:
        started = time.monotonic()
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        text = str(message.get("text") or "").strip()
        if not chat_id or not text:
            return False

        if not self._is_allowed_chat(chat_id):
            self._increment_metric("unauthorized_chats")
            self.client.send_message(chat_id, "Unauthorized chat")
            return True

        cmd = parse_telegram_command(text)
        if cmd is None:
            self._record_command_metric("help", started)
            self.client.send_message(chat_id, help_text())
            return True

        try:
            response = self._dispatch_command(chat_id, cmd)
        except Exception as exc:
            self._increment_metric("command_errors")
            self._set_metric_value("last_error", str(exc))
            response = "Internal error while handling command"
        self._record_command_metric(cmd.name, started)
        self.client.send_message(chat_id, response)
        return True

    def _is_allowed_chat(self, chat_id: str) -> bool:
        allow = self.settings.telegram_allowed_chat_ids
        if not allow:
            return False
        return chat_id in allow

    def _dispatch_command(self, chat_id: str, cmd: TelegramCommand) -> str:
        if cmd.name == "help":
            return help_text()
        if cmd.name == "run":
            return self._run_task(chat_id=chat_id, task=cmd.arg)
        if cmd.name == "schedule":
            return self._schedule_task(chat_id=chat_id, text=cmd.arg)
        if cmd.name == "schedules":
            return self._list_schedules(chat_id=chat_id)
        if cmd.name == "schedule_runs":
            return self._list_schedule_runs(chat_id=chat_id, schedule_id=cmd.arg)
        if cmd.name == "schedule_disable":
            return self._disable_schedule(chat_id=chat_id, schedule_id=cmd.arg)
        if cmd.name == "schedule_delete":
            return self._delete_schedule(chat_id=chat_id, schedule_id=cmd.arg)
        if cmd.name == "status":
            return self._status(cmd.arg)
        if cmd.name == "cancel":
            return self._cancel(cmd.arg)
        if cmd.name == "resume":
            return self._resume(cmd.arg)
        if cmd.name == "pending":
            return self._pending(cmd.arg)
        return help_text()

    def _run_task(self, chat_id: str, task: str) -> str:
        raw = (task or "").strip()
        if not raw:
            return "Usage: /run <task>"
        if len(raw) > self.settings.telegram_max_task_chars:
            return f"Task too long (max {self.settings.telegram_max_task_chars} chars)"
        runner = build_runner(self.settings, provider_name=self.settings.provider, model=self.settings.model)
        state = runner.prepare_run(
            task=raw,
            provider_name=self.settings.provider,
            model=self.settings.model,
            workspace=self.settings.workspace,
            skills_dir=Path(self.settings.skills_dir),
            max_iters=self.settings.max_iters,
        )
        self._run_chat_map[state.run_id] = chat_id
        thread = threading.Thread(
            target=self._run_and_notify,
            args=(runner, state.run_id, chat_id),
            daemon=True,
        )
        self.thread_registry[state.run_id] = thread
        thread.start()
        return started_text(state.run_id, raw)

    def _schedule_task(self, chat_id: str, text: str) -> str:
        raw = (text or "").strip()
        if not raw:
            return "Usage: /schedule วันนี้ 09:00 <task> | /schedule ทุกวัน 09:00 <task>"
        timezone_name = self.settings.scheduler_default_timezone
        try:
            parsed = parse_natural_schedule_text(raw, timezone_name=timezone_name)
            next_run_at = compute_next_run_at(
                schedule_type=parsed.schedule_type,
                timezone_name=parsed.timezone,
                run_at=parsed.run_at,
                cron_expr=parsed.cron_expr,
            )
        except Exception as exc:
            return f"Schedule parse error: {exc}"

        item = self.schedule_store.create_schedule(
            {
                "task": parsed.task,
                "schedule_type": parsed.schedule_type,
                "run_at": parsed.run_at,
                "cron_expr": parsed.cron_expr,
                "timezone": parsed.timezone,
                "enabled": True,
                "next_run_at": next_run_at,
                "owner_type": "chat",
                "owner_id": chat_id,
                "delivery_channel": "telegram",
                "delivery_target": chat_id,
            }
        )
        if parsed.schedule_type == "cron":
            schedule_part = f"cron={item.get('cron_expr')}"
        else:
            schedule_part = f"run_at={item.get('run_at')}"
        return (
            f"Schedule created: {item['id']}\n"
            f"type: {item['schedule_type']}\n"
            f"{schedule_part}\n"
            f"timezone: {item['timezone']}\n"
            f"next_run_at: {item.get('next_run_at')}"
        )

    def _list_schedules(self, chat_id: str) -> str:
        items = [
            item
            for item in self.schedule_store.list_schedules(include_disabled=True)
            if str(item.get("owner_type", "")) == "chat" and str(item.get("owner_id", "")) == chat_id
        ]
        if not items:
            return "No schedules for this chat"
        lines = [f"Schedules ({len(items)}):"]
        for item in items[:20]:
            sid = str(item.get("id", ""))
            status = "enabled" if bool(item.get("enabled", False)) else "disabled"
            sch_type = str(item.get("schedule_type", ""))
            if sch_type == "cron":
                schedule_part = f"cron={item.get('cron_expr')}"
            else:
                schedule_part = f"run_at={item.get('run_at')}"
            lines.append(f"- {sid} [{status}] {sch_type} {schedule_part}")
        return "\n".join(lines)

    def _list_schedule_runs(self, chat_id: str, schedule_id: str) -> str:
        sid = (schedule_id or "").strip()
        if not sid:
            return "Usage: /schedule_runs <schedule_id>"
        try:
            item = self.schedule_store.get_schedule(sid)
        except FileNotFoundError:
            return f"Schedule not found: {sid}"
        if str(item.get("owner_type", "")) != "chat" or str(item.get("owner_id", "")) != chat_id:
            return f"Schedule not found: {sid}"
        rows = self.schedule_store.read_schedule_runs(sid, limit=10)
        if not rows:
            return f"Schedule {sid}: no runs yet"
        lines = [f"Schedule {sid}: recent runs ({len(rows)})"]
        for row in rows:
            run_id = str(row.get("run_id", ""))
            status = str(row.get("status", "-"))
            stop_reason = "-"
            if run_id:
                try:
                    state = self.store.read_state(run_id)
                    status = state.status.value
                    stop_reason = state.stop_reason.value if state.stop_reason else "-"
                except FileNotFoundError:
                    pass
            created_at = str(row.get("created_at", ""))
            lines.append(f"- {run_id} status={status} stop_reason={stop_reason} at={created_at}")
        return "\n".join(lines)

    def _disable_schedule(self, chat_id: str, schedule_id: str) -> str:
        sid = (schedule_id or "").strip()
        if not sid:
            return "Usage: /schedule_disable <schedule_id>"
        try:
            item = self.schedule_store.get_schedule(sid)
        except FileNotFoundError:
            return f"Schedule not found: {sid}"
        if str(item.get("owner_type", "")) != "chat" or str(item.get("owner_id", "")) != chat_id:
            return f"Schedule not found: {sid}"
        updated = self.schedule_store.update_schedule(sid, {"enabled": False, "next_run_at": None})
        return f"Schedule disabled: {sid} (enabled={updated.get('enabled')})"

    def _delete_schedule(self, chat_id: str, schedule_id: str) -> str:
        sid = (schedule_id or "").strip()
        if not sid:
            return "Usage: /schedule_delete <schedule_id>"
        try:
            item = self.schedule_store.get_schedule(sid)
        except FileNotFoundError:
            return f"Schedule not found: {sid}"
        if str(item.get("owner_type", "")) != "chat" or str(item.get("owner_id", "")) != chat_id:
            return f"Schedule not found: {sid}"
        self.schedule_store.delete_schedule(sid)
        return f"Schedule deleted: {sid}"

    def notify_run_finished(self, chat_id: str, run_id: str) -> None:
        state = self.store.read_state(run_id)
        self.client.send_message(
            chat_id,
            final_run_text(
                run_id=run_id,
                status=state.status.value,
                iteration=state.iteration,
                max_iters=state.max_iters,
                stop_reason=state.stop_reason.value if state.stop_reason else "-",
                output=state.last_output,
            ),
        )
        self._increment_metric("run_notifications_sent")
        self._send_artifacts(chat_id=chat_id, run_id=run_id)

    def _run_and_notify(self, runner: Any, run_id: str, chat_id: str) -> None:
        try:
            _ = runner.execute_prepared_run(run_id)
        except Exception as exc:
            self._increment_metric("command_errors")
            self._set_metric_value("last_error", f"run worker error: {exc}")
            try:
                self.client.send_message(chat_id, f"Run {run_id}: failed\nerror: {exc}")
            except Exception:
                pass
            return
        try:
            self.notify_run_finished(chat_id=chat_id, run_id=run_id)
        except Exception as exc:
            self._increment_metric("command_errors")
            self._set_metric_value("last_error", f"run notify error: {exc}")

    def _send_artifacts(self, chat_id: str, run_id: str) -> None:
        entries = self.store.list_artifact_entries(run_id)
        if not entries:
            return
        sent = 0
        for entry in sorted(entries, key=lambda x: float(x.get("modified_at", 0)), reverse=True):
            if sent >= 3:
                break
            rel_path = str(entry.get("path") or "").strip()
            if not rel_path:
                continue
            try:
                target = self.store.resolve_artifact_path(run_id, rel_path)
                self.client.send_document(chat_id=chat_id, file_path=target, caption=f"artifact: {rel_path}")
                sent += 1
                self._increment_metric("artifact_documents_sent")
            except Exception as exc:
                self._increment_metric("command_errors")
                self._set_metric_value("last_error", f"artifact send error: {exc}")

    def _status(self, run_id: str) -> str:
        rid = (run_id or "").strip()
        if not rid:
            return "Usage: /status <run_id>"
        try:
            state = self.store.read_state(rid)
        except FileNotFoundError:
            return f"Run not found: {rid}"
        return status_text(
            run_id=rid,
            status=state.status.value,
            iteration=state.iteration,
            max_iters=state.max_iters,
            stop_reason=state.stop_reason.value,
        )

    def _cancel(self, run_id: str) -> str:
        rid = (run_id or "").strip()
        if not rid:
            return "Usage: /cancel <run_id>"
        try:
            self.store.request_cancel(rid)
        except FileNotFoundError:
            return f"Run not found: {rid}"
        return f"Cancel requested: {rid}"

    def _resume(self, run_id: str) -> str:
        rid = (run_id or "").strip()
        if not rid:
            return "Usage: /resume <run_id>"
        try:
            state = self.store.read_state(rid)
        except FileNotFoundError:
            return f"Run not found: {rid}"
        runner = build_runner(self.settings, provider_name=state.provider, model=state.model)
        thread = threading.Thread(target=runner.resume_run, args=(rid,), daemon=True)
        self.thread_registry[rid] = thread
        thread.start()
        return f"Resumed: {rid}"

    def _pending(self, run_id: str) -> str:
        rid = (run_id or "").strip()
        if not rid:
            return "Usage: /pending <run_id>"
        try:
            state = self.store.read_state(rid)
        except FileNotFoundError:
            return f"Run not found: {rid}"
        memory_store = MarkdownMemoryStore(
            workspace=Path(state.workspace),
            policy_path=self.settings.memory_policy_path,
            profile_file=self.settings.memory_profile_file,
            session_file=self.settings.memory_session_file,
        )
        memory = CoreMemoryService(
            memory_store,
            self.store,
            rid,
            inferred_min_confidence=self.settings.memory_inferred_min_confidence,
        )
        memory.ensure_ready()
        items = memory.list_pending()
        return pending_text(rid, items)

    def get_metrics(self) -> dict[str, Any]:
        with self._metrics_lock:
            metrics = dict(self._metrics)
            avg = 0.0
            if metrics["latency_count"] > 0:
                avg = metrics["latency_total_ms"] / metrics["latency_count"]
            metrics["avg_latency_ms"] = round(avg, 2)
            return metrics

    def _increment_metric(self, key: str, amount: int = 1) -> None:
        with self._metrics_lock:
            self._metrics[key] = int(self._metrics.get(key, 0)) + amount

    def _set_metric_value(self, key: str, value: Any) -> None:
        with self._metrics_lock:
            self._metrics[key] = value

    def _record_command_metric(self, name: str, started: float) -> None:
        elapsed_ms = max(0.0, (time.monotonic() - started) * 1000.0)
        with self._metrics_lock:
            self._metrics["commands_total"] = int(self._metrics.get("commands_total", 0)) + 1
            per = dict(self._metrics.get("commands_by_name") or {})
            per[name] = int(per.get(name, 0)) + 1
            self._metrics["commands_by_name"] = per
            self._metrics["latency_total_ms"] = float(self._metrics.get("latency_total_ms", 0.0)) + elapsed_ms
            self._metrics["latency_count"] = int(self._metrics.get("latency_count", 0)) + 1
