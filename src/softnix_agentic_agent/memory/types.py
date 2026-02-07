from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re


@dataclass
class MemoryEntry:
    scope: str
    kind: str
    key: str
    value: str
    priority: int = 50
    ttl: str = "none"
    updated_at: str = ""
    source: str = "system"

    def is_expired(self, now: datetime | None = None) -> bool:
        now_dt = now or datetime.now(timezone.utc)
        ttl = (self.ttl or "none").strip().lower()
        if ttl in {"", "none", "session_end"}:
            return False

        if ttl.endswith("h") or ttl.endswith("m") or ttl.endswith("d"):
            base = _parse_iso(self.updated_at)
            if base is None:
                return False
            num_part = ttl[:-1].strip()
            if not num_part.isdigit():
                return False
            amount = int(num_part)
            unit = ttl[-1]
            if unit == "h":
                limit = base + timedelta(hours=amount)
            elif unit == "m":
                limit = base + timedelta(minutes=amount)
            else:
                limit = base + timedelta(days=amount)
            return now_dt >= limit

        absolute = _parse_iso(self.ttl)
        if absolute is None:
            return False
        return now_dt >= absolute


def canonical_key(key: str) -> str:
    raw = (key or "").strip().lower()
    return re.sub(r"[^a-z0-9_.-]+", "_", raw).strip("_")


def _parse_iso(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
