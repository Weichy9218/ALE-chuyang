"""Web search + web fetch tools.

Two BaseTool subclasses:
  - :class:`WebSearchTool` — Exa Search API (primary) with a Firecrawl
    fallback; both keyed from env vars.
  - :class:`WebFetchTool` — HTTP(S) fetch with SSRF guard, Readability-based
    extraction, basic-HTML fallback, HTML→markdown conversion, and a
    per-process TTL cache.

Adapted from OpenClaw's ``web-search.ts`` / ``web-fetch.ts`` /
``web-guarded-fetch.ts`` / ``web-fetch-utils.ts`` / ``web-shared.ts``.

Kept:
  - Web-search schema params ``query``/``count``/``freshness``/``country``/
    ``date_after``. ``freshness``/``country`` are accepted but not consumed by
    the Exa/Firecrawl backends; ``date_after`` maps to Exa
    ``startPublishedDate``.
  - SSRF guard: http(s) only, reject private/loopback/link-local/multicast/
    reserved/unspecified on every resolved IP before fetch.
  - Redirect + timeout + max-response-bytes caps.
  - maxChars + truncation marker.
  - Readability → basic-HTML fallback → raw — matches OpenClaw's 3-tier
    extraction (``extractReadableContent`` → ``extractBasicHtmlContent``).
  - ``htmlToMarkdown`` conversion via ``markdownify``.
  - Per-process ``FETCH_CACHE`` + ``SEARCH_CACHE`` with TTL (5m search,
    10m fetch), matches ``web-shared.ts::CacheEntry``.

Dropped:
  - Multi-provider framework, runtime credential scoping, plugin manifest.
  - ``wrapWebContent`` untrusted-content wrapper (benchmark harness; single
    tenant; revisit when we host untrusted tasks).
  - Cloudflare Markdown-for-Agents header branch.
  - Provider-fallback on extraction failure (single provider).

Known limitation: SSRF guard resolves DNS once and then trusts aiohttp to
connect to a fresh resolution. DNS-rebinding attacks between check and
connect are not prevented. Benchmark harness; accepted. OpenClaw's
``fetchWithSsrFGuard`` pins the resolved address into the socket via a
custom ``LookupFn`` — follow-up story if we ever ingest untrusted task
authors.
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import json
import logging
import os
import re
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional, Union
from urllib.parse import urlparse

from agent.tools.base import BaseTool, register_tool

from ._tool_utils import _get_required_str, _run_async

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants (match OpenClaw web-fetch.ts:43-51 / web-shared.ts defaults)
# ---------------------------------------------------------------------------

# web_search backends: Exa is primary, Firecrawl is the fallback.
EXA_SEARCH_URL = "https://api.exa.ai/search"
FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v1/search"

# Chars kept from an Exa result's ``text`` body when it has no highlight,
# used as the result ``description`` snippet.
_EXA_SNIPPET_MAX_CHARS = 300

_DEFAULT_SEARCH_COUNT = 5
_MAX_SEARCH_COUNT = 20

_DEFAULT_FETCH_MAX_CHARS = 20_000
_MAX_FETCH_MAX_CHARS = 100_000
_DEFAULT_FETCH_MAX_RESPONSE_BYTES = 750_000  # matches OpenClaw DEFAULT_FETCH_MAX_RESPONSE_BYTES
_DEFAULT_FETCH_MAX_REDIRECTS = 3              # matches DEFAULT_FETCH_MAX_REDIRECTS
_DEFAULT_FETCH_TIMEOUT_SECONDS = 30
_DEFAULT_SEARCH_TIMEOUT_SECONDS = 10

# Matches OpenClaw DEFAULT_FETCH_USER_AGENT (web-fetch.ts:50-51)
_DEFAULT_FETCH_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_SEARCH_CACHE_TTL_SECONDS = 5 * 60
_FETCH_CACHE_TTL_SECONDS = 10 * 60

_VALID_FRESHNESS = {"pd", "pw", "pm", "py"}
_DATE_AFTER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# TTL cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    value: dict
    expires_at: float


class _TTLCache:
    """Simple per-process TTL dict. Thread-safe.

    Mirrors OpenClaw ``web-shared.ts::CacheEntry`` — a flat key→(value, exp)
    map with lazy expiry on read.
    """

    def __init__(self) -> None:
        self._data: dict[Any, _CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Optional[dict]:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._data.pop(key, None)
                return None
            return entry.value

    def set(self, key: Any, value: dict, ttl_seconds: float) -> None:
        with self._lock:
            self._data[key] = _CacheEntry(
                value=value,
                expires_at=time.monotonic() + ttl_seconds,
            )

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_SEARCH_CACHE = _TTLCache()
_FETCH_CACHE = _TTLCache()


# ---------------------------------------------------------------------------
# Host denylist (answer-leak guard)
# ---------------------------------------------------------------------------
# Hosts (and their subdomains) the agent must never reach: the benchmark's own
# site could expose task prompts or reference answers. Applied in two places —
# web_search filters matching results out before the model ever sees the link,
# and web_fetch rejects the URL both pre-fetch and after every redirect. Extra
# suffixes can be added via the ALE_BLOCKED_HOST_SUFFIXES env var (comma-
# separated); the benchmark host is always blocked regardless of env.
_ALWAYS_BLOCKED_HOST_SUFFIXES = ("agents-last-exam.org",)


def _blocked_host_suffixes() -> tuple[str, ...]:
    extra = os.environ.get("ALE_BLOCKED_HOST_SUFFIXES", "")
    parsed = tuple(
        h.strip().lower().lstrip(".") for h in extra.split(",") if h.strip()
    )
    return _ALWAYS_BLOCKED_HOST_SUFFIXES + parsed


def _host_is_blocked(host: str) -> bool:
    """True if ``host`` equals or is a subdomain of any blocked suffix."""
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return False
    return any(h == s or h.endswith("." + s) for s in _blocked_host_suffixes())


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

# Order matters: Python's ``is_private`` returns True for loopback /
# link-local / multicast / unspecified too, so specific predicates must be
# checked first to surface the most informative label in the error message.
_BLOCKED_IP_PREDICATES = (
    "is_loopback",
    "is_link_local",
    "is_multicast",
    "is_unspecified",
    "is_reserved",
    "is_private",
)


def _assert_url_safe(url: str) -> None:
    """Reject the URL if it is unsafe to fetch.

    Rules (match OpenClaw ``infra/net/ssrf.ts`` policy):
      - Must have a parseable URL.
      - Scheme must be ``http`` or ``https``.
      - Must have a host.
      - Every resolved IP must pass: not private, not loopback, not
        link-local (covers 169.254.169.254 cloud-metadata), not multicast,
        not reserved, not unspecified.

    Raises :class:`ValueError` on rejection so ``call()`` turns it into a
    structured tool error.
    """
    try:
        parsed = urlparse(url)
    except ValueError as e:
        raise ValueError(f"Invalid URL {url!r}: {e}") from e
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError(
            f"URL scheme {scheme!r} is not allowed (only http/https)."
        )
    host = parsed.hostname
    if not host:
        raise ValueError(f"URL {url!r} is missing a host.")

    # Answer-leak guard: reject the benchmark's own host (and configured extras)
    # before any DNS/fetch. Re-checked on the post-redirect final URL by the
    # caller, so a redirect into the blocked host is caught too.
    if _host_is_blocked(host):
        raise ValueError(
            f"URL {url!r} is on the blocked-host denylist (answer-leak guard)."
        )

    # Bare-IP URLs: check the literal first — cheaper and no DNS involved.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        _assert_ip_safe(literal, url, host)
        return

    # Hostname → resolve and inspect every returned IP.
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"DNS resolution failed for host {host!r}: {e}") from e

    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0] if sockaddr else ""
        if not ip_str or ip_str in seen:
            continue
        seen.add(ip_str)
        # IPv6 scope-id suffix: "fe80::1%eth0" — strip before parsing.
        ip_clean = ip_str.split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(ip_clean)
        except ValueError as e:
            raise ValueError(
                f"Could not parse resolved IP {ip_str!r} for {host!r}: {e}"
            ) from e
        _assert_ip_safe(ip, url, host)


def _assert_ip_safe(
    ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address],
    url: str,
    host: str,
) -> None:
    for pred in _BLOCKED_IP_PREDICATES:
        if getattr(ip, pred, False):
            raise ValueError(
                f"URL {url!r} resolves to blocked address {ip.compressed} "
                f"({pred.removeprefix('is_')}) for host {host!r}."
            )


# ---------------------------------------------------------------------------
# HTML extraction helpers
# ---------------------------------------------------------------------------


def _extract_with_readability(html: str, url: str) -> Optional[dict]:
    """Run ``readability-lxml`` and return ``{"title", "html"}`` on success.

    Returns ``None`` if readability is unavailable or returns empty content.
    """
    try:
        from readability import Document  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("readability-lxml not installed; skipping to basic fallback")
        return None
    try:
        doc = Document(html, url=url)
        title = (doc.short_title() or "").strip() or None
        summary_html = doc.summary(html_partial=True) or ""
    except Exception as e:  # noqa: BLE001 — readability is lenient; protect the path
        logger.info("readability failed on %s: %s", url, e)
        return None
    if not summary_html.strip():
        return None
    return {"title": title, "html": summary_html}


def _extract_basic_html(html: str) -> Optional[dict]:
    """Fallback extractor using bs4 + html5lib (both already core deps).

    Strips script/style/nav/footer/aside/header then ``get_text`` with a
    newline separator, collapses runs of blank lines. Returns
    ``{"title", "text"}`` or ``None`` if nothing useful was extracted.
    """
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("beautifulsoup4 not installed; basic-HTML fallback unavailable")
        return None
    try:
        soup = BeautifulSoup(html, "html5lib")
    except Exception as e:  # noqa: BLE001
        logger.info("bs4 parse failed: %s", e)
        return None
    for selector in ("script", "style", "nav", "footer", "aside", "header", "noscript"):
        for node in soup.find_all(selector):
            node.decompose()
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None
    text = soup.get_text(separator="\n")
    # Collapse runs of 2+ blank lines to a single blank line.
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
    if not text:
        return None
    return {"title": title or None, "text": text}


def _html_to_markdown(html: str) -> str:
    """HTML → Markdown via ``markdownify``.

    Falls back to bs4's ``get_text`` (or the raw HTML) if ``markdownify``
    isn't installed so the fetch path keeps working.
    """
    try:
        from markdownify import markdownify as md  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("markdownify not installed; returning text extraction")
        basic = _extract_basic_html(html)
        return (basic or {}).get("text", html)
    try:
        return md(html, heading_style="ATX").strip()
    except Exception as e:  # noqa: BLE001
        logger.info("markdownify failed: %s", e)
        return html


def _truncate_with_marker(text: str, max_chars: int) -> tuple[str, bool]:
    """Hard-cap ``text`` to ``max_chars`` with a tail marker.

    Returns ``(truncated_text, was_truncated)``.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    marker = "\n\n... [truncated {} chars]"
    # Reserve room for the marker so the final string fits under max_chars.
    marker_len = len(marker.format(10**9))  # over-reserve
    keep = max(0, max_chars - marker_len)
    omitted = len(text) - keep
    return text[:keep] + marker.format(omitted), True


# ---------------------------------------------------------------------------
# Param validation helpers
# ---------------------------------------------------------------------------


def _resolve_int(raw: object, default: int, *, min_: int, max_: int) -> int:
    """Clamp ``raw`` to ``[min_, max_]`` if it's a finite number; else default."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return default
    if raw <= 0:
        return default
    val = int(raw)
    return max(min_, min(max_, val))


def _normalize_search_params(
    freshness_raw: object,
    country_raw: object,
    date_after_raw: object,
) -> tuple[Optional[tuple], Optional[str], Optional[str]]:
    """Normalize the optional search params. Never raises.

    Returns ``(freshness_param, country, start_published_date)``:

    - ``freshness_param`` — an opaque cache token (or ``None``) folding the
      recognized ``freshness`` bucket together with ``start_published_date`` so
      the ``_SEARCH_CACHE`` key keeps discriminating both time filters, exactly
      as it did when ``date_after`` was baked into the old freshness string.
      Not sent to any provider.
    - ``country`` — upper-cased ISO code when a non-empty string, else ``None``.
      Kept for the cache key + schema back-compat; the providers ignore it.
    - ``start_published_date`` — ``date_after`` (``YYYY-MM-DD``) rendered as an
      ISO-8601 timestamp for Exa's ``startPublishedDate``, else ``None``.

    ``freshness`` (``pd|pw|pm|py``) is accepted for schema back-compat but Exa/
    Firecrawl don't consume it. Unsupported or malformed values are skipped
    rather than raised — Exa/Firecrawl silently ignore params they don't take,
    so web_search does the same instead of erroring on them.
    """
    freshness: Optional[str] = None
    if isinstance(freshness_raw, str):
        candidate = freshness_raw.strip().lower()
        if candidate in _VALID_FRESHNESS:
            freshness = candidate

    country: Optional[str] = None
    if isinstance(country_raw, str) and country_raw.strip():
        country = country_raw.strip().upper()

    start_published_date: Optional[str] = None
    if isinstance(date_after_raw, str):
        candidate = date_after_raw.strip()
        if _DATE_AFTER_RE.match(candidate):
            start_published_date = f"{candidate}T00:00:00.000Z"

    if freshness is None and start_published_date is None:
        freshness_param: Optional[tuple] = None
    else:
        freshness_param = (freshness, start_published_date)
    return freshness_param, country, start_published_date


# ---------------------------------------------------------------------------
# web_search providers (Exa primary, Firecrawl fallback)
# ---------------------------------------------------------------------------
# Structured for offline unit-testing: the two ``_search_*`` coroutines are the
# only network surface. Response mapping (``_map_*``), denylist filtering +
# truncation (``_filter_and_truncate``) and provider selection
# (``_run_web_search``) are pure and monkeypatchable without a socket.


def _map_exa_results(payload: object) -> list[dict[str, str]]:
    """Map an Exa ``/search`` payload → ``[{title,url,description}]``.

    Defensive: tolerates a non-dict payload, a missing/non-list ``results``,
    non-dict rows, and missing fields. ``description`` is the first non-empty
    highlight when present, else a short snippet of the result ``text``, else
    ``""``. Not host-filtered here — that happens in ``_filter_and_truncate``.
    """
    if not isinstance(payload, dict):
        return []
    raw = payload.get("results")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        description = ""
        highlights = r.get("highlights")
        if isinstance(highlights, list):
            for h in highlights:
                if isinstance(h, str) and h.strip():
                    description = h.strip()
                    break
        if not description:
            text = r.get("text")
            if isinstance(text, str) and text.strip():
                description = text.strip()[:_EXA_SNIPPET_MAX_CHARS]
        out.append(
            {
                "title": r.get("title") or "",
                "url": r.get("url") or "",
                "description": description,
            }
        )
    return out


def _map_firecrawl_results(payload: object) -> list[dict[str, str]]:
    """Map a Firecrawl ``/v1/search`` payload → ``[{title,url,description}]``.

    Defensive over a non-dict payload, a missing/non-list ``data``, and
    non-dict rows. Not host-filtered here.
    """
    if not isinstance(payload, dict):
        return []
    raw = payload.get("data")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "title": r.get("title") or "",
                "url": r.get("url") or "",
                "description": r.get("description") or "",
            }
        )
    return out


def _filter_and_truncate(raw_results: list, count: int) -> list[dict[str, str]]:
    """Drop blocked-host results (answer-leak guard) and cap to ``count``.

    Pure + synchronous: no network, no provider specifics — so mapping +
    denylist + truncation are unit-testable in isolation. Applied to results
    from BOTH providers (Exa and Firecrawl) before they are returned, so a
    blocked host never reaches the model regardless of which provider served.
    """
    out: list[dict[str, str]] = []
    for r in raw_results:
        if len(out) >= count:
            break
        if not isinstance(r, dict):
            continue
        url = r.get("url") or ""
        # Drop blocked hosts before the model sees the link (answer-leak guard).
        if _host_is_blocked(urlparse(url).hostname or ""):
            continue
        out.append(
            {
                "title": r.get("title") or "",
                "url": url,
                "description": r.get("description") or "",
            }
        )
    return out


async def _search_exa(
    api_key: str,
    query: str,
    count: int,
    start_published_date: Optional[str] = None,
) -> list[dict[str, str]]:
    """Call Exa ``/search`` and return mapped ``[{title,url,description}]``.

    Raises ``RuntimeError`` on HTTP >= 400 so the caller can fall back to
    Firecrawl. Results are NOT host-filtered here.
    """
    import aiohttp

    body: dict[str, Any] = {
        "query": query,
        "numResults": count,
        "type": "auto",
        "contents": {"highlights": {"numSentences": 2, "highlightsPerUrl": 1}},
    }
    if start_published_date:
        body["startPublishedDate"] = start_published_date
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=_DEFAULT_SEARCH_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(EXA_SEARCH_URL, json=body, headers=headers) as resp:
            if resp.status == 429:
                retry_after = resp.headers.get("Retry-After", "unknown")
                raise RuntimeError(
                    f"web_search rate-limited by Exa (HTTP 429, Retry-After={retry_after})"
                )
            if resp.status >= 400:
                detail = (await resp.text())[:1000]
                raise RuntimeError(
                    f"web_search Exa failed (HTTP {resp.status}): {detail!r}"
                )
            payload = await resp.json(content_type=None)
    return _map_exa_results(payload)


async def _search_firecrawl(
    api_key: str,
    query: str,
    count: int,
) -> list[dict[str, str]]:
    """Call Firecrawl ``/v1/search`` and return mapped ``[{title,url,description}]``.

    Raises ``RuntimeError`` on HTTP >= 400. Results are NOT host-filtered here.
    """
    import aiohttp

    body = {"query": query, "limit": count}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=_DEFAULT_SEARCH_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(FIRECRAWL_SEARCH_URL, json=body, headers=headers) as resp:
            if resp.status == 429:
                retry_after = resp.headers.get("Retry-After", "unknown")
                raise RuntimeError(
                    f"web_search rate-limited by Firecrawl (HTTP 429, Retry-After={retry_after})"
                )
            if resp.status >= 400:
                detail = (await resp.text())[:1000]
                raise RuntimeError(
                    f"web_search Firecrawl failed (HTTP {resp.status}): {detail!r}"
                )
            payload = await resp.json(content_type=None)
    return _map_firecrawl_results(payload)


def _build_search_payload(
    provider: str, query: str, count: int, raw_results: list
) -> dict:
    """Apply the denylist filter + truncation and shape the tool return dict."""
    results = _filter_and_truncate(raw_results, count)
    return {
        "success": True,
        "provider": provider,
        "query": query,
        "count": len(results),
        "results": results,
    }


async def _run_web_search(
    exa_key: str,
    firecrawl_key: str,
    query: str,
    count: int,
    start_published_date: Optional[str],
) -> dict:
    """Run the Exa→Firecrawl search chain and return the tool payload.

    Provider selection:
      - Exa is primary whenever ``exa_key`` is set.
      - Firecrawl is the fallback, used when Exa is unavailable (no
        ``exa_key``), raises, or returns zero results — provided a
        ``firecrawl_key`` exists.
      - If Exa raises and there is no Firecrawl key, the Exa error propagates.
      - If Exa returns zero results and there is no Firecrawl key, the empty
        Exa result is returned as-is.

    At least one key is guaranteed non-empty by the caller
    (``WebSearchTool._resolve_api_keys``). Reads the module-level ``_search_*``
    coroutines by name so tests can monkeypatch them.
    """
    if exa_key:
        try:
            raw = await _search_exa(exa_key, query, count, start_published_date)
        except Exception as exa_err:  # noqa: BLE001 — fall back or resurface
            if firecrawl_key:
                logger.info(
                    "web_search: Exa failed (%s); falling back to Firecrawl", exa_err
                )
                raw = await _search_firecrawl(firecrawl_key, query, count)
                return _build_search_payload("firecrawl", query, count, raw)
            raise
        if raw:
            return _build_search_payload("exa", query, count, raw)
        # Exa succeeded but returned nothing — fall back if a key is available.
        if firecrawl_key:
            logger.info("web_search: Exa returned 0 results; falling back to Firecrawl")
            raw = await _search_firecrawl(firecrawl_key, query, count)
            return _build_search_payload("firecrawl", query, count, raw)
        return _build_search_payload("exa", query, count, raw)

    # No Exa key: Firecrawl is the only provider.
    raw = await _search_firecrawl(firecrawl_key, query, count)
    return _build_search_payload("firecrawl", query, count, raw)


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------


@register_tool("web_search")
class WebSearchTool(BaseTool):
    """Search the web via Exa (primary) with a Firecrawl fallback.

    Requires at least one of ``EXA_API_KEY`` / ``Firecrawl_API_KEY`` (env
    vars), or an explicit ``exa_api_key`` / ``firecrawl_api_key`` kwarg. Exa
    serves whenever its key is present; Firecrawl takes over when Exa is
    unavailable, errors, or returns no results. Errors are returned as
    ``{"success": False, "error": "..."}`` to keep the contract aligned with
    the other OpenClaw tools.
    """

    def __init__(
        self,
        *,
        exa_api_key: Optional[str] = None,
        firecrawl_api_key: Optional[str] = None,
        cfg: Optional[dict] = None,
    ):
        self._exa_api_key_override = exa_api_key
        self._firecrawl_api_key_override = firecrawl_api_key
        super().__init__(cfg)

    @property
    def description(self) -> str:
        return (
            "Search the web (Exa, with Firecrawl fallback). Returns ranked "
            "results with title, url, and description."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query.",
                },
                "count": {
                    "type": "integer",
                    "description": (
                        f"Results to return "
                        f"(1-{_MAX_SEARCH_COUNT}, default {_DEFAULT_SEARCH_COUNT})."
                    ),
                    "minimum": 1,
                    "maximum": _MAX_SEARCH_COUNT,
                },
                "freshness": {
                    "type": "string",
                    "description": (
                        "Time filter: 'pd' (past day), 'pw' (past week), "
                        "'pm' (past month), 'py' (past year)."
                    ),
                    "enum": sorted(_VALID_FRESHNESS),
                },
                "country": {
                    "type": "string",
                    "description": "ISO country code (e.g. 'US', 'JP'). Biases results.",
                },
                "date_after": {
                    "type": "string",
                    "description": (
                        "Only results published on or after YYYY-MM-DD. Maps to "
                        "Exa's startPublishedDate; ignored by the Firecrawl fallback."
                    ),
                },
            },
            "required": ["query"],
        }

    def _resolve_api_keys(self) -> tuple[str, str]:
        """Resolve ``(exa_key, firecrawl_key)``; at least one must be present.

        Explicit overrides win over env vars. web_search runs with whichever
        provider has a key and only errors when BOTH are missing. Note the
        intentional mixed-case ``Firecrawl_API_KEY`` env var name — it is read
        verbatim, not upper-cased.
        """
        exa_key = (
            self._exa_api_key_override or os.environ.get("EXA_API_KEY") or ""
        ).strip()
        firecrawl_key = (
            self._firecrawl_api_key_override
            or os.environ.get("Firecrawl_API_KEY")
            or ""
        ).strip()
        if not exa_key and not firecrawl_key:
            raise ValueError(
                "web_search requires at least one of EXA_API_KEY or "
                "Firecrawl_API_KEY (env vars), or an api_key override."
            )
        return exa_key, firecrawl_key

    def call(self, params: Union[str, dict], **kwargs) -> dict:
        try:
            parsed = self._verify_json_format_args(params)
            query = _get_required_str(parsed, "query", "web_search")
            count = _resolve_int(
                parsed.get("count"),
                default=_DEFAULT_SEARCH_COUNT,
                min_=1,
                max_=_MAX_SEARCH_COUNT,
            )
            # freshness/country are accepted for schema back-compat but not
            # consumed by Exa/Firecrawl; date_after maps to Exa
            # startPublishedDate. None of this raises — unsupported/malformed
            # values are skipped.
            freshness_param, country, start_published_date = _normalize_search_params(
                parsed.get("freshness"),
                parsed.get("country"),
                parsed.get("date_after"),
            )
            exa_key, firecrawl_key = self._resolve_api_keys()
        except ValueError as e:
            return {"success": False, "error": f"Error: {e}"}

        cache_key = (query, count, freshness_param, country)
        hit = _SEARCH_CACHE.get(cache_key)
        if hit is not None:
            return {**hit, "cached": True}

        try:
            result = _run_async(
                _run_web_search(
                    exa_key, firecrawl_key, query, count, start_published_date
                )
            )
        except Exception as e:  # noqa: BLE001 — surface HTTP errors as tool errors
            logger.error("web_search failure on %r: %s", query, e)
            return {"success": False, "error": f"Error: {e}"}

        _SEARCH_CACHE.set(cache_key, result, ttl_seconds=_SEARCH_CACHE_TTL_SECONDS)
        return result


# ---------------------------------------------------------------------------
# WebFetchTool
# ---------------------------------------------------------------------------


@register_tool("web_fetch")
class WebFetchTool(BaseTool):
    """Fetch an HTTP(S) URL and extract readable text.

    Pipeline: SSRF guard → aiohttp GET (redirect + size cap) → content-type
    routing → readability / basic-HTML / raw → optional markdownify →
    truncate.
    """

    def __init__(
        self,
        *,
        user_agent: Optional[str] = None,
        max_response_bytes: Optional[int] = None,
        cfg: Optional[dict] = None,
    ):
        self.user_agent = user_agent or _DEFAULT_FETCH_USER_AGENT
        self.max_response_bytes = (
            int(max_response_bytes)
            if isinstance(max_response_bytes, (int, float)) and max_response_bytes > 0
            else _DEFAULT_FETCH_MAX_RESPONSE_BYTES
        )
        super().__init__(cfg)

    @property
    def description(self) -> str:
        return (
            "Fetch and extract readable text from an HTTP(S) URL. Use for "
            "lightweight page access without browser automation."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "HTTP or HTTPS URL.",
                },
                "extractMode": {
                    "type": "string",
                    "enum": ["markdown", "text"],
                    "description": "Output format (default 'markdown').",
                },
                "maxChars": {
                    "type": "integer",
                    "description": (
                        f"Character cap on returned text "
                        f"(default {_DEFAULT_FETCH_MAX_CHARS}, "
                        f"max {_MAX_FETCH_MAX_CHARS})."
                    ),
                    "minimum": 100,
                    "maximum": _MAX_FETCH_MAX_CHARS,
                },
            },
            "required": ["url"],
        }

    def call(self, params: Union[str, dict], **kwargs) -> dict:
        try:
            parsed = self._verify_json_format_args(params)
            url = _get_required_str(parsed, "url", "web_fetch")
            extract_mode_raw = parsed.get("extractMode", "markdown")
            if extract_mode_raw not in ("markdown", "text"):
                raise ValueError(
                    f'extractMode must be "markdown" or "text", got {extract_mode_raw!r}'
                )
            extract_mode = extract_mode_raw
            max_chars = _resolve_int(
                parsed.get("maxChars"),
                default=_DEFAULT_FETCH_MAX_CHARS,
                min_=100,
                max_=_MAX_FETCH_MAX_CHARS,
            )
            _assert_url_safe(url)
        except ValueError as e:
            return {"success": False, "error": f"Error: {e}"}

        cache_key = (url, extract_mode, max_chars)
        hit = _FETCH_CACHE.get(cache_key)
        if hit is not None:
            return {**hit, "cached": True}

        try:
            result = _run_async(self._fetch(url, extract_mode, max_chars))
        except ValueError as e:
            return {"success": False, "error": f"Error: {e}"}
        except Exception as e:  # noqa: BLE001 — surface HTTP errors as tool errors
            logger.error("web_fetch failure on %r: %s", url, e)
            return {"success": False, "error": f"Error: {e}"}

        _FETCH_CACHE.set(cache_key, result, ttl_seconds=_FETCH_CACHE_TTL_SECONDS)
        return result

    async def _fetch(
        self,
        url: str,
        extract_mode: str,
        max_chars: int,
    ) -> dict:
        t0 = time.monotonic()
        status, content_type, final_url, body_bytes, truncated_body = await self._http_get(url)

        body_text = _decode_best_effort(body_bytes)
        normalized_ct = content_type.split(";", 1)[0].strip().lower()
        text, title, extractor = self._extract_content(
            body_text, normalized_ct, content_type, final_url, extract_mode
        )

        truncated_output, marker_applied = _truncate_with_marker(text, max_chars)
        truncated_text_flag = truncated_body or marker_applied

        took_ms = int((time.monotonic() - t0) * 1000)
        return {
            "success": True,
            "url": url,
            "finalUrl": final_url,
            "status": status,
            "contentType": normalized_ct,
            "title": title,
            "extractMode": extract_mode,
            "extractor": extractor,
            "text": truncated_output,
            "truncated": truncated_text_flag,
            "length": len(truncated_output),
            "rawLength": len(body_text),
            "fetchedAt": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(),
            "tookMs": took_ms,
        }

    async def _http_get(self, url: str) -> tuple[int, str, str, bytes, bool]:
        """GET ``url`` and stream up to ``self.max_response_bytes``.

        Returns ``(status, content_type, final_url, body_bytes, truncated_body)``.
        Raises ``RuntimeError`` on HTTP >= 400 with a decoded error snippet.
        """
        import aiohttp

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/markdown, text/html;q=0.9, */*;q=0.1",
            "Accept-Language": "en-US,en;q=0.9",
        }
        timeout = aiohttp.ClientTimeout(total=_DEFAULT_FETCH_TIMEOUT_SECONDS)
        connector = aiohttp.TCPConnector(limit=4)
        body_bytes = bytearray()
        truncated_body = False
        async with aiohttp.ClientSession(
            timeout=timeout, connector=connector
        ) as session:
            async with session.get(
                url,
                headers=headers,
                allow_redirects=True,
                max_redirects=_DEFAULT_FETCH_MAX_REDIRECTS,
            ) as resp:
                final_url = str(resp.url)
                # Re-check the final URL after redirects — a server can
                # redirect a public URL to an internal one.
                _assert_url_safe(final_url)
                status = resp.status
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                async for chunk in resp.content.iter_chunked(32 * 1024):
                    if not chunk:
                        continue
                    remaining = self.max_response_bytes - len(body_bytes)
                    if remaining <= 0:
                        truncated_body = True
                        break
                    if len(chunk) > remaining:
                        body_bytes.extend(chunk[:remaining])
                        truncated_body = True
                        break
                    body_bytes.extend(chunk)

                if status >= 400:
                    detail_html = _decode_best_effort(bytes(body_bytes))
                    detail_text = _html_to_markdown(detail_html) if _looks_like_html(
                        detail_html, content_type
                    ) else detail_html
                    detail_truncated, _ = _truncate_with_marker(detail_text, 4000)
                    raise RuntimeError(
                        f"web_fetch failed (HTTP {status}) for {url}: {detail_truncated}"
                    )

        return status, content_type, final_url, bytes(body_bytes), truncated_body

    @staticmethod
    def _extract_content(
        body_text: str,
        normalized_ct: str,
        content_type: str,
        final_url: str,
        extract_mode: str,
    ) -> tuple[str, Optional[str], str]:
        """Extract ``(text, title, extractor)`` from a fetched body by content type.

        HTML routes through readability (then a basic-HTML fallback); JSON is
        pretty-printed; everything else is returned raw.
        """
        if _is_html_content_type(normalized_ct) or _looks_like_html(body_text, content_type):
            extracted = _extract_with_readability(body_text, final_url)
            if extracted is not None:
                title = extracted["title"]
                html_fragment = extracted["html"]
                if extract_mode == "markdown":
                    text = _html_to_markdown(html_fragment)
                else:
                    basic = _extract_basic_html(html_fragment)
                    text = (basic or {}).get("text", body_text)
                return text, title, "readability"
            basic = _extract_basic_html(body_text)
            if basic is not None:
                return basic["text"], basic["title"], "basic-html"
            raise RuntimeError(
                "web_fetch extraction failed: readability and basic-HTML "
                "fallback both returned empty content."
            )
        if normalized_ct == "application/json" or normalized_ct.endswith("+json"):
            try:
                return json.dumps(json.loads(body_text), indent=2), None, "json"
            except (ValueError, json.JSONDecodeError):
                return body_text, None, "raw"
        # text/* and any other content type → raw passthrough
        return body_text, None, "raw"


def _decode_best_effort(data: bytes) -> str:
    """Decode ``data`` trying utf-8 first, then latin-1 (which never fails).

    aiohttp can surface mis-declared encodings; latin-1 gives us a lossless
    fallback that ``readability``/``bs4`` can still parse.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def _is_html_content_type(ct: str) -> bool:
    return ct in ("text/html", "application/xhtml+xml")


def _looks_like_html(body: str, content_type: str) -> bool:
    head = body.lstrip()[:256].lower()
    if head.startswith("<!doctype html") or head.startswith("<html"):
        return True
    return "text/html" in (content_type or "").lower()
