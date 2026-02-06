from __future__ import annotations

from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.providers.base import LLMProvider
from softnix_agentic_agent.providers.claude_provider import ClaudeProvider
from softnix_agentic_agent.providers.openai_compatible_provider import OpenAICompatibleProvider
from softnix_agentic_agent.providers.openai_provider import OpenAIProvider


def create_provider(name: str, settings: Settings) -> LLMProvider:
    provider_name = name.lower().strip()
    if provider_name == "openai":
        return OpenAIProvider(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    if provider_name == "claude":
        return ClaudeProvider(api_key=settings.claude_api_key, base_url=settings.claude_base_url)
    if provider_name in {"custom", "openai-compatible", "openai_compatible"}:
        return OpenAICompatibleProvider(api_key=settings.custom_api_key, base_url=settings.custom_base_url)
    raise ValueError(f"Unsupported provider: {name}")
