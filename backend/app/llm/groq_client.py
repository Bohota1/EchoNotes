"""Groq provider for the LLM abstraction.

Groq is the free option: no credit card, a free-tier key from
console.groq.com, and a generous daily request allowance running open
models (Llama 3.3 70B by default) - more than enough for a personal
note-taking app making a couple of LLM calls per captured note.

The only module in the project that imports the `groq` SDK. The import is
deferred to construction time so the package stays optional: a deployment
with no API key never needs it installed. Groq's API (and SDK shape) is
OpenAI-compatible - a `messages` list with an optional `system` role,
rather than Anthropic's separate top-level `system` parameter - which is
the one real structural difference from `AnthropicLLMClient`.
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


class GroqLLMClient(LLMClient):
    provider = "groq"

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-120b",
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
            self._unavailable_reason = "GROQ_API_KEY is not set"
            return

        try:
            import groq
        except ImportError:
            self._unavailable_reason = "the `groq` package is not installed"
            return

        self._sdk = groq
        self._client = groq.Groq(api_key=api_key, timeout=timeout)

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

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.extend({"role": m.role, "content": m.content} for m in (history or []))
        messages.append({"role": "user", "content": prompt})

        groq = self._sdk
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=max_tokens or self.default_max_tokens,
            )
        except groq.AuthenticationError as exc:
            raise LLMUnavailableError(f"authentication failed: {exc}") from exc
        except groq.PermissionDeniedError as exc:
            raise LLMUnavailableError(f"permission denied: {exc}") from exc
        except groq.NotFoundError as exc:
            raise LLMError(f"unknown model {self.model!r}: {exc}") from exc
        except groq.RateLimitError as exc:
            # Retryable, but the caller has a rule-based fallback, so surface it
            # as unavailable rather than blocking a capture on a backoff loop.
            # This is also what a free-tier daily cap looks like once it's hit.
            raise LLMUnavailableError(f"rate limited: {exc}") from exc
        except groq.APIStatusError as exc:
            raise LLMError(f"API error {exc.status_code}: {exc}") from exc
        except groq.APIConnectionError as exc:
            raise LLMUnavailableError(f"could not reach the API: {exc}") from exc

        choice = response.choices[0]
        usage = getattr(response, "usage", None)

        return LLMResponse(
            text=choice.message.content or "",
            model=response.model,
            provider=self.provider,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            stop_reason=choice.finish_reason,
            raw=response,
        )
