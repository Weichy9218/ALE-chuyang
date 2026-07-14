"""
GPT sub2api gateway client.

haoxiang.ai exposes the full OpenAI Responses API, so this client inherits
the complete Responses API implementation from OpenAIClient.  The only
gateway-specific additions are:
  - credential resolution from GPT_sub2api_* env vars
  - transparent secondary API-key fallback for rate-limit resilience
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from .base import register_llm_client
from .env_utils import load_env, resolve_client_setting, resolve_env_value
from .openai_client import OpenAIClient

load_env()

logger = logging.getLogger(__name__)

GPT_SUB2API_API_KEY_ENV = "GPT_sub2api_apikey"
GPT_SUB2API_API_KEY_ENV_2 = "GPT_sub2api_apikey_2"
GPT_SUB2API_DISABLE_SECONDARY_FALLBACK_ENV = "GPT_SUB2API_DISABLE_SECONDARY_FALLBACK"
GPT_SUB2API_BASE_URL_ENV = "GPT_sub2api_URL"

_RETRYABLE_ERROR_MARKERS = (
    "error code: 429",
    "error code: 500",
    "error code: 502",
    "error code: 503",
    "error code: 504",
    "rate limit",
    "service temporarily unavailable",
    "temporarily unavailable",
    "timeout",
)


def _is_retryable_gateway_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _RETRYABLE_ERROR_MARKERS)


@register_llm_client("gpt_sub2api")
class GPTSub2APIClient(OpenAIClient):
    """Gateway client for haoxiang.ai using the Responses API.

    Inherits from OpenAIClient (Responses API) because haoxiang.ai exposes the
    full Responses API route — the only path that returns reasoning summaries when
    the model performs extended thinking.  The secondary-key fallback is the only
    gateway-specific behavior; everything else is inherited unchanged.
    """

    DEFAULT_MODEL = "gpt-5.4"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        temperature: Optional[float] = 0.2,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key_env: Optional[str] = None,
        base_url_env: Optional[str] = None,
        max_tokens: Optional[int] = 4096,
        reasoning_effort: Optional[str] = None,
        async_mode: bool = True,
        **kwargs: Any,
    ) -> None:
        resolved_api_key, api_key_source = resolve_client_setting(
            api_key,
            preferred_env=api_key_env,
            fallback_envs=(GPT_SUB2API_API_KEY_ENV, GPT_SUB2API_API_KEY_ENV_2),
        )
        resolved_base_url, _ = resolve_client_setting(
            base_url,
            preferred_env=base_url_env,
            fallback_envs=(GPT_SUB2API_BASE_URL_ENV,),
        )
        if not resolved_api_key:
            raise ValueError(
                f"GPTSub2APIClient requires api_key, api_key_env, or {GPT_SUB2API_API_KEY_ENV}"
            )
        if not resolved_base_url:
            raise ValueError(
                f"GPTSub2APIClient requires base_url, base_url_env, or {GPT_SUB2API_BASE_URL_ENV}"
            )

        super().__init__(
            model=model,
            temperature=temperature,
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            async_mode=async_mode,
            **kwargs,
        )
        self._fallback_client: Any = None
        self._fallback_api_key_source: Optional[str] = None
        self._maybe_init_secondary_key_fallback(
            explicit_api_key=api_key,
            requested_api_key_env=api_key_env,
            primary_api_key=resolved_api_key,
            primary_api_key_source=api_key_source,
        )

    def _maybe_init_secondary_key_fallback(
        self,
        *,
        explicit_api_key: Optional[str],
        requested_api_key_env: Optional[str],
        primary_api_key: str,
        primary_api_key_source: str,
    ) -> None:
        """Build a fallback SDK client from the secondary API key when applicable."""
        if str(os.getenv(GPT_SUB2API_DISABLE_SECONDARY_FALLBACK_ENV, "")).strip().lower() in {
            "1", "true", "yes", "on",
        }:
            return
        if explicit_api_key is not None:
            return
        requested_env = str(requested_api_key_env or "").strip()
        if requested_env and requested_env != GPT_SUB2API_API_KEY_ENV:
            return
        if primary_api_key_source == GPT_SUB2API_API_KEY_ENV_2:
            return
        secondary_key = resolve_env_value(GPT_SUB2API_API_KEY_ENV_2)
        if not secondary_key or secondary_key == primary_api_key:
            return

        from openai import AsyncOpenAI, OpenAI
        client_cls = AsyncOpenAI if self.async_mode else OpenAI
        self._fallback_client = client_cls(
            api_key=secondary_key,
            base_url=self.base_url,
            default_headers=self.default_headers or None,
            timeout=180,
        )
        self._fallback_api_key_source = GPT_SUB2API_API_KEY_ENV_2

    async def _create_response(self, params: Dict[str, Any]):
        """Responses API call with transparent secondary-key fallback on gateway errors."""
        try:
            return await super()._create_response(params)
        except Exception as exc:
            if self._fallback_client is None or not _is_retryable_gateway_error(exc):
                raise
            logger.warning(
                "GPTSub2APIClient primary key hit retryable error; trying %s fallback: %s",
                self._fallback_api_key_source,
                exc,
            )

        response = await self._do_responses_create(self._fallback_client, params)
        logger.info("GPTSub2APIClient recovered via %s", self._fallback_api_key_source)
        return response

    async def aclose(self) -> None:
        await super().aclose()
        if self._fallback_client is not None:
            if self.async_mode and hasattr(self._fallback_client, "close"):
                await self._fallback_client.close()
            elif hasattr(self._fallback_client, "close"):
                self._fallback_client.close()
            self._fallback_client = None
