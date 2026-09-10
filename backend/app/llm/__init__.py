"""Shared LLM abstraction.

Other modules should import from here, not from a provider module:

    from app.llm import get_llm_client, LLMUnavailableError
"""

from app.llm.base import (
    LLMClient,
    LLMError,
    LLMMessage,
    LLMResponse,
    LLMUnavailableError,
    parse_json_response,
)
from app.llm.factory import get_llm_client, reset_llm_client_cache
from app.llm.null_client import NullLLMClient

__all__ = [
    "LLMClient",
    "LLMError",
    "LLMMessage",
    "LLMResponse",
    "LLMUnavailableError",
    "NullLLMClient",
    "get_llm_client",
    "reset_llm_client_cache",
    "parse_json_response",
]
