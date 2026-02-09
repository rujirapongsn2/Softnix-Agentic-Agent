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

    settings = Settings(runs_dir=tmp_path / "runs", workspace=tmp_path, skills_dir=tmp_path, memory_admin_key="admin-secret")
    store = FilesystemStore(settings.runs_dir)

    monkeypatch.setattr(app_module, "_settings", settings)
    monkeypatch.setattr(app_module, "_store", store)
    monkeypatch.setattr(app_module, "_threads", {})
    monkeypatch.setattr(app_module, "_telegram_gateway", None)
    monkeypatch.setattr(app_module, "_memory_admin", None)

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
    store.log_event(run_id, "skills selected iteration=1 names=web-summary,sample-skill")

    r2 = client.get(f"/runs/{run_id}")
    assert r2.status_code == 200
    assert r2.json()["run_id"] == run_id
    assert r2.json()["workspace"] == str(tmp_path)
    assert r2.json().get("selected_skills") == ["web-summary", "sample-skill"]
    assert r2.headers.get("x-content-type-options") == "nosniff"
    assert r2.headers.get("x-frame-options") == "DENY"

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

    (tmp_path / "memory" / "SESSION.md").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "SESSION.md").write_text(
        "# SESSION\n\n## Context\n"
        "- key:memory.pending.response.verbosity | value:concise | kind:preference | priority:45 | ttl:session_end | source:user_inferred | updated_at:2026-02-07T00:00:00Z\n",
        encoding="utf-8",
    )
    r_pending = client.get(f"/runs/{run_id}/memory/pending")
    assert r_pending.status_code == 200
    pending_items = r_pending.json()["items"]
    assert len(pending_items) == 1
    assert pending_items[0]["target_key"] == "response.verbosity"

    r_metrics = client.get(f"/runs/{run_id}/memory/metrics")
    assert r_metrics.status_code == 200
    assert r_metrics.json()["pending_count"] == 1
    assert isinstance(r_metrics.json()["policy_allow_tools"], list)

    r_confirm = client.post(
        f"/runs/{run_id}/memory/confirm",
        json={"key": "response.verbosity", "reason": "approve via api"},
    )
    assert r_confirm.status_code == 200
    assert r_confirm.json()["status"] == "confirmed"

    r_pending_after_confirm = client.get(f"/runs/{run_id}/memory/pending")
    assert r_pending_after_confirm.status_code == 200
    assert r_pending_after_confirm.json()["items"] == []

    (tmp_path / "memory" / "SESSION.md").write_text(
        "# SESSION\n\n## Context\n"
        "- key:memory.pending.response.tone | value:friendly | kind:preference | priority:45 | ttl:session_end | source:user_inferred | updated_at:2026-02-07T00:00:00Z\n",
        encoding="utf-8",
    )
    r_reject = client.post(
        f"/runs/{run_id}/memory/reject",
        json={"key": "response.tone", "reason": "reject via api"},
    )
    assert r_reject.status_code == 200
    assert r_reject.json()["status"] == "rejected"

    r_reload_no_key = client.post("/admin/memory/policy/reload")
    assert r_reload_no_key.status_code == 401

    r_reload = client.post("/admin/memory/policy/reload", headers={"x-memory-admin-key": "admin-secret"})
    assert r_reload.status_code == 200
    assert r_reload.json()["status"] == "reloaded"
    assert "policy_allow_tools" in r_reload.json()

    r_runs = client.get("/runs")
    assert r_runs.status_code == 200
    assert len(r_runs.json()["items"]) >= 1
    assert r_runs.json()["items"][0].get("selected_skills") == ["web-summary", "sample-skill"]

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
    assert r_config.json()["memory_admin_configured"] is True

    r_artifacts = client.get(f"/artifacts/{run_id}")
    assert r_artifacts.status_code == 200
    assert "report.txt" in r_artifacts.json()["items"]
    assert any(entry["path"] == "report.txt" for entry in r_artifacts.json().get("entries", []))

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


def test_api_requires_key_when_configured(monkeypatch, tmp_path: Path) -> None:
    from softnix_agentic_agent.api import app as app_module

    settings = Settings(runs_dir=tmp_path / "runs", workspace=tmp_path, skills_dir=tmp_path, api_key="secret-key")
    store = FilesystemStore(settings.runs_dir)

    monkeypatch.setattr(app_module, "_settings", settings)
    monkeypatch.setattr(app_module, "_store", store)
    monkeypatch.setattr(app_module, "_threads", {})
    monkeypatch.setattr(app_module, "_telegram_gateway", None)
    monkeypatch.setattr(app_module, "_memory_admin", None)

    def fake_build_runner(settings, provider_name, model=None):  # type: ignore[no-untyped-def]
        return FakeRunner(store=store, workspace=tmp_path)

    monkeypatch.setattr(app_module, "build_runner", fake_build_runner)

    client = TestClient(app_module.app)

    no_key = client.get("/runs")
    assert no_key.status_code == 401
    assert no_key.json()["detail"] == "unauthorized"

    bad_key = client.get("/runs", headers={"x-api-key": "wrong"})
    assert bad_key.status_code == 401

    ok = client.get("/runs", headers={"x-api-key": "secret-key"})
    assert ok.status_code == 200

    ok_query = client.get("/runs?api_key=secret-key")
    assert ok_query.status_code == 200

    health = client.get("/health")
    assert health.status_code == 200

    reload_policy = client.post(
        "/admin/memory/policy/reload",
        headers={"x-api-key": "secret-key", "x-memory-admin-key": "anything"},
    )
    assert reload_policy.status_code == 403


def test_runs_are_sorted_by_latest_updated_at(monkeypatch, tmp_path: Path) -> None:
    from softnix_agentic_agent.api import app as app_module

    settings = Settings(runs_dir=tmp_path / "runs", workspace=tmp_path, skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)

    old_state = RunState(
        run_id="oldrun",
        task="old task",
        provider="openai",
        model="m",
        workspace=str(tmp_path),
        skills_dir=str(tmp_path),
        max_iters=1,
        created_at="2026-02-07T01:00:00+00:00",
        updated_at="2026-02-07T01:00:00+00:00",
    )
    new_state = RunState(
        run_id="newrun",
        task="new task",
        provider="openai",
        model="m",
        workspace=str(tmp_path),
        skills_dir=str(tmp_path),
        max_iters=1,
        created_at="2026-02-07T02:00:00+00:00",
        updated_at="2026-02-07T02:00:00+00:00",
    )
    store.init_run(old_state)
    store.init_run(new_state)

    monkeypatch.setattr(app_module, "_settings", settings)
    monkeypatch.setattr(app_module, "_store", store)
    monkeypatch.setattr(app_module, "_threads", {})
    monkeypatch.setattr(app_module, "_telegram_gateway", None)
    monkeypatch.setattr(app_module, "_memory_admin", None)

    client = TestClient(app_module.app)
    resp = client.get("/runs")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["run_id"] == "newrun"
    assert items[1]["run_id"] == "oldrun"


def test_telegram_webhook_and_poll(monkeypatch, tmp_path: Path) -> None:
    from softnix_agentic_agent.api import app as app_module

    class FakeTelegramGateway:
        def __init__(self, settings, store, thread_registry):  # type: ignore[no-untyped-def]
            self.settings = settings
            self.store = store
            self.thread_registry = thread_registry

        def handle_update(self, update):  # type: ignore[no-untyped-def]
            return bool(update.get("message"))

        def poll_once(self, limit=20):  # type: ignore[no-untyped-def]
            return {"updates": 1, "handled": 1, "limit": limit}

        def get_metrics(self):  # type: ignore[no-untyped-def]
            return {"commands_total": 3, "avg_latency_ms": 12.3}

    settings = Settings(
        runs_dir=tmp_path / "runs",
        workspace=tmp_path,
        skills_dir=tmp_path,
        telegram_enabled=True,
        telegram_mode="webhook",
        telegram_bot_token="telegram-token",
        telegram_allowed_chat_ids=["1001"],
        telegram_webhook_secret="secret-1",
    )
    store = FilesystemStore(settings.runs_dir)

    monkeypatch.setattr(app_module, "_settings", settings)
    monkeypatch.setattr(app_module, "_store", store)
    monkeypatch.setattr(app_module, "_threads", {})
    monkeypatch.setattr(app_module, "_telegram_gateway", None)
    monkeypatch.setattr(app_module, "_memory_admin", None)
    monkeypatch.setattr(app_module, "TelegramGateway", FakeTelegramGateway)

    client = TestClient(app_module.app)

    bad = client.post("/telegram/webhook", json={"message": {"text": "/help"}}, headers={})
    assert bad.status_code == 401

    ok = client.post(
        "/telegram/webhook",
        json={"message": {"text": "/help"}},
        headers={"x-telegram-bot-api-secret-token": "secret-1"},
    )
    assert ok.status_code == 200
    assert ok.json()["handled"] is True

    poll = client.post("/telegram/poll?limit=5")
    assert poll.status_code == 200
    assert poll.json()["handled"] == 1
    assert poll.json()["limit"] == 5

    metrics = client.get("/telegram/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["commands_total"] == 3


def test_memory_admin_key_control_plane_rotate_revoke_and_audit(monkeypatch, tmp_path: Path) -> None:
    from softnix_agentic_agent.api import app as app_module

    settings = Settings(
        runs_dir=tmp_path / "runs",
        workspace=tmp_path,
        skills_dir=tmp_path,
        memory_admin_key="legacy-admin",
        memory_admin_keys_path=tmp_path / ".softnix/system/keys.json",
        memory_admin_audit_path=tmp_path / ".softnix/system/audit.jsonl",
    )
    store = FilesystemStore(settings.runs_dir)

    monkeypatch.setattr(app_module, "_settings", settings)
    monkeypatch.setattr(app_module, "_store", store)
    monkeypatch.setattr(app_module, "_threads", {})
    monkeypatch.setattr(app_module, "_telegram_gateway", None)
    monkeypatch.setattr(app_module, "_memory_admin", None)

    client = TestClient(app_module.app)

    keys_before = client.get("/admin/memory/keys", headers={"x-memory-admin-key": "legacy-admin"})
    assert keys_before.status_code == 200
    assert keys_before.json()["items"] == []

    rotate = client.post(
        "/admin/memory/keys/rotate",
        headers={"x-memory-admin-key": "legacy-admin"},
        json={"new_key": "rotated-admin-1", "note": "first rotate"},
    )
    assert rotate.status_code == 200
    key_id = rotate.json()["item"]["key_id"]

    keys_after = client.get("/admin/memory/keys", headers={"x-memory-admin-key": "legacy-admin"})
    assert keys_after.status_code == 200
    assert any(item["key_id"] == key_id and item["status"] == "active" for item in keys_after.json()["items"])

    reload_with_rotated = client.post("/admin/memory/policy/reload", headers={"x-memory-admin-key": "rotated-admin-1"})
    assert reload_with_rotated.status_code == 200
    assert reload_with_rotated.json()["status"] == "reloaded"

    revoke = client.post(
        "/admin/memory/keys/revoke",
        headers={"x-memory-admin-key": "legacy-admin"},
        json={"key_id": key_id, "reason": "rotate out"},
    )
    assert revoke.status_code == 200
    assert revoke.json()["item"]["status"] == "revoked"

    reload_after_revoke = client.post("/admin/memory/policy/reload", headers={"x-memory-admin-key": "rotated-admin-1"})
    assert reload_after_revoke.status_code == 401

    audit = client.get("/admin/memory/audit?limit=20", headers={"x-memory-admin-key": "legacy-admin"})
    assert audit.status_code == 200
    actions = [item.get("action") for item in audit.json()["items"]]
    assert "rotate_key" in actions
    assert "revoke_key" in actions
