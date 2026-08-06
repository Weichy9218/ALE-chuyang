"""
Provider-agnostic OpenAI-compatible gateway client.

The gateway (configured via ``gateway`` env vars in .env, see below) is an
OpenAI-compatible endpoint that exposes the full Responses API route and serves
the gpt-5.x reasoning models (gpt-5.6-sol, gpt-5.6-luna, ...).

The client is deliberately provider-agnostic: the class, module, and registry
name carry no vendor name. Switching providers is a localized change of the
three ``GATEWAY_*_ENV`` string values below (which .env key holds the
credentials), never a repo-wide rename. Current provider: Yihui, via
``yihui_url`` / ``yihui_api_key``. It succeeded the retired Boyue gateway; the
``boyue``/``ale`` registry aliases are kept so older configs still resolve.

Like GPTSub2APIClient, this client inherits the complete Responses API
implementation from OpenAIClient, the only route that returns reasoning
summaries when the model performs extended thinking. The gateway-specific
additions are:
  - credential resolution from the ``GATEWAY_*_ENV`` env vars
  - base-URL normalization (the .env value omits the ``/v1`` suffix the SDK needs)
  - transient-error retry for gateway hiccups (429/5xx/timeouts)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

from .base import register_llm_client
from .env_utils import load_env, resolve_client_setting
from .openai_client import OpenAIClient

load_env()

logger = logging.getLogger(__name__)

# Which .env keys hold the gateway credentials. Provider-specific values live
# here and only here; switching providers means editing these three strings.
GATEWAY_API_KEY_ENV = "yihui_api_key"
GATEWAY_BASE_URL_ENV = "yihui_url"
# By default gateway traffic bypasses the ambient proxy (see _build_sdk_client).
# Set this truthy to opt back into the http_proxy/all_proxy env from .env, e.g.
# on a network where the gateway is only reachable through the proxy.
GATEWAY_USE_PROXY_ENV = "yihui_use_proxy"

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

    The .env entry may omit ``/v1``, but the SDK appends only ``/responses`` etc.
    to whatever base it is given, so the version segment must already be present.
    This is idempotent: a base URL that already ends in ``/v1`` is left alone.
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
    "gateway",
    aliases=("boyue", "ale", "yihui"),
)
class GatewayClient(OpenAIClient):
    """Provider-agnostic gateway client using the Responses API.

    Inherits from OpenAIClient (Responses API) so gpt-5.x reasoning summaries are
    surfaced.  Only credential/base-URL resolution and a small transient-error
    retry are gateway-specific; everything else is inherited unchanged. The
    ``boyue``/``ale``/``yihui`` aliases keep older configs resolving after the
    provider naming was made generic.
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
            fallback_envs=(GATEWAY_API_KEY_ENV,),
        )
        resolved_base_url, _ = resolve_client_setting(
            base_url,
            preferred_env=base_url_env,
            fallback_envs=(GATEWAY_BASE_URL_ENV,),
        )
        if not resolved_api_key:
            raise ValueError(
                f"GatewayClient requires api_key, api_key_env, or {GATEWAY_API_KEY_ENV}"
            )
        if not resolved_base_url:
            raise ValueError(
                f"GatewayClient requires base_url, base_url_env, or {GATEWAY_BASE_URL_ENV}"
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

    def _build_sdk_client(self, *, timeout_seconds: int):
        """Build the SDK client with a direct (unproxied) HTTP transport.

        ``load_env`` propagates the local Clash proxy (``http_proxy`` /
        ``all_proxy`` = ``127.0.0.1:7897`` in .env) into the process environment,
        so httpx would otherwise tunnel every gateway call through it.  The
        gateway is directly reachable, and that personal proxy is frequently
        down — routing through it just turns each call into a
        ``Connection error``.  We therefore build the SDK's httpx client with
        ``trust_env=False`` so gateway traffic bypasses the ambient proxy.

        Set ``yihui_use_proxy=1`` to opt back into the ambient proxy env.
        """
        use_proxy = str(os.getenv(GATEWAY_USE_PROXY_ENV, "")).strip().lower() in {
            "1", "true", "yes", "on",
        }
        if use_proxy:
            return super()._build_sdk_client(timeout_seconds=timeout_seconds)

        from openai import DefaultAsyncHttpxClient, DefaultHttpxClient

        if self.async_mode:
            http_client = DefaultAsyncHttpxClient(trust_env=False, timeout=timeout_seconds)
        else:
            http_client = DefaultHttpxClient(trust_env=False, timeout=timeout_seconds)

        async_cls, sync_cls = self._sdk_client_classes()
        client_cls = async_cls if self.async_mode else sync_cls
        return client_cls(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers=self.default_headers or None,
            timeout=timeout_seconds,
            http_client=http_client,
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
                        "GatewayClient call failed after %s attempts: %s",
                        _DEFAULT_MAX_RETRIES,
                        exc,
                    )
                    raise
                wait_time = _next_retry_wait_seconds(retry_count)
                logger.warning(
                    "GatewayClient transient error (attempt %s/%s), retrying in %ss: %s",
                    retry_count,
                    _DEFAULT_MAX_RETRIES,
                    wait_time,
                    exc,
                )
                if self.async_mode:
                    await asyncio.sleep(wait_time)
                else:
                    time.sleep(wait_time)
