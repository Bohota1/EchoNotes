"""A client that is never available.

Used when no provider is configured. It exists so callers can always get an
`LLMClient` back from the factory and branch on `available`, instead of having
to handle `None` everywhere.
"""

from __future__ import annotations

from app.llm.base import LLMClient, LLMMessage, LLMResponse, LLMUnavailableError


class NullLLMClient(LLMClient):
    provider = "null"
    model = "none"

    def __init__(self, reason: str = "no LLM provider configured"):
        self.reason = reason

    @property
    def available(self) -> bool:
        return False

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        history: list[LLMMessage] | None = None,
    ) -> LLMResponse:
        raise LLMUnavailableError(self.reason)
