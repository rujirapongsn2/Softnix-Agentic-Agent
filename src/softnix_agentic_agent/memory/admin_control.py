from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import secrets
import uuid
from typing import Any

from softnix_agentic_agent.types import utc_now_iso


@dataclass
class AdminPrincipal:
    key_id: str
    source: str


class MemoryAdminControlPlane:
    def __init__(
        self,
        keys_path: Path,
        audit_path: Path,
        legacy_admin_key: str | None = None,
        external_admin_keys: list[str] | None = None,
    ) -> None:
        self.keys_path = keys_path
        self.audit_path = audit_path
        self.legacy_admin_key = (legacy_admin_key or "").strip()
        self.external_admin_keys = [k.strip() for k in (external_admin_keys or []) if k.strip()]
        self._ensure_initialized()

    def is_configured(self) -> bool:
        return bool(self.legacy_admin_key or self.external_admin_keys or self._active_local_keys())

    def authenticate(self, provided_key: str | None) -> AdminPrincipal | None:
        candidate = (provided_key or "").strip()
        if not candidate:
            return None

        if self.legacy_admin_key and secrets.compare_digest(candidate, self.legacy_admin_key):
            return AdminPrincipal(key_id="legacy-env", source="legacy_env")

        for idx, raw in enumerate(self.external_admin_keys, start=1):
            if secrets.compare_digest(candidate, raw):
                return AdminPrincipal(key_id=f"env-{idx}", source="env")

        digest = self._hash_key(candidate)
        for item in self._active_local_keys():
            if secrets.compare_digest(digest, str(item.get("token_hash", ""))):
                self._mark_key_used(str(item.get("key_id", "")))
                return AdminPrincipal(key_id=str(item.get("key_id", "")), source="local")
        return None

    def list_keys(self) -> list[dict[str, Any]]:
        keys = self._read_payload().get("keys", [])
        output: list[dict[str, Any]] = []
        for item in keys:
            output.append(
                {
                    "key_id": item.get("key_id"),
                    "status": item.get("status"),
                    "created_at": item.get("created_at"),
                    "rotated_at": item.get("rotated_at"),
                    "revoked_at": item.get("revoked_at"),
                    "last_used_at": item.get("last_used_at"),
                    "note": item.get("note", ""),
                }
            )
        output.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
        return output

    def rotate_key(self, new_key: str, note: str, actor: AdminPrincipal) -> dict[str, Any]:
        raw = (new_key or "").strip()
        if not raw:
            raise ValueError("new key is required")
        payload = self._read_payload()
        key_id = f"k-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        payload.setdefault("keys", []).append(
            {
                "key_id": key_id,
                "token_hash": self._hash_key(raw),
                "status": "active",
                "created_at": now,
                "rotated_at": now,
                "revoked_at": None,
                "last_used_at": None,
                "note": (note or "").strip(),
            }
        )
        self._write_payload(payload)
        self.audit(
            action="rotate_key",
            actor=actor,
            status="ok",
            detail={"key_id": key_id, "note": (note or "").strip()},
        )
        return {"key_id": key_id, "status": "active", "created_at": now}

    def revoke_key(self, key_id: str, reason: str, actor: AdminPrincipal) -> dict[str, Any]:
        target = (key_id or "").strip()
        if not target:
            raise ValueError("key_id is required")
        payload = self._read_payload()
        now = utc_now_iso()
        changed: dict[str, Any] | None = None
        for item in payload.get("keys", []):
            if str(item.get("key_id", "")).strip() != target:
                continue
            item["status"] = "revoked"
            item["revoked_at"] = now
            item["revoked_reason"] = (reason or "").strip()
            changed = item
            break
        if changed is None:
            raise KeyError("key not found")
        self._write_payload(payload)
        self.audit(
            action="revoke_key",
            actor=actor,
            status="ok",
            detail={"key_id": target, "reason": (reason or "").strip()},
        )
        return {"key_id": target, "status": "revoked", "revoked_at": now}

    def audit(self, action: str, actor: AdminPrincipal | None, status: str, detail: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": utc_now_iso(),
            "action": action,
            "status": status,
            "actor_key_id": actor.key_id if actor else "",
            "actor_source": actor.source if actor else "",
            "detail": detail,
        }
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def read_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.audit_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        return rows[-max(1, limit) :]

    def _ensure_initialized(self) -> None:
        if self.keys_path.exists():
            return
        payload = {"version": 1, "keys": []}
        self.keys_path.parent.mkdir(parents=True, exist_ok=True)
        self.keys_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_payload(self) -> dict[str, Any]:
        if not self.keys_path.exists():
            return {"version": 1, "keys": []}
        try:
            data = json.loads(self.keys_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"version": 1, "keys": []}
        if not isinstance(data, dict):
            return {"version": 1, "keys": []}
        if not isinstance(data.get("keys"), list):
            data["keys"] = []
        return data

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self.keys_path.parent.mkdir(parents=True, exist_ok=True)
        self.keys_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _active_local_keys(self) -> list[dict[str, Any]]:
        payload = self._read_payload()
        keys = payload.get("keys", [])
        output: list[dict[str, Any]] = []
        for item in keys:
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "")).strip().lower() != "active":
                continue
            if not str(item.get("token_hash", "")).strip():
                continue
            output.append(item)
        return output

    def _mark_key_used(self, key_id: str) -> None:
        target = (key_id or "").strip()
        if not target:
            return
        payload = self._read_payload()
        changed = False
        for item in payload.get("keys", []):
            if str(item.get("key_id", "")).strip() != target:
                continue
            item["last_used_at"] = utc_now_iso()
            changed = True
            break
        if changed:
            self._write_payload(payload)

    def _hash_key(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

