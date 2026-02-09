from __future__ import annotations

from typing import Any

import httpx


class TelegramClient:
    def __init__(self, bot_token: str, timeout_sec: float = 10.0) -> None:
        token = (bot_token or "").strip()
        if not token:
            raise ValueError("telegram bot token is required")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout_sec = timeout_sec

    def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        resp = httpx.post(
            f"{self.base_url}/sendMessage",
            json={"chat_id": chat_id, "text": text},
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

