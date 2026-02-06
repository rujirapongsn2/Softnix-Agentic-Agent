from __future__ import annotations

from typing import Any

import httpx

from softnix_agentic_agent.providers.base import LLMProvider
from softnix_agentic_agent.types import LLMResponse, ProviderStatus


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, api_key: str | None, base_url: str | None) -> None:
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self.base_url:
            raise ValueError("Custom/OpenAI-compatible base_url is required")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools

        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        content = choice.get("message", {}).get("content", "")
        usage = data.get("usage", {})
        normalized_usage = {
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }

        return LLMResponse(content=content, raw=data, usage=normalized_usage)

    def healthcheck(self) -> ProviderStatus:
        if not self.base_url:
            return ProviderStatus(ok=False, message="Missing base_url")
        try:
            _ = httpx.get(self.base_url, timeout=5)
            return ProviderStatus(ok=True, message="reachable")
        except Exception as exc:  # pragma: no cover
            return ProviderStatus(ok=False, message=str(exc))
