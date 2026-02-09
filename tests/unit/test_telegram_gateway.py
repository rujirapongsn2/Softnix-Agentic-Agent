from __future__ import annotations

import threading
from pathlib import Path

from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.integrations.telegram_gateway import TelegramGateway
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.types import RunState, RunStatus, StopReason


class FakeTelegramClient:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, str]] = []
        self.sent_documents: list[tuple[str, str, str]] = []
        self.updates: list[dict] = []

    def send_message(self, chat_id: str, text: str) -> dict:
        self.sent_messages.append((chat_id, text))
        return {"ok": True}

    def send_document(self, chat_id: str, file_path: Path, caption: str = "") -> dict:
        self.sent_documents.append((chat_id, file_path.name, caption))
        return {"ok": True}

    def get_updates(self, offset=None, timeout=0, limit=20):  # type: ignore[no-untyped-def]
        return self.updates


class FakeRunner:
    def __init__(self, store: FilesystemStore, workspace: Path) -> None:
        self.store = store
        self.workspace = workspace
        self.run_id = "tg-run-1"

    def prepare_run(self, task, provider_name, model, workspace, skills_dir, max_iters):  # type: ignore[no-untyped-def]
        state = RunState(
            run_id=self.run_id,
            task=task,
            provider=provider_name,
            model=model,
            workspace=str(workspace),
            skills_dir=str(skills_dir),
            max_iters=max_iters,
        )
        self.store.init_run(state)
        return state

    def execute_prepared_run(self, run_id: str):  # type: ignore[no-untyped-def]
        state = self.store.read_state(run_id)
        state.iteration = 2
        state.status = RunStatus.COMPLETED
        state.stop_reason = StopReason.COMPLETED
        state.last_output = "done output"
        self.store.write_state(state)
        artifacts_dir = self.store.run_dir(run_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "out.txt").write_text("ok", encoding="utf-8")
        return state

    def resume_run(self, run_id: str):  # type: ignore[no-untyped-def]
        return self.store.read_state(run_id)


def test_gateway_run_sends_final_message_and_artifact(tmp_path: Path, monkeypatch) -> None:
    store = FilesystemStore(tmp_path / "runs")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        provider="claude",
        model="m",
        telegram_enabled=True,
        telegram_bot_token="token-x",
        telegram_allowed_chat_ids=["8388377631"],
    )
    fake_client = FakeTelegramClient()
    threads: dict[str, threading.Thread] = {}
    fake_runner = FakeRunner(store=store, workspace=tmp_path)

    monkeypatch.setattr(
        "softnix_agentic_agent.integrations.telegram_gateway.build_runner",
        lambda settings, provider_name, model=None: fake_runner,
    )

    gateway = TelegramGateway(settings=settings, store=store, thread_registry=threads, client=fake_client)
    ok = gateway.handle_update(
        {
            "update_id": 1,
            "message": {"chat": {"id": 8388377631}, "text": "/run hello world"},
        }
    )
    assert ok is True
    assert "tg-run-1" in threads
    threads["tg-run-1"].join(timeout=2)

    assert any("Started run: tg-run-1" in text for _, text in fake_client.sent_messages)
    assert any("Run tg-run-1: completed" in text for _, text in fake_client.sent_messages)
    assert any(name == "out.txt" for _, name, _ in fake_client.sent_documents)


def test_gateway_rejects_unauthorized_chat(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        telegram_enabled=True,
        telegram_bot_token="token-x",
        telegram_allowed_chat_ids=["1"],
    )
    fake_client = FakeTelegramClient()
    gateway = TelegramGateway(settings=settings, store=store, thread_registry={}, client=fake_client)
    ok = gateway.handle_update(
        {
            "update_id": 1,
            "message": {"chat": {"id": 8388377631}, "text": "/help"},
        }
    )
    assert ok is True
    assert any("Unauthorized chat" in text for _, text in fake_client.sent_messages)

