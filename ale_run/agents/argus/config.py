"""ArgusConfig — per-episode knobs for the Argus multi-role deployer.

Argus (``argus-skill``) is not a model and not a single agent loop: it is an
orchestrator that drives Manager / Planner / Engineer / Reviewer, each of which
is one ``codex exec`` subprocess. So this config has two halves:

  * the **codex-CLI half** (``model`` / ``provider`` / ``base_url`` /
    ``api_key`` / catalog / fork pins) — identical in meaning to
    :class:`~ale_run.agents.codex.config.CodexConfig`, because the deployer
    provisions the very same CLI and writes the very same
    ``~/.codex/config.toml``. :meth:`ArgusConfig.codex_config` converts this
    half into a real ``CodexConfig`` so there is exactly one implementation of
    "install codex + point it at a gateway".

  * the **argus half** (role reasoning efforts, round/mission ceilings, whether
    Manager classifies the vertical or the harness pins it) — surfaced as env
    vars to the in-sandbox launcher, which is the only supported way to
    configure argus-skill non-interactively.

Secrets: ``api_key`` travels inside the serialized config (written into
config.toml as the provider's ``experimental_bearer_token``), exactly as the
codex agent does it. Nothing here is read from the sandbox shell env.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from ale_run.agents.codex.config import CodexConfig


@dataclass
class ArgusConfig:
    """Tunables for :class:`~ale_run.agents.argus.deployer.ArgusDeployer`.

    Standalone config (no shared base). The episode wall-budget is
    orchestration-owned and enforced by the executor, so there is no
    ``timeout_s`` knob here.
    """

    name: ClassVar[str] = "argus"

    # =====================================================================
    # model routing (shared with the codex agent, same semantics)
    # =====================================================================

    model: str = "openai/gpt-5.6-sol"
    """Model id every role uses unless a per-role override below is set.
    Passed to ``codex exec -m <model>``."""

    provider: str = "openrouter"
    """``"openrouter"`` writes a ``[model_providers.openrouter]`` block whose
    ``base_url`` is :attr:`base_url` — that is the path used to reach any
    OpenAI-compatible Responses gateway (Boyue included). ``"direct"`` routes
    through ``OPENAI_API_KEY``."""

    base_url: str | None = None
    """Responses-API gateway. ``None`` ⇒ OpenRouter's default. For Boyue set
    the gateway root that exposes ``<base_url>/responses``."""

    api_key: str | None = None
    """Literal key for :attr:`base_url`. Set it from the agent yaml as
    ``api_key: ${env:BOYUE_API_KEY}`` so the secret is resolved host-side and
    travels with the serialized config."""

    model_catalog_path: str = ""
    """Host path to a codex model-catalog JSON. OPTIONAL: codex was verified to
    run ``gpt-5.6-sol`` through the Boyue gateway with no catalog at all, given
    :attr:`model_context_window` below — an unknown model is not rejected, and
    the reasoning effort is forwarded verbatim (the endpoint itself validates
    it, and it accepts ``xhigh``). Supply
    ``harness/run/model_catalog_boyue.json`` when you want the window and the
    effort list declared explicitly. Read and sanitised host-side; the content
    ships to the sandbox in :attr:`model_catalog_content`."""

    model_catalog_content: str = ""
    """Auto-populated from :attr:`model_catalog_path`; do not set by hand."""

    model_context_window: int = 128000
    """Written to ``config.toml`` as codex's ``model_context_window``. Matches
    ``CONTEXT_WINDOW_OVERRIDE=128000`` on the run box, which is what ale_claw
    uses for the same model, so both arms compact at the same budget. 0 leaves
    the key out and lets the catalog (or codex's default) decide."""

    model_auto_compact_token_limit: int = 100000
    """codex's ``model_auto_compact_token_limit``: where the history is
    compacted. 0 leaves the key out."""

    # ---- codex build pinning (mirrors CodexConfig; empty = inherit its default)
    codex_version: str = ""
    fork_version: str = ""
    patched_binary_url: str = ""
    patched_binary_url_windows: str = ""

    # =====================================================================
    # argus roles
    # =====================================================================

    manager_model: str = ""
    planner_model: str = ""
    engineer_model: str = ""
    reviewer_model: str = ""
    """Per-role model overrides. Empty ⇒ :attr:`model`."""

    manager_reasoning_effort: str = "xhigh"
    planner_reasoning_effort: str = "xhigh"
    engineer_reasoning_effort: str = "xhigh"
    engineer_initial_reasoning_effort: str = "high"
    reviewer_reasoning_effort: str = "high"
    """Argus's own defaults, restated here so a change on either side is
    visible in the run config rather than inherited silently. Boyue's
    gpt-5.6-sol accepts ``xhigh``."""

    runner_backend: str = "codex"
    """Which CLI argus drives. Only ``codex`` is provisioned by
    :meth:`ArgusDeployer.install`; ``claude`` / ``copilot`` / ``opencode``
    would each need their own install step."""

    # =====================================================================
    # mission shape
    # =====================================================================

    manager_division: bool = False
    """``False`` (default): the harness pins the vertical to
    ``ale_last_exam`` and enqueues the ALE instruction as one backlog item, so
    Planner / Engineer / Reviewer run against a fixed mission type. ``True``:
    hand the raw instruction to Manager and let it classify — this costs one
    extra model call and can land the episode in the wrong vertical (the
    paper pipeline), so it is off unless you are measuring Manager itself."""

    vertical: str = "ale_last_exam"
    """Vertical committed into ``research/PIPELINE_STATE.json`` before the run.
    Without this, argus falls back to the ``research`` (paper) pipeline."""

    max_missions: int = 1
    """Backlog missions one episode may drain. ALE is one deliverable."""

    max_rounds: int = 500
    """Engineer↔Reviewer rounds inside one mission (argus's own life default)."""

    iterate: bool = False
    """Argus's post-``done`` polish cycles. Off by default: the reviewer round
    loop inside the mission already re-runs the engineer, and the episode has a
    hard wall-clock budget."""

    iteration_max_cycles: int = 1

    require_post_task_learning: bool = False
    """Argus's skill-distillation pass after the mission. Off for ALE: the
    skill library is empty and per-episode, so distillation only spends the
    remaining wall clock."""

    # =====================================================================
    # runtime
    # =====================================================================

    cost_control: bool = False
    """Argus's USD budget fence. Off for ALE: gateway models are unpriced, and
    the default unpriced policy is ``block``, which would refuse every call."""

    global_daily_cap_usd: float = 1_000_000.0
    """Only consulted when :attr:`cost_control` is on."""

    argus_package: str = ""
    """pip requirement installed inside the sandbox.

    Empty (the default) means "use the wheel vendored at
    ``ale_run/agents/argus/_vendor/*.whl``". That is the only reliable source:
    ``argus-skill`` is not published on PyPI (``/pypi/argus-skill/json`` → 404),
    and the sandbox cannot read the harness host's filesystem, so the package
    has to ride along with the ``ale_run`` tree the executor already ships.
    Set an explicit spec (a version, a path, a VCS URL) to override."""

    argus_pip_index_url: str = ""
    """Optional index URL for the pip install (mirror / private index)."""

    extra_env: dict[str, str] = field(default_factory=dict)
    """Extra env vars for the launcher process (and therefore every codex
    child). Escape hatch for argus knobs this config does not name."""

    def __post_init__(self) -> None:
        # Load the catalog host-side so the in-sandbox deployer, which cannot
        # reach the host path, still gets the content. Mirrors CodexConfig.
        if self.model_catalog_path and not self.model_catalog_content:
            from ale_run.agents.codex.config import _sanitise_catalog_for_fork

            try:
                raw = Path(self.model_catalog_path).read_text(encoding="utf-8")
            except OSError as exc:
                raise RuntimeError(
                    f"argus: model_catalog_path {self.model_catalog_path!r} "
                    f"could not be read: {exc}"
                ) from exc
            self.model_catalog_content = _sanitise_catalog_for_fork(raw)

    # ------------------------------------------------------------------

    def codex_config(self) -> "CodexConfig":
        """The equivalent :class:`CodexConfig` for CLI provisioning.

        Only the fields the codex deployer's ``install`` path reads are set;
        the empty pin fields fall through to CodexConfig's own defaults so a
        fork bump lands in one place.
        """
        from ale_run.agents.codex.config import CodexConfig

        kwargs: dict[str, object] = {
            "model": self.model,
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "model_catalog_content": self.model_catalog_content,
            "reasoning_effort": self.engineer_reasoning_effort,
            "sandbox_mode": "danger-full-access",
            "yolo": True,
            # The OTel collector is a codex-deployer artifact keyed to its own
            # work_dir layout; argus spawns many codex processes and reads its
            # own event log, so leave it off.
            "otel_enabled": False,
        }
        for pin in (
            "codex_version",
            "fork_version",
            "patched_binary_url",
            "patched_binary_url_windows",
        ):
            value = getattr(self, pin)
            if value:
                kwargs[pin] = value
        return CodexConfig(**kwargs)  # type: ignore[arg-type]

    def role_env(self) -> dict[str, str]:
        """Argus role/runtime knobs as environment variables.

        ``argus-skill`` has no config file for these; every non-interactive
        entry point reads ``ARGUS_SKILL_*`` from the environment.
        """
        env: dict[str, str] = {
            "ARGUS_SKILL_RUNNER_BACKEND": self.runner_backend,
            "ARGUS_SKILL_MODEL": self.model,
            "ARGUS_SKILL_MANAGER_MODEL": self.manager_model or self.model,
            "ARGUS_SKILL_PLAN_MODEL": self.planner_model or self.model,
            "ARGUS_SKILL_ENGINEER_MODEL": self.engineer_model or self.model,
            "ARGUS_SKILL_REVIEWER_MODEL": self.reviewer_model or self.model,
            "ARGUS_SKILL_MANAGER_REASONING_EFFORT": self.manager_reasoning_effort,
            "ARGUS_SKILL_PLANNER_REASONING_EFFORT": self.planner_reasoning_effort,
            "ARGUS_SKILL_ENGINEER_REASONING_EFFORT": self.engineer_reasoning_effort,
            "ARGUS_SKILL_ENGINEER_INITIAL_REASONING_EFFORT": (
                self.engineer_initial_reasoning_effort
            ),
            "ARGUS_SKILL_REVIEWER_REASONING_EFFORT": self.reviewer_reasoning_effort,
            "ARGUS_SKILL_MAX_ROUNDS": str(self.max_rounds),
            "ARGUS_SKILL_COST_CONTROL": "on" if self.cost_control else "off",
            "ARGUS_SKILL_GLOBAL_DAILY_CAP_USD": str(self.global_daily_cap_usd),
            "ARGUS_SKILL_REQUIRE_POST_TASK_LEARNING": (
                "1" if self.require_post_task_learning else "0"
            ),
            # Reasoning summaries exist to keep a human watching the cockpit
            # informed; nobody is watching, and they cost output tokens.
            "ARGUS_SKILL_REASONING_SUMMARY": "none",
        }
        env.update({str(k): str(v) for k, v in (self.extra_env or {}).items()})
        return env
