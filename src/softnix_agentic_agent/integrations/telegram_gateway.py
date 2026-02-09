from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.integrations.telegram_client import TelegramClient
from softnix_agentic_agent.integrations.telegram_parser import TelegramCommand, parse_telegram_command
from softnix_agentic_agent.integrations.telegram_templates import (
    help_text,
    pending_text,
    started_text,
    status_text,
)
from softnix_agentic_agent.memory.markdown_store import MarkdownMemoryStore
from softnix_agentic_agent.memory.service import CoreMemoryService
from softnix_agentic_agent.runtime import build_runner
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore


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
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        text = str(message.get("text") or "").strip()
        if not chat_id or not text:
            return False

        if not self._is_allowed_chat(chat_id):
            self.client.send_message(chat_id, "Unauthorized chat")
            return True

        cmd = parse_telegram_command(text)
        if cmd is None:
            self.client.send_message(chat_id, help_text())
            return True

        self.client.send_message(chat_id, self._dispatch_command(cmd))
        return True

    def _is_allowed_chat(self, chat_id: str) -> bool:
        allow = self.settings.telegram_allowed_chat_ids
        if not allow:
            return False
        return chat_id in allow

    def _dispatch_command(self, cmd: TelegramCommand) -> str:
        if cmd.name == "help":
            return help_text()
        if cmd.name == "run":
            return self._run_task(cmd.arg)
        if cmd.name == "status":
            return self._status(cmd.arg)
        if cmd.name == "cancel":
            return self._cancel(cmd.arg)
        if cmd.name == "resume":
            return self._resume(cmd.arg)
        if cmd.name == "pending":
            return self._pending(cmd.arg)
        return help_text()

    def _run_task(self, task: str) -> str:
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
        thread = threading.Thread(target=runner.execute_prepared_run, args=(state.run_id,), daemon=True)
        self.thread_registry[state.run_id] = thread
        thread.start()
        return started_text(state.run_id, raw)

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

