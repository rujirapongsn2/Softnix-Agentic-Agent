from __future__ import annotations

from pathlib import Path
from typing import Iterable

from softnix_agentic_agent.memory.types import MemoryEntry, canonical_key
from softnix_agentic_agent.types import utc_now_iso


class MarkdownMemoryStore:
    def __init__(
        self,
        workspace: Path,
        policy_path: Path,
        profile_file: str = "memory/PROFILE.md",
        session_file: str = "memory/SESSION.md",
    ) -> None:
        self.workspace = workspace.resolve()
        self.profile_path = (self.workspace / profile_file).resolve()
        self.session_path = (self.workspace / session_file).resolve()
        self.policy_path = policy_path.resolve()

    def ensure_files(self) -> None:
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy_path.parent.mkdir(parents=True, exist_ok=True)

        self._migrate_legacy_memory_files_if_needed()

        if not self.profile_path.exists():
            self.profile_path.write_text("# PROFILE\n\n## Preferences\n", encoding="utf-8")
        if not self.session_path.exists():
            self.session_path.write_text("# SESSION\n\n## Context\n", encoding="utf-8")
        if not self.policy_path.exists():
            self.policy_path.write_text("# POLICY\n\n## Guardrails\n", encoding="utf-8")

    def load_scope(self, scope: str) -> list[MemoryEntry]:
        path = self._scope_path(scope)
        if not path.exists() or not path.is_file():
            return []
        rows: list[MemoryEntry] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            item = _parse_memory_line(line, scope)
            if item is not None:
                rows.append(item)
        return rows

    def save_scope(self, scope: str, entries: Iterable[MemoryEntry]) -> None:
        path = self._scope_path(scope)
        title = scope.upper()
        section = "Preferences" if scope == "profile" else "Context" if scope == "session" else "Guardrails"
        lines = [f"# {title}", "", f"## {section}"]
        for entry in sorted(entries, key=lambda x: x.key):
            lines.append(_serialize_memory_line(entry))
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def upsert(self, scope: str, entry: MemoryEntry) -> tuple[MemoryEntry | None, MemoryEntry]:
        if scope == "policy":
            raise PermissionError("policy memory is admin-managed only")

        rows = self.load_scope(scope)
        old: MemoryEntry | None = None
        next_rows: list[MemoryEntry] = []
        key = canonical_key(entry.key)

        for row in rows:
            if canonical_key(row.key) == key:
                old = row
                continue
            next_rows.append(row)

        final = MemoryEntry(
            scope=scope,
            kind=(entry.kind or "preference").strip() or "preference",
            key=key,
            value=str(entry.value),
            priority=int(entry.priority),
            ttl=(entry.ttl or "none").strip() or "none",
            updated_at=entry.updated_at or utc_now_iso(),
            source=(entry.source or "system").strip() or "system",
        )
        next_rows.append(final)
        self.save_scope(scope, next_rows)
        return old, final

    def delete(self, scope: str, key: str) -> MemoryEntry | None:
        if scope == "policy":
            raise PermissionError("policy memory is admin-managed only")

        rows = self.load_scope(scope)
        target = canonical_key(key)
        removed: MemoryEntry | None = None
        kept: list[MemoryEntry] = []
        for row in rows:
            if canonical_key(row.key) == target:
                removed = row
                continue
            kept.append(row)
        if removed is not None:
            self.save_scope(scope, kept)
        return removed

    def _scope_path(self, scope: str) -> Path:
        if scope == "profile":
            return self.profile_path
        if scope == "session":
            return self.session_path
        if scope == "policy":
            return self.policy_path
        raise ValueError(f"Unknown memory scope: {scope}")

    def _migrate_legacy_memory_files_if_needed(self) -> None:
        legacy_profile = (self.workspace / "PROFILE.md").resolve()
        legacy_session = (self.workspace / "SESSION.md").resolve()

        if self.profile_path != legacy_profile and (not self.profile_path.exists()) and legacy_profile.exists():
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_profile.replace(self.profile_path)

        if self.session_path != legacy_session and (not self.session_path.exists()) and legacy_session.exists():
            self.session_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_session.replace(self.session_path)


def _parse_memory_line(line: str, scope: str) -> MemoryEntry | None:
    text = line.strip()
    if not text.startswith("- "):
        return None
    body = text[2:]
    parts = [p.strip() for p in body.split("|") if p.strip()]
    fields: dict[str, str] = {}
    for part in parts:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        fields[key.strip().lower()] = value.strip()

    entry_key = canonical_key(fields.get("key", ""))
    if not entry_key:
        return None

    return MemoryEntry(
        scope=scope,
        kind=fields.get("kind", "preference"),
        key=entry_key,
        value=fields.get("value", ""),
        priority=_to_int(fields.get("priority", "50"), 50),
        ttl=fields.get("ttl", "none"),
        updated_at=fields.get("updated_at", ""),
        source=fields.get("source", "system"),
    )


def _serialize_memory_line(entry: MemoryEntry) -> str:
    return (
        f"- key:{canonical_key(entry.key)}"
        f" | value:{entry.value}"
        f" | kind:{entry.kind}"
        f" | priority:{int(entry.priority)}"
        f" | ttl:{entry.ttl}"
        f" | source:{entry.source}"
        f" | updated_at:{entry.updated_at or utc_now_iso()}"
    )


def _to_int(text: str, default: int) -> int:
    try:
        return int((text or "").strip())
    except ValueError:
        return default
