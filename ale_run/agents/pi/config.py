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

    # ---- harness injection surfaces --------------------------------------
    skills: tuple[str, ...] = ()
    """Host paths passed through as ``--skill <path>`` (repeatable).

    A skill is a ``SKILL.md`` directory whose YAML frontmatter (``name`` +
    ``description``) is the only part resident in the system prompt; the body
    is loaded solely when the model itself elects to invoke it. That makes
    this the one surface with progressive disclosure built in: a skill that
    does not trigger costs ~20 tokens and changes nothing, so relevance
    gating is done by the model against the description rather than by us
    guessing a task taxonomy up front.

    Empty by default: a run that sets no skills is byte-identical to the
    pre-existing argv, so this cannot perturb an established baseline."""

    skill_sources: dict[str, str] = field(default_factory=dict)
    """``{skill_name: SKILL.md text}`` materialized into the pi config dir at
    install time and then passed via ``--skill``.

    The deployer executes *inside* the sandbox (``install`` writes
    ``models.json`` with a plain ``write_text``), so a host path in ``skills``
    does not resolve there. Skill bodies therefore travel with the serialized
    config — the same trick ``api_key`` uses to cross the executor boundary —
    rather than relying on a mount that the sandbox executor does not provide.

    ``skill_name`` must equal the SKILL.md frontmatter ``name`` and be
    ``[a-z0-9-]+``; pi's loader warns and drops the skill when the name and
    its parent directory disagree."""

    extensions: tuple[str, ...] = ()
    """Host paths passed through as ``--extension <path>`` (repeatable).

    NOTE the flag is ``--extension`` (singular, repeatable) — ``--extensions``
    belongs to ``pi update`` and is not an agent flag. Extensions attach to
    the extension *event bus* (``tool_call``/``tool_result``/``turn_end``),
    NOT to the three ``AgentLoopConfig`` loop hooks: ``shouldStopAfterTurn``
    has no consumer in ``coding-agent`` at all, and ``before/afterToolCall``
    are already claimed by ``agent-session.ts`` and bridged to the bus with
    the ``terminate`` field dropped. Under ``--mode json`` there is therefore
    no supported way for an extension to stop the loop; budget control has to
    be emulated. Do not plan an intervention that depends on those hooks.

    Empty by default, for the same baseline-safety reason as ``skills``."""

    # ---- env -------------------------------------------------------------
    clear_proxy: bool = True
    """Drop ``HTTP(S)_PROXY``/``ALL_PROXY`` from the child env. The ALE
    docker image bakes a proxy pointing at a host port that is not exposed
    to the container; clearing it lets pi + npm reach the internet directly
    via the container's NAT."""

    extra_envs: dict[str, str] = field(default_factory=dict)
    """Free-form passthrough env vars for the pi subprocess."""
