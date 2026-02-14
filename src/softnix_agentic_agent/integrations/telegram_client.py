from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


class TelegramClient:
    def __init__(self, bot_token: str, timeout_sec: float = 10.0) -> None:
        token = (bot_token or "").strip()
        if not token:
            raise ValueError("telegram bot token is required")
        self.bot_token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.file_base_url = f"https://api.telegram.org/file/bot{token}"
        self.timeout_sec = timeout_sec

    def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        resp = httpx.post(
            f"{self.base_url}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=self.timeout_sec,
        )
        resp.raise_for_status()
        return resp.json()

    def send_document(self, chat_id: str, file_path: Path, caption: str = "") -> dict[str, Any]:
        with file_path.open("rb") as fh:
            resp = httpx.post(
                f"{self.base_url}/sendDocument",
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (file_path.name, fh)},
                timeout=self.timeout_sec,
            )
        resp.raise_for_status()
        return resp.json()

    def get_updates(self, offset: int | None = None, timeout: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if offset is not None:
            payload["offset"] = offset
        resp = httpx.post(f"{self.base_url}/getUpdates", json=payload, timeout=self.timeout_sec + max(timeout, 0))
        resp.raise_for_status()
        body = resp.json()
        return list(body.get("result") or [])

    def get_file_path(self, file_id: str) -> str:
        fid = (file_id or "").strip()
        if not fid:
            raise ValueError("file_id is required")
        resp = httpx.post(
            f"{self.base_url}/getFile",
            json={"file_id": fid},
            timeout=self.timeout_sec,
        )
        resp.raise_for_status()
        body = resp.json()
        result = body.get("result") or {}
        file_path = str(result.get("file_path") or "").strip()
        if not file_path:
            raise ValueError("telegram file_path missing")
        return file_path

    def download_file_bytes(self, file_path: str) -> bytes:
        rel = str(file_path or "").strip().lstrip("/")
        if not rel:
            raise ValueError("file_path is required")
        resp = httpx.get(
            f"{self.file_base_url}/{rel}",
            timeout=self.timeout_sec * 2,
        )
        resp.raise_for_status()
        return bytes(resp.content or b"")
