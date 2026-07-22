"""AleClawConfig: per-episode knobs for the OpenClaw native agent deployer.

Standalone config (no shared base). Declares ``model`` / ``max_turns``
(mapped to OpenClaw's ``max_steps``) plus the OpenClaw-specific knobs
below. The episode wall-budget is orchestration-owned, so this config no
longer carries ``timeout_s``.

**API keys live in the operator's shell env**, not in this config. The
deployer never touches ``os.environ`` — litellm (the harness's LLM
client) reads ``OPENROUTER_API_KEY`` / ``ANTHROPIC_API_KEY`` /
``OPENAI_API_KEY`` directly from the process's env vars, which the
operator populates via shell ``source`` of an ``.env`` / ``.envrc``.
For docker / VM runtimes those vars are propagated by
:mod:`ale.runtime._env`.

Typical usage::

    # In shell:
    #   export OPENROUTER_API_KEY=...
    #   for f in secret/eval_time/*.env; do source "$f"; done

    cfg = AleClawConfig(
        model="openrouter/anthropic/claude-sonnet-4-20250514",
        max_turns=100,
    )
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class AleClawConfig:
    """Tunables for :class:`AleClawDeployer`."""

    name: ClassVar[str] = "ale-claw"

    model: str = "openrouter/anthropic/claude-sonnet-4.6"
    """LiteLLM-format model id. Maps to OpenClaw's ``model`` kwarg verbatim.
    OpenRouter routes work via the vendored ``unified_loop`` (registered for
    ``openrouter/.*`` regex)."""

    api_key: str | None = None
    """Optional solver-only API key override passed to the agent loop.

    This leaves process-level provider variables available to task evaluators,
    which may need a different OpenAI-compatible endpoint. ``None`` preserves
    the normal environment-based routing.
    """

    api_base: str | None = None
    """Optional solver-only OpenAI-compatible base URL override."""

    max_turns: int | None = 100
    """Mapped to OpenClaw's ``max_steps``. Hard ceiling on the agent run loop."""

    # ---- model variants ----
    summary_model: str | None = None
    """Model for compaction + memory_flush. None → ``auxiliary_model`` if set,
    else ``model``. Cheaper sibling for cost savings."""

    gui_model: str | None = None
    """Model for the ``delegate_gui`` subagent. None → ``auxiliary_model``
    if set, else falls back to main."""

    auxiliary_model: str | None = None
    """Optional cheaper sibling model offered to subagents, and the fallback for
    ``summary_model`` / ``gui_model`` when those are unset. Caller opts in
    explicitly; there is no automatic sibling lookup."""

    # ---- loop control ----
    max_history_turns: int | None = None
    """Truncate replay-message history when restoring a transcript. None = unlimited."""

    disable_main_computer: bool = False
    """If True, the main agent has no ``computer`` tool — all GUI work goes
    through ``delegate_gui``. Mutually exclusive with :attr:`disable_delegate_gui`."""

    disable_delegate_gui: bool = False
    """If True, no GUI subagent — main agent uses its own ``computer``."""

    disabled_tools: list[str] = field(default_factory=lambda: ["web_search"])
    """Tools to drop from the assembled tool list (matched by ``BaseTool.name``).
    Defaults to ``["web_search"]`` because the search API keys are rarely
    provisioned; set to ``[]`` to opt back in (and ensure at least one of
    ``EXA_API_KEY`` / ``Firecrawl_API_KEY`` is exported in your shell)."""


    skill_sources: dict[str, str] = field(default_factory=dict)
    """{skill_name: SKILL.md text}. Seeded as method playbooks into the task
    memory store: a short index goes into TASK_MEMORY.md (bootstrap-injected, so
    always visible), and each full body becomes a method-<name>.md memory file
    the model pulls with memory_get only when the skill's when-to-use matches.
    Empty default -> byte-identical to before."""

    task_specific_prep: bool = True
    """Run the task-specific prep agent in the writer's sandbox before the writer.

    It brings the task's runtime up, compiles the deliverable contract from the
    public materials, and looks up what the task does not supply. Its report is
    inlined into the writer's first prompt. The worker has read/exec/web tools
    but does not receive solver skills.
    """

    task_specific_prep_model: str | None = None
    """Prep-agent model. None uses the main model, preserving full capability."""

    task_specific_prep_max_steps: int = 30
    """Maximum multi-turn tool/LLM steps for the prep agent."""

    task_specific_prep_timeout_s: int = 1800
    """Wall-clock budget for one prep session. On timeout the writer continues."""

    task_specific_prep_self_check: bool = True
    """Deliver the prep self-check (script, report section, digest command).

    ``False`` keeps prep itself identical - same prompt, same budget, the
    script is still written and declared - but withholds the self-check and
    its artifact from everything the writer sees. This is the A/B switch for
    isolating the self-check channel's net effect from the rest of prep.
    """

    task_specific_prep_task_id: str = ""
    """Lifecycle-populated task identity used for audited content-addressed caching."""

    task_specific_prep_task_root: str = ""
    """Lifecycle-populated public task root containing input/ and software/."""

    verifier: bool = False
    """Freeze an independent public verifier before the solver, then run it after."""

    verifier_model: str | None = None
    """Builder/auditor model. None uses the main model."""

    verifier_max_steps: int = 30
    """Maximum tool/LLM steps for each Builder or Auditor."""

    verifier_max_review_rounds: int = 1
    """Maximum Writer review rounds after the frozen suite runs.

    A round feeds the report to the Writer; it becomes a revision only when the
    Writer actually changes output. A round with no output change stops the loop.
    """

    verifier_writer_checks: int = 2
    """Pre-submission runs of the frozen suite the Writer may trigger itself.

    When the verifier is on and this is positive, the Writer gets a ``verify``
    tool that snapshots the current ``output/`` and runs the complete frozen
    suite before DONE, so measurements arrive while the Writer still has budget
    to act on them. 0 removes the tool and keeps the post-DONE-only behavior.
    """

    writer_self_review_hint: bool = False
    """Append a short pre-submission self-review instruction to the writer prompt.

    Control arm for pricing the verifier: no frozen tests and no tools, only
    the instruction to recheck ``output/`` against the task's stated contract
    before DONE. Run it with ``verifier=False`` to measure how much of the
    verifier arm's effect the instruction alone reproduces.
    """

    # ---- substrate transport ----
    substrate_transport: str = "mcp"
    """How the non-GUI tools (``read``/``write``/``edit``/``exec``) reach the VM.

    - ``"mcp"`` (default): route through the ``vm_mcp_server`` bridge — the agent
      consumes the same MCP substrate as installed agents. Tool granularity is
      unchanged; only the transport moves off ``RemoteDesktopSession``.
    - ``"session"``: legacy direct ``session.interface`` RPC. Retained as a
      debug / parity escape hatch; may be removed once the MCP path is validated.

    GUI (the ``computer`` tool) is governed separately by :attr:`gui_transport`."""

    gui_transport: str | None = None
    """How the GUI ``computer`` tool reaches the VM (Phase 2).

    - ``None`` (default): follow :attr:`substrate_transport` — so GUI is ``"mcp"``
      by default, and a ``substrate_transport="session"`` run stays all-session
      without having to flip this too.
    - ``"mcp"``: route GUI through the ``cua_mcp_server`` bridge — clicks/keys/
      screenshots become MCP tool calls (pixel↔[0,1000] conversion in the
      handler). Requires ``substrate_transport="mcp"``.
    - ``"session"``: the cua ``RemoteDesktopSession`` handler (pixel coords).

    With both transports on ``"mcp"`` (the default), ale_claw never touches
    ``RemoteDesktopSession`` for tool I/O."""

    # ---- thinking levels (off | low | medium | high) ----
    thinking_level: str | None = None
    """Base thinking level. None → resolved-default for the model
    (see ``harness.thinking.resolve_thinking_default``)."""

    flush_thinking_level: str | None = None
    """Memory flush thinking. None → inherit :attr:`thinking_level`."""

    compaction_thinking_level: str | None = None
    """Compaction-rebuild thinking. None → inherit :attr:`thinking_level`."""

    vision_thinking_level: str = "off"
    """Vision/screenshot summarization thinking. Default off (cost)."""

    gui_thinking_level: str = "off"
    """``delegate_gui`` subagent thinking. Default off."""

    # ---- image retention ----
    image_retention_mode: str = "openclaw"
    """``openclaw`` (default — last N completed turns) or ``cua`` (last N images
    by count). OpenClaw mode reduces cache thrash on multi-screenshot turns."""

    def __post_init__(self) -> None:
        if self.task_specific_prep_max_steps <= 0:
            raise ValueError("task_specific_prep_max_steps must be positive")
        if self.task_specific_prep_timeout_s <= 0:
            raise ValueError("task_specific_prep_timeout_s must be positive")
        if self.verifier_max_steps <= 0:
            raise ValueError("verifier_max_steps must be positive")
        if not 1 <= self.verifier_max_review_rounds <= 3:
            raise ValueError("verifier_max_review_rounds must be between 1 and 3")
        if not 0 <= self.verifier_writer_checks <= 8:
            raise ValueError("verifier_writer_checks must be between 0 and 8")
        if self.disable_main_computer and self.disable_delegate_gui:
            raise ValueError(
                "Both disable_main_computer and disable_delegate_gui set — "
                "agent has no way to interact with the VM."
            )
        if self.substrate_transport not in ("mcp", "session"):
            raise ValueError(
                f"AleClawConfig.substrate_transport={self.substrate_transport!r} "
                "not in {mcp, session}"
            )
        if self.gui_transport is not None and self.gui_transport not in ("mcp", "session"):
            raise ValueError(
                f"AleClawConfig.gui_transport={self.gui_transport!r} not in {{mcp, session, None}}"
            )
        # An explicit gui=mcp on a session substrate is a genuine conflict; the
        # None default instead *follows* substrate (so session mode just works).
        if self.gui_transport == "mcp" and self.substrate_transport != "mcp":
            raise ValueError(
                "AleClawConfig.gui_transport='mcp' requires substrate_transport='mcp'"
            )
        if self.gui_transport is None:
            self.gui_transport = self.substrate_transport
        for level_field, value in [
            ("thinking_level", self.thinking_level),
            ("flush_thinking_level", self.flush_thinking_level),
            ("compaction_thinking_level", self.compaction_thinking_level),
            ("vision_thinking_level", self.vision_thinking_level),
            ("gui_thinking_level", self.gui_thinking_level),
        ]:
            if value is not None and value not in ("off", "low", "medium", "high"):
                raise ValueError(
                    f"AleClawConfig.{level_field}={value!r} not in "
                    f"{{off, low, medium, high}}"
                )
