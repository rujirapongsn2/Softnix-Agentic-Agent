from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from softnix_agentic_agent.types import LLMResponse, ProviderStatus


class LLMProvider(ABC):
    @abstractmethod
    def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    def healthcheck(self) -> ProviderStatus:
        raise NotImplementedError
