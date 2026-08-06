"""Unified LLM client exports and registry helpers."""

from .base import (
    BaseLLMClient,
    LLMResponse,
    ASSISTANT_MESSAGE_EXTRA_FIELDS,
    get_llm_client_class,
    instantiate_llm_client,
    resolve_llm_client_name,
)
from .gateway_client import GatewayClient
from .gpt_sub2api_client import GPTSub2APIClient
from .openrouter_newapi_client import OpenRouterNewAPIClient
from .openai_client import OpenAIClient
from .openrouter_test_client import OpenRouterTestClient

__all__ = [
    "BaseLLMClient",
    "LLMResponse",
    "ASSISTANT_MESSAGE_EXTRA_FIELDS",
    "get_llm_client_class",
    "instantiate_llm_client",
    "resolve_llm_client_name",
    "GatewayClient",
    "GPTSub2APIClient",
    "OpenRouterNewAPIClient",
    "OpenAIClient",
    "OpenRouterTestClient",
]
