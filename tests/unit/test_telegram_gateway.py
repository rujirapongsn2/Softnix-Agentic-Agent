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


def test_gateway_schedule_creates_schedule_file(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        scheduler_dir=tmp_path / "schedules",
        scheduler_default_timezone="Asia/Bangkok",
        telegram_enabled=True,
        telegram_bot_token="token-x",
        telegram_allowed_chat_ids=["8388377631"],
    )
    fake_client = FakeTelegramClient()
    gateway = TelegramGateway(settings=settings, store=store, thread_registry={}, client=fake_client)
    ok = gateway.handle_update(
        {
            "update_id": 3,
            "message": {"chat": {"id": 8388377631}, "text": "/schedule ทุกวัน 09:00 สรุปเว็บไซต์ www.softnix.ai"},
        }
    )
    assert ok is True
    assert any("Schedule created:" in text for _, text in fake_client.sent_messages)
    schedule_files = list((tmp_path / "schedules").glob("*.json"))
    assert len(schedule_files) == 1


def test_gateway_schedules_and_schedule_runs(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        scheduler_dir=tmp_path / "schedules",
        scheduler_default_timezone="Asia/Bangkok",
        telegram_enabled=True,
        telegram_bot_token="token-x",
        telegram_allowed_chat_ids=["8388377631"],
    )
    fake_client = FakeTelegramClient()
    gateway = TelegramGateway(settings=settings, store=store, thread_registry={}, client=fake_client)

    gateway.handle_update(
        {
            "update_id": 1,
            "message": {"chat": {"id": 8388377631}, "text": "/schedule ทุกวัน 09:00 สรุปเว็บไซต์ www.softnix.ai"},
        }
    )
    created_messages = [text for _, text in fake_client.sent_messages if "Schedule created:" in text]
    assert created_messages
    schedule_id = created_messages[-1].split("Schedule created:", 1)[1].splitlines()[0].strip()

    gateway.handle_update({"update_id": 2, "message": {"chat": {"id": 8388377631}, "text": "/schedules"}})
    assert any("Schedules (" in text for _, text in fake_client.sent_messages)
    assert any(schedule_id in text for _, text in fake_client.sent_messages)

    # No runs yet
    gateway.handle_update(
        {"update_id": 3, "message": {"chat": {"id": 8388377631}, "text": f"/schedule_runs {schedule_id}"}}
    )
    assert any("no runs yet" in text for _, text in fake_client.sent_messages)


def test_gateway_schedule_runs_reflects_runstate_status(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        scheduler_dir=tmp_path / "schedules",
        scheduler_default_timezone="Asia/Bangkok",
        telegram_enabled=True,
        telegram_bot_token="token-x",
        telegram_allowed_chat_ids=["8388377631"],
    )
    fake_client = FakeTelegramClient()
    gateway = TelegramGateway(settings=settings, store=store, thread_registry={}, client=fake_client)

    # Create schedule owned by this chat
    gateway.handle_update(
        {
            "update_id": 1,
            "message": {"chat": {"id": 8388377631}, "text": "/schedule ทุกวัน 09:00 สรุปเว็บไซต์ www.softnix.ai"},
        }
    )
    created_messages = [text for _, text in fake_client.sent_messages if "Schedule created:" in text]
    assert created_messages
    schedule_id = created_messages[-1].split("Schedule created:", 1)[1].splitlines()[0].strip()

    # Create run state as completed
    run_id = "sched-run-1"
    state = RunState(
        run_id=run_id,
        task="scheduled task",
        provider="openai",
        model="m",
        workspace=str(tmp_path),
        skills_dir=str(tmp_path),
        max_iters=10,
    )
    state.status = RunStatus.COMPLETED
    state.stop_reason = StopReason.COMPLETED
    store.init_run(state)
    store.write_state(state)
    gateway.schedule_store.append_schedule_run(schedule_id=schedule_id, run_id=run_id, status="queued")

    gateway.handle_update(
        {
            "update_id": 2,
            "message": {"chat": {"id": 8388377631}, "text": f"/schedule_runs {schedule_id}"},
        }
    )
    text = fake_client.sent_messages[-1][1]
    assert "status=completed" in text
    assert "stop_reason=completed" in text


def test_gateway_schedule_disable_and_delete(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        scheduler_dir=tmp_path / "schedules",
        scheduler_default_timezone="Asia/Bangkok",
        telegram_enabled=True,
        telegram_bot_token="token-x",
        telegram_allowed_chat_ids=["8388377631"],
    )
    fake_client = FakeTelegramClient()
    gateway = TelegramGateway(settings=settings, store=store, thread_registry={}, client=fake_client)

    gateway.handle_update(
        {
            "update_id": 1,
            "message": {"chat": {"id": 8388377631}, "text": "/schedule ทุกวัน 09:00 สรุปเว็บไซต์ www.softnix.ai"},
        }
    )
    created_messages = [text for _, text in fake_client.sent_messages if "Schedule created:" in text]
    schedule_id = created_messages[-1].split("Schedule created:", 1)[1].splitlines()[0].strip()

    gateway.handle_update(
        {"update_id": 2, "message": {"chat": {"id": 8388377631}, "text": f"/schedule_disable {schedule_id}"}}
    )
    assert "Schedule disabled" in fake_client.sent_messages[-1][1]

    gateway.handle_update(
        {"update_id": 3, "message": {"chat": {"id": 8388377631}, "text": f"/schedule_delete {schedule_id}"}}
    )
    assert "Schedule deleted" in fake_client.sent_messages[-1][1]


def test_gateway_natural_mode_runs_task_without_run_prefix(tmp_path: Path, monkeypatch) -> None:
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
        telegram_natural_mode_enabled=True,
        telegram_risky_confirmation_enabled=False,
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
            "update_id": 20,
            "message": {"chat": {"id": 8388377631}, "text": "วันนี้วันที่เท่าไหร่"},
        }
    )
    assert ok is True
    assert "tg-run-1" in threads
    threads["tg-run-1"].join(timeout=2)
    assert any("Started run: tg-run-1" in text for _, text in fake_client.sent_messages)


def test_gateway_risky_task_requires_confirmation_then_yes_runs(tmp_path: Path, monkeypatch) -> None:
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
        telegram_natural_mode_enabled=True,
        telegram_risky_confirmation_enabled=True,
    )
    fake_client = FakeTelegramClient()
    threads: dict[str, threading.Thread] = {}
    fake_runner = FakeRunner(store=store, workspace=tmp_path)

    monkeypatch.setattr(
        "softnix_agentic_agent.integrations.telegram_gateway.build_runner",
        lambda settings, provider_name, model=None: fake_runner,
    )

    gateway = TelegramGateway(settings=settings, store=store, thread_registry=threads, client=fake_client)
    first = gateway.handle_update(
        {
            "update_id": 21,
            "message": {"chat": {"id": 8388377631}, "text": "ช่วยลบไฟล์ result.txt"},
        }
    )
    assert first is True
    assert any("Risky task detected" in text for _, text in fake_client.sent_messages)
    assert "tg-run-1" not in threads

    second = gateway.handle_update(
        {
            "update_id": 22,
            "message": {"chat": {"id": 8388377631}, "text": "yes"},
        }
    )
    assert second is True
    assert "tg-run-1" in threads
    threads["tg-run-1"].join(timeout=2)
    assert any("Started run: tg-run-1" in text for _, text in fake_client.sent_messages)


def test_gateway_skill_build_command_and_status(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path / "skillpacks",
        skill_builds_dir=tmp_path / ".softnix/skill-builds",
        telegram_enabled=True,
        telegram_bot_token="token-x",
        telegram_allowed_chat_ids=["8388377631"],
    )
    fake_client = FakeTelegramClient()
    gateway = TelegramGateway(settings=settings, store=store, thread_registry={}, client=fake_client)

    class _FakeSkillBuildService:
        def start_build(self, payload):  # type: ignore[no-untyped-def]
            return {"id": "job123", "skill_name": "order-status", "status": "queued"}

        def get_build(self, job_id):  # type: ignore[no-untyped-def]
            return {"id": job_id, "skill_name": "order-status", "status": "completed", "stage": "completed"}

        def list_builds(self, limit=10):  # type: ignore[no-untyped-def]
            return [{"id": "job123", "skill_name": "order-status", "status": "completed", "stage": "completed"}]

    gateway.skill_build_service = _FakeSkillBuildService()  # type: ignore[assignment]

    ok_build = gateway.handle_update(
        {"update_id": 30, "message": {"chat": {"id": 8388377631}, "text": "/skill_build สร้าง skill ตรวจสอบสถานะคำสั่งซื้อ"}}
    )
    ok_status = gateway.handle_update(
        {"update_id": 31, "message": {"chat": {"id": 8388377631}, "text": "/skill_status job123"}}
    )
    ok_list = gateway.handle_update(
        {"update_id": 32, "message": {"chat": {"id": 8388377631}, "text": "/skill_builds"}}
    )

    assert ok_build is True
    assert ok_status is True
    assert ok_list is True
    assert any("Skill build started: job123" in text for _, text in fake_client.sent_messages)
    assert any("Skill build job123" in text for _, text in fake_client.sent_messages)
    assert any("Skill builds (" in text for _, text in fake_client.sent_messages)


def test_gateway_skill_build_auto_notify_completion(tmp_path: Path) -> None:
    store = FilesystemStore(tmp_path / "runs")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path / "skillpacks",
        skill_builds_dir=tmp_path / ".softnix/skill-builds",
        telegram_enabled=True,
        telegram_bot_token="token-x",
        telegram_allowed_chat_ids=["8388377631"],
    )
    fake_client = FakeTelegramClient()
    threads: dict[str, threading.Thread] = {}
    gateway = TelegramGateway(settings=settings, store=store, thread_registry=threads, client=fake_client)

    class _FakeSkillBuildService:
        def __init__(self) -> None:
            self._reads = 0

        def start_build(self, payload):  # type: ignore[no-untyped-def]
            return {"id": "job555", "skill_name": "order-status", "status": "running"}

        def get_build(self, job_id):  # type: ignore[no-untyped-def]
            self._reads += 1
            if self._reads < 2:
                return {"id": job_id, "skill_name": "order-status", "status": "running", "stage": "validate"}
            return {
                "id": job_id,
                "skill_name": "order-status",
                "status": "completed",
                "stage": "completed",
                "installed_path": str(tmp_path / "skillpacks" / "order-status"),
            }

        def list_builds(self, limit=10):  # type: ignore[no-untyped-def]
            return []

    gateway.skill_build_service = _FakeSkillBuildService()  # type: ignore[assignment]

    ok = gateway.handle_update(
        {"update_id": 50, "message": {"chat": {"id": 8388377631}, "text": "/skill_build สร้าง skill ตรวจสอบสถานะคำสั่งซื้อ"}}
    )
    assert ok is True
    for key, thread in list(threads.items()):
        if key.startswith("skill-build:"):
            thread.join(timeout=2)
    assert any("Skill build started: job555" in text for _, text in fake_client.sent_messages)
    assert any("Skill build job555: completed" in text for _, text in fake_client.sent_messages)
