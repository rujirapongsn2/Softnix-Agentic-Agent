from __future__ import annotations

from typing import Any

import httpx

from softnix_agentic_agent.providers.base import LLMProvider
from softnix_agentic_agent.types import LLMResponse, ProviderStatus


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str | None, base_url: str = "https://api.anthropic.com") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError("SOFTNIX_CLAUDE_API_KEY is required")
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        user_text = "\n\n".join(f"{m['role']}: {m['content']}" for m in messages)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user_text}],
        }
        if tools:
            payload["tools"] = tools

        resp = httpx.post(
            f"{self.base_url}/v1/messages",
            headers=self._headers(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        blocks = data.get("content", [])
        text_parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        content = "\n".join([x for x in text_parts if x])

        usage = data.get("usage", {})
        normalized_usage = {
            "prompt_tokens": int(usage.get("input_tokens", 0)),
            "completion_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
        }

        return LLMResponse(content=content, raw=data, usage=normalized_usage)

    def healthcheck(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(ok=False, message="Missing API key")
        return ProviderStatus(ok=True, message="configured")
