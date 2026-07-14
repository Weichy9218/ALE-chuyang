"""
Low-cost OpenRouter test client.

This is intentionally just a thin preset over OpenRouterNewAPIClient:
- same chat-completions transport and compatibility behavior
- cheaper default model
- longer timeout for ad-hoc manual testing
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import register_llm_client
from .openrouter_newapi_client import OpenRouterNewAPIClient


@register_llm_client("openrouter_test", aliases=("OpenRouterTest",))
class OpenRouterTestClient(OpenRouterNewAPIClient):
    """Cheap OpenRouter preset for quick smoke tests and manual debugging."""

    DEFAULT_MODEL = "openai/gpt-4.1-mini"
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_TIMEOUT_SECONDS = 300

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.7,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        extra_headers: Optional[Dict[str, str]] = None,
        async_mode: bool = True,
        **kwargs: Any,
    ):
        super().__init__(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            extra_headers=extra_headers,
            async_mode=async_mode,
            timeout_seconds=self.DEFAULT_TIMEOUT_SECONDS,
            **kwargs,
        )
