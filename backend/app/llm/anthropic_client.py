"""Anthropic provider for the LLM abstraction.

The only module in the project that imports the `anthropic` SDK. The import is
deferred to construction time so the package stays optional: a deployment with
no API key never needs it installed.
"""

from __future__ import annotations

import logging

from app.llm.base import (
    LLMClient,
    LLMError,
    LLMMessage,
    LLMResponse,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)


class AnthropicLLMClient(LLMClient):
    provider = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-opus-5",
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ):
        self.model = model
        self.default_max_tokens = max_tokens
        self._api_key = api_key
        self._timeout = timeout
        self._client = None
        self._unavailable_reason: str | None = None

        if not api_key:
            self._unavailable_reason = "ANTHROPIC_API_KEY is not set"
            return

        try:
            import anthropic
        except ImportError:
            self._unavailable_reason = "the `anthropic` package is not installed"
            return

        self._sdk = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

    @property
    def available(self) -> bool:
        return self._client is not None

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        history: list[LLMMessage] | None = None,
    ) -> LLMResponse:
        if self._client is None:
            raise LLMUnavailableError(self._unavailable_reason or "client not initialised")

        messages: list[dict] = [
            {"role": m.role, "content": m.content} for m in (history or [])
        ]
        messages.append({"role": "user", "content": prompt})

        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens or self.default_max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        anthropic = self._sdk
        try:
            response = self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailableError(f"authentication failed: {exc}") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMUnavailableError(f"permission denied: {exc}") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"unknown model {self.model!r}: {exc}") from exc
        except anthropic.RateLimitError as exc:
            # Retryable, but the caller has a rule-based fallback, so surface it
            # as unavailable rather than blocking a capture on a backoff loop.
            raise LLMUnavailableError(f"rate limited: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"API error {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError(f"could not reach the API: {exc}") from exc

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )

        return LLMResponse(
            text=text,
            model=response.model,
            provider=self.provider,
            input_tokens=getattr(response.usage, "input_tokens", 0),
            output_tokens=getattr(response.usage, "output_tokens", 0),
            stop_reason=response.stop_reason,
            raw=response,
        )
