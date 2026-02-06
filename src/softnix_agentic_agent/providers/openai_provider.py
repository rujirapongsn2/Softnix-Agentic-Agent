from __future__ import annotations

from softnix_agentic_agent.providers.openai_compatible_provider import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None, base_url: str = "https://api.openai.com/v1") -> None:
        super().__init__(api_key=api_key, base_url=base_url)
