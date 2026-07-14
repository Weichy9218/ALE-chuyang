"""
Boyue (ALE) gateway client.

``apirx.boyuerichdata.com`` (configured via ``ale_url`` / ``ale_api_key`` in
.env) is an OpenAI-compatible gateway that exposes the full Responses API route
and serves the gpt-5.x reasoning models (gpt-5.6-sol, gpt-5.6-luna, ...).

Like GPTSub2APIClient, this client inherits the complete Responses API
implementation from OpenAIClient — the only route that returns reasoning
summaries when the model performs extended thinking.  The gateway-specific
additions are:
  - credential resolution from ``ale_api_key`` / ``ale_url`` env vars
  - base-URL normalization (the .env value omits the ``/v1`` suffix the SDK needs)
  - transient-error retry for gateway hiccups (429/5xx/timeouts)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from .base import register_llm_client
from .env_utils import load_env, resolve_client_setting
from .openai_client import OpenAIClient

load_env()

logger = logging.getLogger(__name__)

BOYUE_API_KEY_ENV = "ale_api_key"
BOYUE_BASE_URL_ENV = "ale_url"

_DEFAULT_MAX_RETRIES = 3
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
    "connection error",
)


def _is_retryable_gateway_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _RETRYABLE_ERROR_MARKERS)


def _normalize_base_url(base_url: Optional[str]) -> Optional[str]:
    """Ensure the base URL carries the ``/v1`` suffix the OpenAI SDK expects.

    The .env entry is ``https://apirx.boyuerichdata.com/`` (no ``/v1``), but the
    SDK appends only ``/responses`` etc. to whatever base it is given, so the
    version segment must already be present.
    """
    candidate = str(base_url or "").strip()
    if not candidate:
        return None
    candidate = candidate.rstrip("/")
    if not candidate.endswith("/v1"):
        candidate = f"{candidate}/v1"
    return candidate


def _next_retry_wait_seconds(retry_count: int) -> int:
    return min(2 * (2 ** min(retry_count - 1, 2)), 20)


@register_llm_client(
    "boyue_api",
    aliases=("boyue", "boyueapi", "BoyueAPI", "ale"),
)
class BoyueAPIClient(OpenAIClient):
    """Gateway client for apirx.boyuerichdata.com using the Responses API.

    Inherits from OpenAIClient (Responses API) so gpt-5.x reasoning summaries are
    surfaced.  Only credential/base-URL resolution and a small transient-error
    retry are gateway-specific; everything else is inherited unchanged.
    """

    DEFAULT_MODEL = "gpt-5.6-sol"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        temperature: Optional[float] = 0.7,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key_env: Optional[str] = None,
        base_url_env: Optional[str] = None,
        max_tokens: Optional[int] = 4096,
        reasoning_effort: Optional[str] = "medium",
        async_mode: bool = True,
        **kwargs: Any,
    ) -> None:
        resolved_api_key, _ = resolve_client_setting(
            api_key,
            preferred_env=api_key_env,
            fallback_envs=(BOYUE_API_KEY_ENV,),
        )
        resolved_base_url, _ = resolve_client_setting(
            base_url,
            preferred_env=base_url_env,
            fallback_envs=(BOYUE_BASE_URL_ENV,),
        )
        if not resolved_api_key:
            raise ValueError(
                f"BoyueAPIClient requires api_key, api_key_env, or {BOYUE_API_KEY_ENV}"
            )
        if not resolved_base_url:
            raise ValueError(
                f"BoyueAPIClient requires base_url, base_url_env, or {BOYUE_BASE_URL_ENV}"
            )

        super().__init__(
            model=model,
            temperature=temperature,
            api_key=resolved_api_key,
            base_url=_normalize_base_url(resolved_base_url),
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            async_mode=async_mode,
            **kwargs,
        )

    async def _create_response(self, params: Dict[str, Any]):
        """Responses API call with a small retry on transient gateway errors."""
        retry_count = 0
        while True:
            try:
                return await super()._create_response(params)
            except Exception as exc:
                if not _is_retryable_gateway_error(exc):
                    raise
                retry_count += 1
                if retry_count >= _DEFAULT_MAX_RETRIES:
                    logger.error(
                        "BoyueAPIClient call failed after %s attempts: %s",
                        _DEFAULT_MAX_RETRIES,
                        exc,
                    )
                    raise
                wait_time = _next_retry_wait_seconds(retry_count)
                logger.warning(
                    "BoyueAPIClient transient error (attempt %s/%s), retrying in %ss: %s",
                    retry_count,
                    _DEFAULT_MAX_RETRIES,
                    wait_time,
                    exc,
                )
                if self.async_mode:
                    await asyncio.sleep(wait_time)
                else:
                    time.sleep(wait_time)
