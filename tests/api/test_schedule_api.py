from pathlib import Path

from fastapi.testclient import TestClient

from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.storage.schedule_store import ScheduleStore
from softnix_agentic_agent.types import RunState


class FakeRunner:
    def __init__(self, store: FilesystemStore, workspace: Path) -> None:
        self.store = store
        self.workspace = workspace

    def prepare_run(self, task, provider_name, model, workspace, skills_dir, max_iters):  # type: ignore[no-untyped-def]
        state = RunState(
            run_id=f"run-{abs(hash(task)) % 100000}",
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
        s = self.store.read_state(run_id)
        s.iteration = 1
        self.store.write_state(s)
        return s


def test_schedule_crud_and_run_now(monkeypatch, tmp_path: Path) -> None:
    from softnix_agentic_agent.api import app as app_module

    settings = Settings(
        runs_dir=tmp_path / "runs",
        workspace=tmp_path,
        skills_dir=tmp_path,
        scheduler_dir=tmp_path / "schedules",
        scheduler_default_timezone="Asia/Bangkok",
    )
    store = FilesystemStore(settings.runs_dir)
    schedule_store = ScheduleStore(settings.scheduler_dir)

    monkeypatch.setattr(app_module, "_settings", settings)
    monkeypatch.setattr(app_module, "_store", store)
    monkeypatch.setattr(app_module, "_schedule_store", schedule_store)
    monkeypatch.setattr(app_module, "_threads", {})
    monkeypatch.setattr(app_module, "_telegram_gateway", None)
    monkeypatch.setattr(app_module, "_memory_admin", None)

    def fake_build_runner(settings, provider_name, model=None):  # type: ignore[no-untyped-def]
        return FakeRunner(store=store, workspace=tmp_path)

    monkeypatch.setattr(app_module, "build_runner", fake_build_runner)

    client = TestClient(app_module.app)

    create_resp = client.post(
        "/schedules",
        json={
            "task": "summarize softnix",
            "schedule_type": "one_time",
            "run_at": "2026-02-10T09:00:00+07:00",
            "timezone": "Asia/Bangkok",
        },
    )
    assert create_resp.status_code == 200
    item = create_resp.json()["item"]
    assert item["schedule_type"] == "one_time"
    assert item["next_run_at"] == "2026-02-10T02:00:00+00:00"
    schedule_id = item["id"]

    get_resp = client.get(f"/schedules/{schedule_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["item"]["id"] == schedule_id

    list_resp = client.get("/schedules")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["items"]) == 1

    run_now_resp = client.post(f"/schedules/{schedule_id}/run-now")
    assert run_now_resp.status_code == 200
    run_id = run_now_resp.json()["run_id"]
    assert run_now_resp.json()["status"] == "started"

    runs_resp = client.get(f"/schedules/{schedule_id}/runs")
    assert runs_resp.status_code == 200
    assert runs_resp.json()["items"][0]["run_id"] == run_id
    assert runs_resp.json()["items"][0]["run_status"] in {"running", "completed", "failed", "canceled"}

    update_resp = client.patch(f"/schedules/{schedule_id}", json={"enabled": False})
    assert update_resp.status_code == 200
    assert update_resp.json()["item"]["enabled"] is False
    assert update_resp.json()["item"]["next_run_at"] is None

    delete_resp = client.delete(f"/schedules/{schedule_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "deleted"


def test_schedule_create_validation(monkeypatch, tmp_path: Path) -> None:
    from softnix_agentic_agent.api import app as app_module

    settings = Settings(runs_dir=tmp_path / "runs", workspace=tmp_path, skills_dir=tmp_path, scheduler_dir=tmp_path / "schedules")
    store = FilesystemStore(settings.runs_dir)
    schedule_store = ScheduleStore(settings.scheduler_dir)

    monkeypatch.setattr(app_module, "_settings", settings)
    monkeypatch.setattr(app_module, "_store", store)
    monkeypatch.setattr(app_module, "_schedule_store", schedule_store)
    monkeypatch.setattr(app_module, "_threads", {})
    monkeypatch.setattr(app_module, "_telegram_gateway", None)
    monkeypatch.setattr(app_module, "_memory_admin", None)

    client = TestClient(app_module.app)

    no_run_at = client.post(
        "/schedules",
        json={"task": "x", "schedule_type": "one_time", "timezone": "Asia/Bangkok"},
    )
    assert no_run_at.status_code == 400

    bad_cron = client.post(
        "/schedules",
        json={"task": "x", "schedule_type": "cron", "cron_expr": "bad cron", "timezone": "Asia/Bangkok"},
    )
    assert bad_cron.status_code == 400


def test_schedule_parse_and_create_from_text(monkeypatch, tmp_path: Path) -> None:
    from softnix_agentic_agent.api import app as app_module

    settings = Settings(runs_dir=tmp_path / "runs", workspace=tmp_path, skills_dir=tmp_path, scheduler_dir=tmp_path / "schedules")
    store = FilesystemStore(settings.runs_dir)
    schedule_store = ScheduleStore(settings.scheduler_dir)

    monkeypatch.setattr(app_module, "_settings", settings)
    monkeypatch.setattr(app_module, "_store", store)
    monkeypatch.setattr(app_module, "_schedule_store", schedule_store)
    monkeypatch.setattr(app_module, "_threads", {})
    monkeypatch.setattr(app_module, "_telegram_gateway", None)
    monkeypatch.setattr(app_module, "_memory_admin", None)

    client = TestClient(app_module.app)

    parsed = client.post(
        "/schedules/parse",
        json={"text": "ทุกวัน 09:00 สรุปเว็บไซต์ www.softnix.ai และข่าว AI", "timezone": "Asia/Bangkok"},
    )
    assert parsed.status_code == 200
    assert parsed.json()["item"]["schedule_type"] == "cron"
    assert parsed.json()["item"]["cron_expr"] == "0 9 * * *"

    created = client.post(
        "/schedules/from-text",
        json={"text": "ทุกวัน 09:00 สรุปเว็บไซต์ www.softnix.ai และข่าว AI", "timezone": "Asia/Bangkok"},
    )
    assert created.status_code == 200
    item = created.json()["item"]
    assert item["schedule_type"] == "cron"
    assert item["cron_expr"] == "0 9 * * *"
