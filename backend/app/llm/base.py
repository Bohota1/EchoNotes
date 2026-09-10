"""Provider-agnostic LLM interface.

This is the single abstraction every part of EchoNotes uses to talk to a large
language model. Nothing outside `app/llm/` imports a vendor SDK, so a caller
depends on `LLMClient` and never on Anthropic, OpenAI or anything else.

Usage from another module:

    from app.llm import get_llm_client

    client = get_llm_client()
    if client.available:
        result = client.complete_json(prompt, system=SYSTEM)

`available` is the important part of the contract. Every caller is expected to
have a non-LLM path, because the deployment may legitimately have no API key.
"""

from __future__ import annotations

import abc
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant"]


class LLMError(RuntimeError):
    """Any failure while talking to a provider."""


class LLMUnavailableError(LLMError):
    """No provider is configured, or it cannot be reached.

    Callers should treat this as "fall back to rules", never as a crash.
    """


@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None
    raw: Any = field(default=None, repr=False)


class LLMClient(abc.ABC):
    """What every provider implementation must offer."""

    provider: str = "base"
    model: str = ""

    @property
    @abc.abstractmethod
    def available(self) -> bool:
        """True when a real call can be made right now (SDK importable, key set)."""

    @abc.abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        history: list[LLMMessage] | None = None,
    ) -> LLMResponse:
        """Single-turn completion. Raises LLMUnavailableError when not configured."""

    def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        """Completion whose text is parsed as JSON.

        Models reliably wrap JSON in prose or code fences even when told not to,
        so the response is repaired before parsing rather than trusted verbatim.
        """
        response = self.complete(prompt, system=system, max_tokens=max_tokens)
        return parse_json_response(response.text)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_response(text: str) -> Any:
    """Pull a JSON value out of a model response.

    Tries, in order: the raw text, the contents of a fenced code block, then the
    outermost {...} or [...] span. Raises LLMError if none of them parse, so a
    caller can fall back rather than propagate a half-parsed result.
    """
    candidates: list[str] = [text.strip()]

    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise LLMError(f"response was not JSON: {text[:200]!r}")
