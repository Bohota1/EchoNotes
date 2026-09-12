"""Builds the configured LLM client.

`get_llm_client()` always returns an `LLMClient` - never `None`. When nothing is
configured it returns a `NullLLMClient` whose `available` is False, so callers
have exactly one branch to write.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import get_settings
from app.llm.base import LLMClient
from app.llm.null_client import NullLLMClient

logger = logging.getLogger(__name__)


@lru_cache
def get_llm_client() -> LLMClient:
    settings = get_settings()

    if settings.llm_provider == "anthropic":
        from app.llm.anthropic_client import AnthropicLLMClient

        client = AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
        )
        if client.available:
            logger.info("LLM enabled: %s / %s", client.provider, client.model)
            return client
        logger.info("LLM disabled, rules only (%s)", client._unavailable_reason)
        return NullLLMClient(client._unavailable_reason or "anthropic unavailable")

    if settings.llm_provider == "groq":
        from app.llm.groq_client import GroqLLMClient

        # `llm_model` defaults to an Anthropic model id; if it was never
        # overridden for Groq, use a real Groq model instead of passing the
        # Anthropic default straight through (which would just 404). Also
        # catches `llama-3.3-70b-versatile`, which Groq retired for free/
        # developer-tier accounts in August 2026 (see console.groq.com/docs/
        # deprecations) - anyone who saved that as LLM_MODEL before this fix
        # gets upgraded automatically rather than hitting the same 404.
        model = settings.llm_model
        if model in ("claude-opus-5", "llama-3.3-70b-versatile"):
            model = "openai/gpt-oss-120b"

        client = GroqLLMClient(
            api_key=settings.groq_api_key,
            model=model,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
        )
        if client.available:
            logger.info("LLM enabled: %s / %s", client.provider, client.model)
            return client
        logger.info("LLM disabled, rules only (%s)", client._unavailable_reason)
        return NullLLMClient(client._unavailable_reason or "groq unavailable")

    if settings.llm_provider == "null":
        return NullLLMClient("llm_provider is set to 'null'")

    logger.warning("unknown llm_provider %r, running rules only", settings.llm_provider)
    return NullLLMClient(f"unknown provider {settings.llm_provider!r}")


def reset_llm_client_cache() -> None:
    """Drop the cached client. Tests use this after changing settings."""
    get_llm_client.cache_clear()
