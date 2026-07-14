"""PiConfig: per-episode knobs for the Pi coding-agent deployer.

Pi (``@earendil-works/pi-coding-agent``) is a Node CLI. It reaches an
LLM through the built-in providers OR a custom provider declared in
``models.json``. This deployer writes a ``models.json`` describing an
OpenAI-compatible gateway (default: apihy) and launches::

    pi --mode json --provider <provider> --model <model> \
       --no-session --approve "<prompt>"   < /dev/null

The API key travels with the serialized config (``api_key``) so it does
not need to be in the executor env passthrough whitelist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class PiConfig:
    """Tunables for :class:`PiDeployer`.

    Standalone config (no shared base). The episode wall-budget is
    orchestration-owned; there is no per-agent ``timeout_s`` knob.
    """

    name: ClassVar[str] = "pi"

    # ---- routing ---------------------------------------------------------
    model: str = "qwen3.5-397b-a17b"
    """Model id sent to the provider (``--model`` and the ``id`` in
    ``models.json``)."""

    provider: str = "apihy"
    """Provider name registered in ``models.json`` and passed to pi via
    ``--provider``."""

    base_url: str = "https://zgc.apihy.com/v1"
    """OpenAI-compatible base URL for the provider (``baseUrl``)."""

    api_key: str | None = None
    """Literal API key written into ``models.json`` (``apiKey``). Travels
    with the serialized config, so it survives the executor boundary
    without an env passthrough change. ``None`` ⇒ fall back to
    ``executor.env`` / ``api_key_env``."""

    api_key_env: str = "apihy_API_KEY_qwen"
    """Executor-env var name to read the key from when ``api_key`` is unset."""

    api: str = "openai-completions"
    """pi ``models.json`` API type. One of ``openai-completions``,
    ``openai-responses``, ``anthropic-messages``, ``google-generative-ai``."""

    # ---- model shape -----------------------------------------------------
    reasoning: bool = False
    """Whether pi should treat the model as reasoning-capable. Left False
    by default: apihy's Qwen streams ``reasoning_content`` on its own
    without pi sending reasoning-control params, which keeps the request
    shape maximally compatible."""

    thinking: str = "off"
    """pi ``--thinking`` level: off | minimal | low | medium | high | xhigh."""

    context_window: int = 262144
    max_tokens: int = 32768

    compat: dict[str, Any] = field(default_factory=dict)
    """Provider-level ``compat`` overrides for partial OpenAI compatibility
    (e.g. ``{"supportsReasoningEffort": false}``)."""

    # ---- install ---------------------------------------------------------
    npm_package: str = "@earendil-works/pi-coding-agent@0.80.3"
    """npm spec installed with ``npm install -g`` when ``pi`` is not already
    on PATH. Pinned to the version validated for this run."""

    # ---- tools -----------------------------------------------------------
    disabled_tools: tuple[str, ...] = ()
    """Built-in/extension tools to disable via ``--exclude-tools``."""

    no_context_files: bool = True
    """Pass ``--no-context-files`` so stray ``AGENTS.md``/``CLAUDE.md`` in the
    task tree do not leak into the system prompt (deterministic benchmark
    runs)."""

    # ---- env -------------------------------------------------------------
    clear_proxy: bool = True
    """Drop ``HTTP(S)_PROXY``/``ALL_PROXY`` from the child env. The ALE
    docker image bakes a proxy pointing at a host port that is not exposed
    to the container; clearing it lets pi + npm reach the internet directly
    via the container's NAT."""

    extra_envs: dict[str, str] = field(default_factory=dict)
    """Free-form passthrough env vars for the pi subprocess."""
