from pathlib import Path

from softnix_agentic_agent.memory.markdown_store import MarkdownMemoryStore
from softnix_agentic_agent.memory.service import CoreMemoryService
from softnix_agentic_agent.memory.types import MemoryEntry
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.types import RunState


def _make_service(tmp_path: Path) -> CoreMemoryService:
    run_store = FilesystemStore(tmp_path / "runs")
    state = RunState(
        run_id="r1",
        task="task",
        provider="openai",
        model="m",
        workspace=str(tmp_path),
        skills_dir=str(tmp_path),
        max_iters=1,
    )
    run_store.init_run(state)
    store = MarkdownMemoryStore(workspace=tmp_path, policy_path=tmp_path / "system" / "POLICY.md")
    svc = CoreMemoryService(store=store, run_store=run_store, run_id=state.run_id, inferred_min_confidence=0.75)
    svc.ensure_ready()
    return svc


def test_apply_user_text_writes_profile_memory(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)

    changes = svc.apply_user_text("จำไว้ว่า response.tone = professional")
    assert len(changes) == 1

    profile = (tmp_path / "PROFILE.md").read_text(encoding="utf-8")
    assert "response.tone" in profile
    assert "professional" in profile


def test_apply_user_text_supports_ttl_suffix(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)

    changes = svc.apply_user_text("remember response.verbosity = concise for 8h")
    assert len(changes) == 1

    profile = (tmp_path / "PROFILE.md").read_text(encoding="utf-8")
    assert "response.verbosity" in profile
    assert "ttl:8h" in profile


def test_resolve_effective_prefers_policy_then_profile_then_session(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)

    svc.store.upsert(
        "session",
        MemoryEntry(scope="session", kind="preference", key="response.tone", value="casual", priority=60),
    )
    svc.store.upsert(
        "profile",
        MemoryEntry(scope="profile", kind="preference", key="response.tone", value="formal", priority=70),
    )

    policy_text = (
        "# POLICY\n\n## Guardrails\n"
        "- key:response.tone | value:strict | kind:constraint | priority:100 | ttl:none | source:admin | updated_at:2026-02-01T00:00:00Z\n"
    )
    (tmp_path / "system" / "POLICY.md").write_text(policy_text, encoding="utf-8")

    resolved = svc.resolve_effective()
    assert resolved["response.tone"]["value"] == "strict"
    assert resolved["response.tone"]["scope"] == "policy"


def test_compact_removes_expired_and_duplicate_rows(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)

    profile = tmp_path / "PROFILE.md"
    profile.write_text(
        "# PROFILE\n\n## Preferences\n"
        "- key:response.tone | value:old | kind:preference | priority:60 | ttl:1h | source:user_explicit | updated_at:2024-01-01T00:00:00Z\n"
        "- key:response.style | value:brief | kind:preference | priority:70 | ttl:none | source:user_explicit | updated_at:2026-02-07T00:00:00Z\n"
        "- key:response.style | value:detailed | kind:preference | priority:80 | ttl:none | source:user_explicit | updated_at:2026-02-07T01:00:00Z\n",
        encoding="utf-8",
    )

    stats = svc.compact(["profile"])
    assert stats["removed_expired"] == 1
    assert stats["removed_duplicates"] == 1
    assert stats["changed_scopes"] == 1

    after = profile.read_text(encoding="utf-8")
    assert "response.tone" not in after
    assert "value:detailed" in after


def test_stage_inferred_preferences_creates_pending_entries(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)

    staged = svc.stage_inferred_preferences("ช่วยสรุปสั้นๆ และขอเป็นข้อๆ")
    assert len(staged) == 2

    session_text = (tmp_path / "SESSION.md").read_text(encoding="utf-8")
    assert "memory.pending.response.verbosity" in session_text
    assert "memory.pending.response.format.default" in session_text


def test_confirm_pending_promotes_to_profile(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.stage_inferred_preferences("ขอสั้นๆ")

    changes = svc.apply_confirmation_text("ยืนยันให้จำ response.verbosity")
    assert len(changes) == 1
    assert changes[0]["op"] == "promote_pending"

    profile_text = (tmp_path / "PROFILE.md").read_text(encoding="utf-8")
    assert "response.verbosity" in profile_text
    assert "concise" in profile_text

    session_text = (tmp_path / "SESSION.md").read_text(encoding="utf-8")
    assert "memory.pending.response.verbosity" not in session_text


def test_reject_pending_removes_entry(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.stage_inferred_preferences("ขอสั้นๆ")

    changes = svc.apply_confirmation_text("ไม่ต้องจำ response.verbosity")
    assert len(changes) == 1
    assert changes[0]["op"] == "reject_pending"

    session_text = (tmp_path / "SESSION.md").read_text(encoding="utf-8")
    assert "memory.pending.response.verbosity" not in session_text


def test_stage_inferred_respects_confidence_threshold(tmp_path: Path) -> None:
    run_store = FilesystemStore(tmp_path / "runs")
    state = RunState(
        run_id="r2",
        task="task",
        provider="openai",
        model="m",
        workspace=str(tmp_path),
        skills_dir=str(tmp_path),
        max_iters=1,
    )
    run_store.init_run(state)
    store = MarkdownMemoryStore(workspace=tmp_path, policy_path=tmp_path / "system" / "POLICY.md")
    svc = CoreMemoryService(store=store, run_store=run_store, run_id=state.run_id, inferred_min_confidence=0.8)
    svc.ensure_ready()

    staged = svc.stage_inferred_preferences("ขอสั้นๆ และขอเป็นข้อๆ")
    assert len(staged) == 1
    assert staged[0]["key"] == "memory.pending.response.verbosity"


def test_list_pending_returns_session_pending_rows(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.stage_inferred_preferences("ขอสั้นๆ")
    items = svc.list_pending()
    assert len(items) == 1
    assert items[0]["target_key"] == "response.verbosity"
