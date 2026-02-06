from pathlib import Path
import re

from fastapi.testclient import TestClient

from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.types import RunState


class FakeRunner:
    def __init__(self, store: FilesystemStore, workspace: Path) -> None:
        self.store = store
        self.workspace = workspace

    def prepare_run(self, task, provider_name, model, workspace, skills_dir, max_iters):  # type: ignore[no-untyped-def]
        state = RunState(
            run_id="run123",
            task=task,
            provider=provider_name,
            model=model,
            workspace=str(workspace),
            skills_dir=str(skills_dir),
            max_iters=max_iters,
        )
        self.store.init_run(state)
        artifacts_dir = self.store.run_dir(state.run_id) / "artifacts"
        (artifacts_dir / "report.txt").write_text("ok", encoding="utf-8")
        return state

    def execute_prepared_run(self, run_id: str):  # type: ignore[no-untyped-def]
        s = self.store.read_state(run_id)
        s.iteration = 1
        s.last_output = "ok"
        self.store.write_state(s)
        return s

    def resume_run(self, run_id: str):  # type: ignore[no-untyped-def]
        s = self.store.read_state(run_id)
        s.iteration += 1
        self.store.write_state(s)
        return s


def test_api_create_get_cancel(monkeypatch, tmp_path: Path) -> None:
    from softnix_agentic_agent.api import app as app_module

    settings = Settings(runs_dir=tmp_path / "runs", workspace=tmp_path, skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)

    monkeypatch.setattr(app_module, "_settings", settings)
    monkeypatch.setattr(app_module, "_store", store)
    monkeypatch.setattr(app_module, "_threads", {})

    def fake_build_runner(settings, provider_name, model=None):  # type: ignore[no-untyped-def]
        return FakeRunner(store=store, workspace=tmp_path)

    monkeypatch.setattr(app_module, "build_runner", fake_build_runner)

    client = TestClient(app_module.app)

    r = client.post(
        "/runs",
        json={"task": "t", "provider": "openai", "max_iters": 2, "workspace": "/other/path", "skills_dir": str(tmp_path)},
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert r.json()["workspace"] == str(tmp_path)

    r2 = client.get(f"/runs/{run_id}")
    assert r2.status_code == 200
    assert r2.json()["run_id"] == run_id
    assert r2.json()["workspace"] == str(tmp_path)

    r3 = client.get(f"/runs/{run_id}/iterations")
    assert r3.status_code == 200
    assert "items" in r3.json()

    r_stream = client.get(f"/runs/{run_id}/stream?poll_ms=100&max_events=3")
    assert r_stream.status_code == 200
    assert r_stream.headers["content-type"].startswith("text/event-stream")
    assert "event: state" in r_stream.text or "event: iteration" in r_stream.text
    ids = [int(x) for x in re.findall(r"id:\\s*(\\d+)", r_stream.text)]
    if ids:
        last_id = max(ids)
        r_stream_resume = client.get(f"/runs/{run_id}/stream?poll_ms=100&max_events=3&last_event_id={last_id}")
        assert r_stream_resume.status_code == 200
        resume_ids = [int(x) for x in re.findall(r"id:\\s*(\\d+)", r_stream_resume.text)]
        assert all(x > last_id for x in resume_ids)

    r_events = client.get(f"/runs/{run_id}/events")
    assert r_events.status_code == 200
    assert isinstance(r_events.json()["items"], list)

    r_runs = client.get("/runs")
    assert r_runs.status_code == 200
    assert len(r_runs.json()["items"]) >= 1

    r_resume = client.post(f"/runs/{run_id}/resume")
    assert r_resume.status_code == 200
    assert r_resume.json()["status"] == "resumed"

    r4 = client.post(f"/runs/{run_id}/cancel")
    assert r4.status_code == 200
    assert r4.json()["status"] == "cancel_requested"

    r_skills = client.get("/skills")
    assert r_skills.status_code == 200
    assert "items" in r_skills.json()

    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert "providers" in r_health.json()

    r_config = client.get("/system/config")
    assert r_config.status_code == 200
    assert r_config.json()["workspace"] == str(tmp_path)

    r_artifacts = client.get(f"/artifacts/{run_id}")
    assert r_artifacts.status_code == 200
    assert "report.txt" in r_artifacts.json()["items"]

    r_artifact_file = client.get(f"/artifacts/{run_id}/report.txt")
    assert r_artifact_file.status_code == 200
    assert "ok" in r_artifact_file.text

    cors_preflight = client.options(
        "/runs",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert cors_preflight.status_code == 200
    assert cors_preflight.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
