from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from softnix_agentic_agent.memory.markdown_store import MarkdownMemoryStore
from softnix_agentic_agent.memory.types import MemoryEntry, canonical_key
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.types import utc_now_iso


class CoreMemoryService:
    def __init__(
        self,
        store: MarkdownMemoryStore,
        run_store: FilesystemStore,
        run_id: str,
        inferred_min_confidence: float = 0.75,
    ) -> None:
        self.store = store
        self.run_store = run_store
        self.run_id = run_id
        self.inferred_min_confidence = float(inferred_min_confidence)

    def ensure_ready(self) -> None:
        self.store.ensure_files()

    def apply_user_text(self, text: str) -> list[dict[str, Any]]:
        instructions = _extract_instructions(text)
        changes: list[dict[str, Any]] = []
        for inst in instructions:
            if inst["op"] == "upsert":
                entry = MemoryEntry(
                    scope=str(inst["scope"]),
                    kind=str(inst.get("kind", "preference")),
                    key=str(inst["key"]),
                    value=str(inst["value"]),
                    priority=int(inst.get("priority", 70)),
                    ttl=str(inst.get("ttl", "none")),
                    source="user_explicit",
                    updated_at=utc_now_iso(),
                )
                old, new = self.store.upsert(entry.scope, entry)
                payload = {
                    "op": "upsert",
                    "scope": entry.scope,
                    "key": entry.key,
                    "old": old.value if old else None,
                    "new": new.value,
                    "actor": "user_explicit",
                    "reason": str(inst.get("reason", "")),
                }
                self.run_store.append_memory_audit(self.run_id, payload)
                changes.append(payload)
                continue

            if inst["op"] == "delete":
                scope = str(inst["scope"])
                key = str(inst["key"])
                removed = self.store.delete(scope, key)
                payload = {
                    "op": "delete",
                    "scope": scope,
                    "key": canonical_key(key),
                    "old": removed.value if removed else None,
                    "new": None,
                    "actor": "user_explicit",
                    "reason": str(inst.get("reason", "")),
                }
                self.run_store.append_memory_audit(self.run_id, payload)
                changes.append(payload)
        return changes

    def apply_confirmation_text(self, text: str) -> list[dict[str, Any]]:
        decisions = _extract_confirmation_decisions(text)
        if not decisions:
            return []

        changes: list[dict[str, Any]] = []
        pending_rows = self.store.load_scope("session")
        pending_by_key = {canonical_key(x.key): x for x in pending_rows}

        for decision in decisions:
            key = canonical_key(str(decision["key"]))
            pending_key = f"memory.pending.{key}"
            pending = pending_by_key.get(pending_key)
            if pending is None:
                continue

            if decision["action"] == "confirm":
                old_profile, new_profile = self.store.upsert(
                    "profile",
                    MemoryEntry(
                        scope="profile",
                        kind="preference",
                        key=key,
                        value=pending.value,
                        priority=max(70, int(pending.priority)),
                        ttl="none",
                        source="user_explicit",
                        updated_at=utc_now_iso(),
                    ),
                )
                self.store.delete("session", pending_key)
                payload = {
                    "op": "promote_pending",
                    "scope": "profile",
                    "key": key,
                    "old": old_profile.value if old_profile else None,
                    "new": new_profile.value,
                    "actor": "user_explicit",
                    "reason": str(decision.get("reason", "")),
                }
                self.run_store.append_memory_audit(self.run_id, payload)
                changes.append(payload)
                continue

            if decision["action"] == "reject":
                removed = self.store.delete("session", pending_key)
                payload = {
                    "op": "reject_pending",
                    "scope": "session",
                    "key": pending_key,
                    "old": removed.value if removed else None,
                    "new": None,
                    "actor": "user_explicit",
                    "reason": str(decision.get("reason", "")),
                }
                self.run_store.append_memory_audit(self.run_id, payload)
                changes.append(payload)

        return changes

    def stage_inferred_preferences(self, text: str) -> list[dict[str, Any]]:
        candidates = _extract_inferred_candidates(text)
        if not candidates:
            return []

        staged: list[dict[str, Any]] = []
        for item in candidates:
            confidence = float(item.get("confidence", 0.0))
            if confidence < self.inferred_min_confidence:
                continue
            key = canonical_key(str(item["key"]))
            pending_key = f"memory.pending.{key}"
            old, new = self.store.upsert(
                "session",
                MemoryEntry(
                    scope="session",
                    kind="preference",
                    key=pending_key,
                    value=str(item["value"]),
                    priority=int(item.get("priority", 45)),
                    ttl="session_end",
                    source="user_inferred",
                    updated_at=utc_now_iso(),
                ),
            )
            payload = {
                "op": "stage_inferred",
                "scope": "session",
                "key": pending_key,
                "old": old.value if old else None,
                "new": new.value,
                "actor": "system",
                "reason": f"{str(item.get('reason', ''))}; confidence={confidence:.2f}",
            }
            self.run_store.append_memory_audit(self.run_id, payload)
            staged.append(payload)
        return staged

    def list_pending(self) -> list[dict[str, Any]]:
        rows = self.store.load_scope("session")
        items: list[dict[str, Any]] = []
        for entry in rows:
            key = canonical_key(entry.key)
            if not key.startswith("memory.pending."):
                continue
            target = key[len("memory.pending.") :]
            items.append(
                {
                    "pending_key": key,
                    "target_key": target,
                    "value": entry.value,
                    "priority": int(entry.priority),
                    "source": entry.source,
                    "updated_at": entry.updated_at,
                }
            )
        items.sort(key=lambda x: x["target_key"])
        return items

    def compact(self, scopes: list[str] | None = None) -> dict[str, int]:
        target_scopes = scopes or ["profile", "session"]
        removed_expired = 0
        removed_duplicates = 0
        changed_scopes = 0
        now = datetime.now(timezone.utc)

        for scope in target_scopes:
            if scope not in {"profile", "session"}:
                continue
            rows = self.store.load_scope(scope)
            if not rows:
                continue

            best_by_key: dict[str, MemoryEntry] = {}
            for entry in rows:
                if entry.is_expired(now):
                    removed_expired += 1
                    continue
                key = canonical_key(entry.key)
                current = best_by_key.get(key)
                if current is None:
                    best_by_key[key] = entry
                    continue
                if _entry_is_better(entry, current):
                    best_by_key[key] = entry
                removed_duplicates += 1

            compacted = list(best_by_key.values())
            if len(compacted) != len(rows):
                changed_scopes += 1
                self.store.save_scope(scope, compacted)

        if removed_expired or removed_duplicates:
            self.run_store.append_memory_audit(
                self.run_id,
                {
                    "op": "compact",
                    "scope": ",".join(target_scopes),
                    "removed_expired": removed_expired,
                    "removed_duplicates": removed_duplicates,
                    "changed_scopes": changed_scopes,
                    "actor": "system",
                    "reason": "automatic cleanup",
                },
            )
        return {
            "removed_expired": removed_expired,
            "removed_duplicates": removed_duplicates,
            "changed_scopes": changed_scopes,
        }

    def build_prompt_context(self, max_items: int = 20) -> str:
        resolved = self.resolve_effective()
        if not resolved:
            return "- none"

        lines = []
        for key in sorted(resolved.keys())[:max_items]:
            item = resolved[key]
            lines.append(
                f"- {key}={item['value']} "
                f"(scope={item['scope']}, priority={item['priority']}, source={item['source']})"
            )
        return "\n".join(lines)

    def resolve_effective(self) -> dict[str, dict[str, Any]]:
        now = datetime.now(timezone.utc)
        merged: dict[str, dict[str, Any]] = {}
        for scope_weight, scope in ((3, "policy"), (2, "profile"), (1, "session")):
            for entry in self.store.load_scope(scope):
                if entry.is_expired(now):
                    continue
                key = canonical_key(entry.key)
                if key.startswith("memory.pending."):
                    continue
                candidate = {
                    "scope": scope,
                    "scope_weight": scope_weight,
                    "value": entry.value,
                    "priority": int(entry.priority),
                    "updated_at": entry.updated_at or "",
                    "source": entry.source,
                    "kind": entry.kind,
                }
                current = merged.get(key)
                if current is None or _is_better(candidate, current):
                    merged[key] = candidate
        return merged


def _is_better(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    c_scope = int(candidate.get("scope_weight", 0))
    x_scope = int(current.get("scope_weight", 0))
    if c_scope != x_scope:
        return c_scope > x_scope

    c_prio = int(candidate.get("priority", 0))
    x_prio = int(current.get("priority", 0))
    if c_prio != x_prio:
        return c_prio > x_prio

    c_time = str(candidate.get("updated_at", ""))
    x_time = str(current.get("updated_at", ""))
    return c_time >= x_time


def _entry_is_better(candidate: MemoryEntry, current: MemoryEntry) -> bool:
    c_prio = int(candidate.priority)
    x_prio = int(current.priority)
    if c_prio != x_prio:
        return c_prio > x_prio
    return str(candidate.updated_at or "") >= str(current.updated_at or "")


def _extract_instructions(text: str) -> list[dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return []

    rows: list[dict[str, Any]] = []

    # Explicit key/value memory: "จำไว้ว่า key = value" / "remember key=value"
    for pattern in (
        r"จำไว้ว่า\s*([A-Za-z0-9_.-]+)\s*=\s*(.+?)(?:\s+(?:for|ttl=)\s*([0-9]+[hmd]))?$",
        r"remember\s+([A-Za-z0-9_.-]+)\s*=\s*(.+?)(?:\s+(?:for|ttl=)\s*([0-9]+[hmd]))?$",
    ):
        m = re.search(pattern, raw, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            ttl = (m.group(3) or "none").strip().lower()
            rows.append(
                {
                    "op": "upsert",
                    "scope": "profile",
                    "kind": "preference",
                    "key": m.group(1),
                    "value": m.group(2).strip(),
                    "priority": 80,
                    "ttl": ttl or "none",
                    "reason": m.group(0).strip(),
                }
            )

    tone = re.search(r"(?:ตั้งโทน(?:การตอบ)?เป็น|tone\s*[:=])\s*(.+)$", raw, flags=re.IGNORECASE | re.MULTILINE)
    if tone:
        rows.append(
            {
                "op": "upsert",
                "scope": "profile",
                "kind": "preference",
                "key": "response.tone",
                "value": tone.group(1).strip(),
                "priority": 85,
                "ttl": "none",
                "reason": tone.group(0).strip(),
            }
        )

    style = re.search(r"(?:ตั้งสไตล์(?:การตอบ)?เป็น|style\s*[:=])\s*(.+)$", raw, flags=re.IGNORECASE | re.MULTILINE)
    if style:
        rows.append(
            {
                "op": "upsert",
                "scope": "profile",
                "kind": "preference",
                "key": "response.style",
                "value": style.group(1).strip(),
                "priority": 85,
                "ttl": "none",
                "reason": style.group(0).strip(),
            }
        )

    language = re.search(r"(?:ตอบ(?:กลับ)?เป็นภาษา|language\s*[:=])\s*([A-Za-zก-๙-]+)", raw, flags=re.IGNORECASE)
    if language:
        rows.append(
            {
                "op": "upsert",
                "scope": "profile",
                "kind": "preference",
                "key": "response.language",
                "value": language.group(1).strip(),
                "priority": 85,
                "ttl": "none",
                "reason": language.group(0).strip(),
            }
        )

    forget = re.search(r"(?:ลืมสิ่งนี้|ลืม)\s+([A-Za-z0-9_.-]+)", raw, flags=re.IGNORECASE)
    if forget:
        key = forget.group(1).strip()
        rows.append(
            {
                "op": "delete",
                "scope": "session",
                "key": key,
                "reason": forget.group(0).strip(),
            }
        )
        rows.append(
            {
                "op": "delete",
                "scope": "profile",
                "key": key,
                "reason": forget.group(0).strip(),
            }
        )

    # Deduplicate upserts by (scope,key), keeping last mention.
    out: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], int] = {}
    for item in rows:
        op = str(item.get("op", ""))
        key = canonical_key(str(item.get("key", "")))
        scope = str(item.get("scope", ""))
        sig = (op, scope, key)
        if sig in seen:
            out[seen[sig]] = item
            continue
        seen[sig] = len(out)
        out.append(item)
    return out


def _extract_confirmation_decisions(text: str) -> list[dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return []

    rows: list[dict[str, Any]] = []
    for pattern in (
        r"(?:ยืนยันการจดจำ|ยืนยันให้จำ|confirm memory)\s+([A-Za-z0-9_.-]+)",
        r"(?:โอเคให้จำ|ตกลงให้จำ)\s+([A-Za-z0-9_.-]+)",
    ):
        m = re.search(pattern, raw, flags=re.IGNORECASE)
        if m:
            rows.append({"action": "confirm", "key": m.group(1), "reason": m.group(0).strip()})

    for pattern in (
        r"(?:ไม่ต้องจำ|ยกเลิกการจำ|reject memory)\s+([A-Za-z0-9_.-]+)",
        r"(?:ไม่เอาให้จำ)\s+([A-Za-z0-9_.-]+)",
    ):
        m = re.search(pattern, raw, flags=re.IGNORECASE)
        if m:
            rows.append({"action": "reject", "key": m.group(1), "reason": m.group(0).strip()})
    return rows


def _extract_inferred_candidates(text: str) -> list[dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return []

    # Inferred preferences are intentionally conservative and never auto-promoted to profile.
    rows: list[dict[str, Any]] = []

    soft_concise_patterns = (
        r"(?:ขอสั้นๆ|สรุปสั้นๆ|ตอบสั้นๆ)",
        r"(?:briefly|be concise|short answer)",
    )
    if any(re.search(p, raw, flags=re.IGNORECASE) for p in soft_concise_patterns):
        rows.append(
            {
                "key": "response.verbosity",
                "value": "concise",
                "priority": 45,
                "confidence": 0.86,
                "reason": "inferred from concise preference phrase",
            }
        )

    soft_structured_patterns = (
        r"(?:ขอเป็นข้อๆ|สรุปเป็น bullet|ตอบเป็นข้อ)",
        r"(?:bullet points|in bullets)",
    )
    if any(re.search(p, raw, flags=re.IGNORECASE) for p in soft_structured_patterns):
        rows.append(
            {
                "key": "response.format.default",
                "value": "bullet-summary",
                "priority": 45,
                "confidence": 0.78,
                "reason": "inferred from structured response phrase",
            }
        )

    seen = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = canonical_key(str(row["key"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out
