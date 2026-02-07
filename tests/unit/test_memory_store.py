from pathlib import Path

from softnix_agentic_agent.memory.markdown_store import MarkdownMemoryStore
from softnix_agentic_agent.memory.types import MemoryEntry


def test_markdown_store_upsert_delete_and_reload(tmp_path: Path) -> None:
    policy = tmp_path / "system" / "POLICY.md"
    store = MarkdownMemoryStore(workspace=tmp_path, policy_path=policy)
    store.ensure_files()

    old, new = store.upsert(
        "profile",
        MemoryEntry(scope="profile", kind="preference", key="response.tone", value="friendly", priority=80),
    )
    assert old is None
    assert new.key == "response.tone"

    rows = store.load_scope("profile")
    assert len(rows) == 1
    assert rows[0].value == "friendly"

    removed = store.delete("profile", "response.tone")
    assert removed is not None
    assert store.load_scope("profile") == []


def test_markdown_store_blocks_policy_write(tmp_path: Path) -> None:
    store = MarkdownMemoryStore(workspace=tmp_path, policy_path=tmp_path / "system" / "POLICY.md")
    store.ensure_files()

    try:
        store.upsert(
            "policy",
            MemoryEntry(scope="policy", kind="constraint", key="policy.lock", value="true", priority=100),
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("policy upsert should be blocked")
