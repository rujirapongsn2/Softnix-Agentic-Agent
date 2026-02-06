from __future__ import annotations

from typing import Any

from softnix_agentic_agent.providers.openai_compatible_provider import OpenAICompatibleProvider
from softnix_agentic_agent.types import LLMResponse


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None, base_url: str = "https://api.openai.com/v1") -> None:
        super().__init__(api_key=api_key, base_url=base_url)

    def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self.api_key:
            raise ValueError("SOFTNIX_OPENAI_API_KEY is required for provider=openai")
        if model.lower().startswith("claude"):
            raise ValueError(
                "Model looks like Claude but provider is openai. Use --provider claude or a compatible custom endpoint."
            )
        return super().generate(
            messages=messages,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
