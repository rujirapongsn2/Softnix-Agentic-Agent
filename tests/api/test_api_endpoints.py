from pathlib import Path

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
        return state

    def execute_prepared_run(self, run_id: str):  # type: ignore[no-untyped-def]
        s = self.store.read_state(run_id)
        s.iteration = 1
        s.last_output = "ok"
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

    r = client.post("/runs", json={"task": "t", "provider": "openai", "max_iters": 2, "workspace": str(tmp_path), "skills_dir": str(tmp_path)})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    r2 = client.get(f"/runs/{run_id}")
    assert r2.status_code == 200
    assert r2.json()["run_id"] == run_id

    r3 = client.get(f"/runs/{run_id}/iterations")
    assert r3.status_code == 200
    assert "items" in r3.json()

    r4 = client.post(f"/runs/{run_id}/cancel")
    assert r4.status_code == 200
    assert r4.json()["status"] == "cancel_requested"
