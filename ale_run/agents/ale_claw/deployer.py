"""AleClawDeployer — OpenClaw harness native deployer.

Lives on the host (``runtime: local``) or in a docker container
(``runtime: docker``) — same code, framework picks where to run.

The deployer's surface:

  __init__(executor): stores the executor (per-unit context + I/O)
  install():          import-check the harness modules + at least one
                      API key env var
  launch(prompt):     runs the OpenClaw harness end-to-end, writes
                      transcripts to executor.work_dir, returns
                      AgentRunResult
  parse_artifacts():  reads work_dir's transcripts → ATIF Steps via builder

The OpenClaw harness itself is unchanged (lives at :mod:`.harness`,
copied from ``cua_bench/agents/openclaw/`` upstream).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from ale_run.base_interface import (
    AgentRunResult,
    BaseAgentDeployer,
    TrajectoryBuilder,
)

from .config import AleClawConfig
from .task_prep import (
    NO_PREP_SENTINEL,
    TaskPrepResult,
    build_prep_digest,
    run_task_specific_prep,
)
from .reviewer_audit import (
    build_audit_feedback_prompt,
    parse_audit_disputes,
    reviewer_audit_protocol_digest,
    run_reviewer_audit_with_retry,
)
from .verifier_runtime import (
    reconcile_to_allowlist,
    restore_snapshot,
    snapshot_output,
    snapshot_regressed,
    stage_verifier_report,
)
from .transcript_to_trajectory import parse_transcripts_into

# Harness imports (all in-tree under harness/).
from .harness import (
    OpenClawComputerAgent,
    OpenClawComputerHandler,
    SessionManager,
    MemoryStore,
    SubagentRegistry,
    build_tools,
    get_tool_summaries,
    ToolLoggingCallback,
    ContextOverflowCallback,
    build_system_prompt_report,
    PromptBuilder,
    ContextFile,
    ThinkingConfig,
    ThinkLevel,
    resolve_thinking_default,
    build_replay_messages,
    sanitize_history,
    limit_history_turns,
    convert_to_responses_api_items,
)
from .harness.agent_loop import has_done_signal
from .harness.context.context import DEFAULT_CONTEXT_TOKENS, resolve_context_window
from .harness.model.model_config import resolve_model

logger = logging.getLogger(__name__)

# System-prompt context file shipped with the harness; loaded fresh each launch
_HARNESS_AGENTS_MD = Path(__file__).resolve().parent / "harness" / "AGENTS.md"


def _prep_artifact_parts(relative: str) -> tuple[str, ...]:
    candidate = PurePosixPath(relative)
    if (
        "\\" in relative
        or candidate.is_absolute()
        or not candidate.parts
        or candidate.parts[0] != "artifacts"
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError(f"invalid prep artifact path: {relative!r}")
    return candidate.parts


def _assistant_text(output: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in output:
        if item.get("type") != "message":
            continue
        content = item.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and block.get("text")
            )
    return "\n".join(parts)


def _skill_description(body: str) -> str:
    """Extract the `description:` value from a SKILL.md frontmatter block."""
    in_fm = False
    for line in body.splitlines():
        s = line.strip()
        if s == "---":
            if in_fm:
                break
            in_fm = True
            continue
        if in_fm and s.lower().startswith("description:"):
            return s.split(":", 1)[1].strip()
    return "(no description)"


def _seed_skill_playbooks(memory_store, task_id: str, skill_sources: dict) -> None:
    """Seed skill bodies as memory files + a when-to-use index into TASK_MEMORY.md."""
    idx = [
        "# Method playbooks (pre-seeded)",
        "",
        "Optional. Use the ONE whose 'when to use' matches this task; if neither "
        "fits, ignore both. To load a playbook, memory_get the path shown.",
        "",
    ]
    for name, body in skill_sources.items():
        (memory_store.memory_dir / f"method-{name}.md").write_text(body, encoding="utf-8")
        rel = f"tasks/{task_id}/memory/method-{name}.md"
        idx.append(f"- **{name}** — {_skill_description(body)}  (load: memory_get {rel})")
    memory_store.write_task_memory("\n".join(idx) + "\n")


async def _stage_prep_bundle(
    interface: Any,
    *,
    task_root: str,
    os_type: str,
    content: str,
    artifacts: dict[str, str],
) -> str | None:
    """Place a validated prep report and its text artifacts for the writer."""
    if not task_root or not content:
        return None
    separator = "\\" if os_type.lower() == "windows" else "/"
    task_root = task_root.rstrip("/\\")
    report_dir = task_root + separator + "task_prep"
    report_path = report_dir + separator + "PREP_REPORT.md"
    try:
        # The report directory must exist even when there is no artifact to
        # stage. Creating it inside the artifact loop meant that a bundle with
        # an empty artifact set skipped the mkdir and then lost the entire
        # report to ENOENT - a silent failure that made prep look like it ran
        # and delivered nothing. Observed on four of ten runs in the 26-task
        # rounds, including every run of the withheld-self-check arm, whose
        # only artifact is the self-check script.
        created_dirs: set[str] = {report_dir}
        await interface.create_dir(report_dir)
        for relative, artifact_content in sorted(artifacts.items()):
            portable_parts = _prep_artifact_parts(relative)
            native_relative = separator.join(portable_parts)
            artifact_path = report_dir + separator + native_relative
            parent = artifact_path.rsplit(separator, 1)[0]
            if parent not in created_dirs:
                await interface.create_dir(parent)
                created_dirs.add(parent)
            await interface.write_text(
                artifact_path, artifact_content, append=False
            )
        # The report is the bundle's entry point, so expose it only after every
        # declared artifact has been staged successfully.
        await interface.write_text(report_path, content, append=False)
    except Exception as exc:  # noqa: BLE001 - optional research must not abort solve
        logger.warning("could not stage task prep bundle at %s: %s", report_path, exc)
        return None
    return report_path


class AleClawDeployer(BaseAgentDeployer):
    """OpenClaw harness deployer. Runs on host or in docker container.

    Both ``local`` and ``docker`` executors are supported — same code path.
    The docker executor adds process / fs / env isolation; the local
    one is faster for dev. yaml picks one explicitly when both apply
    (with default ``local`` if omitted).
    """

    default_executor: ClassVar[str] = "local"
    supported_executors: ClassVar[frozenset[str]] = frozenset({"local", "docker"})

    # Modules ``install`` will import-fail-fast on (typo-catching).
    _required_modules: ClassVar[tuple[str, ...]] = (".harness.agent_loop",)
    # At least one of these env vars must be set or ``install`` raises.
    _api_key_alternatives: ClassVar[tuple[str, ...]] = (
        "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    )

    # =========================================================================
    # install — fast-fail on import + API key checks, then mkdir work_dir
    # =========================================================================

    async def install(self) -> None:
        import importlib
        import os as _os

        # Relative-imports anchor: this deployer's parent package
        # (i.e. ``ale_run.agents.ale_claw``).
        deployer_pkg = type(self).__module__.rsplit(".", 1)[0]
        for mod in self._required_modules:
            try:
                if mod.startswith("."):
                    importlib.import_module(mod, package=deployer_pkg)
                else:
                    importlib.import_module(mod)
            except ImportError as e:
                raise RuntimeError(
                    f"{type(self).__name__}: failed to import {mod!r}: {e}"
                ) from e
        if not any(_os.environ.get(k) for k in self._api_key_alternatives):
            raise RuntimeError(
                f"{type(self).__name__}: no LLM API key in env — set one of "
                f"{', '.join(self._api_key_alternatives)}"
            )
        Path(self.executor.work_dir).mkdir(parents=True, exist_ok=True)
        logger.info(
            "%s: install ok (model=%s, work_dir=%s, executor=%s)",
            type(self).__name__,
            getattr(self.config, "model", "?"),
            self.executor.work_dir,
            self.executor.type,
        )

    # =========================================================================
    # launch / parse_artifacts
    # =========================================================================

    async def launch(self, prompt: str) -> AgentRunResult:
        """Drive the OpenClaw agent end-to-end against the eval VM.

        Builds memory_store / session_mgr / tools / OpenClawComputerAgent,
        runs the async-generator loop with wall-clock timeout, returns the
        outcome. Transcripts land in ``self.executor.work_dir`` for
        :meth:`parse_artifacts` to read later.
        """
        cfg: AleClawConfig = self.config  # type: ignore[assignment]
        t0 = time.monotonic()
        # work_dir from BaseExecutor is a substrate-native str; local /
        # docker runtimes are host-visible so wrapping in Path is safe.
        work_dir = Path(self.executor.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        # Harness-internal id for memory + session keying (just a folder name).
        task_id = uuid.uuid4().hex[:12]
        memory_base = work_dir / "openclaw_memory"
        session_base = work_dir / "openclaw_sessions"
        trajectory_dir = work_dir / "trajectories"
        trajectory_dir.mkdir(parents=True, exist_ok=True)
        logger.info("ale-claw: launch — work_dir=%s task_id=%s", work_dir, task_id)

        # ---- 1. Drive-VM session (deployer-side, talks to eval cua-server) ----
        # In local executor this is host → VM RPC. In docker executor it's
        # container → VM RPC (container has --network host so endpoint reaches).
        from cua_bench.computers.remote import RemoteDesktopSession

        sb = self.executor.sandbox
        session = RemoteDesktopSession(
            api_url=sb.endpoint,
            os_type=sb.os,
            ephemeral=False,        # env lifecycle is owned by ALEEnv
            headless=True,
        )
        await session.check_status()

        # ---- 1b. MCP substrate (non-GUI tools route through the vm bridge) ----
        # Build the runtime object now (so build_tools can wire the backends to
        # it); it is *connected* later, around the drive loop, and torn down with
        # it. GUI stays on `session` in Phase 1. For the `local`/`docker`
        # executor the bridge runs on the host and points at the same cua-server
        # endpoint the harness already uses (cua_bridge_url == sb.endpoint), so
        # there is no extra network hop.
        mcp_runtime = None
        if cfg.substrate_transport == "mcp":
            from ale_run.agents._bootstrap import (
                cua_bridge_env,
                ensure_cua_mcp_server_at,
                ensure_node_npm,
                ensure_vm_mcp_server,
                vm_bridge_env,
            )
            from mcp.client.stdio import StdioServerParameters

            from .harness.tools.mcp_runtime import MCPRuntime

            node_path, _ = await ensure_node_npm()
            servers: dict[str, Any] = {}
            vm_bridge_dir = await ensure_vm_mcp_server(str(work_dir / "mcp" / "vm"))
            servers["vm"] = StdioServerParameters(
                command=node_path,
                args=[os.path.join(vm_bridge_dir, "src", "index.js")],
                env={**os.environ, **vm_bridge_env(self.executor)},
            )
            if cfg.gui_transport == "mcp":
                cua_bridge_dir = await ensure_cua_mcp_server_at(str(work_dir / "mcp" / "cua"))
                servers["cua"] = StdioServerParameters(
                    command=node_path,
                    args=[os.path.join(cua_bridge_dir, "src", "index.js")],
                    env={**os.environ, **cua_bridge_env(self.executor)},
                )
            mcp_runtime = MCPRuntime(servers)
            logger.info(
                "ale-claw: substrate_transport=mcp gui_transport=%s (servers=%s)",
                cfg.gui_transport, sorted(servers),
            )

        # ---- 2. Memory + session + subagent registry ----
        memory_store = MemoryStore(task_id=task_id, base_dir=str(memory_base))
        memory_store.init_session()
        if getattr(cfg, "skill_sources", None):
            _seed_skill_playbooks(memory_store, task_id, cfg.skill_sources)
        session_mgr = SessionManager(task_id=task_id, base_dir=str(session_base))
        session_mgr.init_session(model=cfg.model)
        registry = SubagentRegistry(persist_path=session_mgr.task_dir / "subagent-runs.jsonl")
        registry.restore()

        # ---- 3. Model resolution + context window ----
        resolved_model = resolve_model(cfg.model)
        summary_model = cfg.summary_model or cfg.auxiliary_model or cfg.model
        resolved_summary_model = (
            resolved_model if summary_model == cfg.model
            else resolve_model(summary_model)
        )
        ctx_override = os.environ.get("CONTEXT_WINDOW_OVERRIDE")
        if ctx_override:
            context_window_tokens = int(ctx_override)
        else:
            context_window_tokens = (
                resolved_model.context_window
                or resolve_context_window(cfg.model)
                or DEFAULT_CONTEXT_TOKENS
            )

        workspace_root: str | None = None    # permissive — full VM access
        host_workspace_root = str(memory_store.task_dir.resolve())

        # ---- 4. Thinking config ----
        thinking_config = self._build_thinking_config()
        thinking_api_params = thinking_config.to_api_params(cfg.model)
        gui_thinking_params = thinking_config.gui_params(cfg.gui_model or cfg.model)

        # ---- 5. Pre-build computer handler ----
        # gui_transport=mcp → drive GUI through the cua bridge; else the session
        # handler. The MCP handler inits lazily (the runtime connects later,
        # around the drive loop), so don't _initialize it here.
        computer_handler = None
        if not cfg.disable_main_computer:
            if cfg.gui_transport == "mcp" and mcp_runtime is not None:
                from .harness.tools.computer_handler import MCPComputerHandler
                computer_handler = MCPComputerHandler(mcp_runtime, os_type=sb.os)
            else:
                computer_handler = OpenClawComputerHandler(session.computer)
                await computer_handler._initialize()            # noqa: SLF001

        # ---- 6. Tools + disabled_tools filter ----
        tools = build_tools(
            session, memory_store,
            summary_model=summary_model,
            vision_thinking_params=thinking_config.vision_params(
                summary_model, runtime=resolved_summary_model,
            ),
            registry=registry,
            parent_session_dir=session_mgr.task_dir,
            default_model=cfg.model,
            auxiliary_model=cfg.auxiliary_model,
            thinking_params=thinking_api_params,
            gui_thinking_params=gui_thinking_params,
            disable_main_computer=cfg.disable_main_computer,
            disable_delegate_gui=cfg.disable_delegate_gui,
            gui_model=cfg.gui_model,
            workspace_root=workspace_root,
            host_workspace_root=host_workspace_root,
            context_window_tokens=context_window_tokens,
            computer_handler=computer_handler,
            mcp_runtime=mcp_runtime,
            api_key=cfg.api_key,
            api_base=cfg.api_base,
        )
        # Prep receives the real read/exec/web tools even when the main-agent
        # policy disables one of them. Its own session applies a narrower,
        # explicit allowlist and never receives solver skills or delegation.
        prep_tools = list(tools)
        if cfg.disabled_tools:
            from .harness.tools.tools import COMPUTER_TOOL_NAME, _is_computer_tool
            drop_computer = COMPUTER_TOOL_NAME in cfg.disabled_tools
            # The primary computer handler is not a BaseTool and does not expose
            # name="computer" (see _is_computer_tool), so the name filter alone
            # can't remove it. Drop it explicitly when "computer" is listed —
            # for headless Linux tasks this strips the GUI tool schema (~1.6 KB
            # per call) and stops the model wasting turns on screenshot actions.
            tools = [
                t for t in tools
                if getattr(t, "name", "") not in cfg.disabled_tools
                and not (drop_computer and _is_computer_tool(t))
            ]
            logger.info("ale-claw: disabled_tools=%s", cfg.disabled_tools)
        tool_summaries = get_tool_summaries(tools)

        # ---- 7. System prompt + AGENTS.md + TASK_MEMORY.md context ----
        agents_md = _HARNESS_AGENTS_MD.read_text(encoding="utf-8")
        context_files = [ContextFile(path="AGENTS.md", content=agents_md)]
        bootstrap = memory_store.get_bootstrap_context()
        if bootstrap:
            context_files.append(ContextFile(path="TASK_MEMORY.md", content=bootstrap))
        instructions = PromptBuilder().build(
            tool_summaries=tool_summaries, context_files=context_files,
            target_os=sb.os,
        )
        report = build_system_prompt_report(
            system_prompt=instructions, context_files=context_files,
            tool_summaries=tool_summaries, tools=tools,
        )
        session_mgr.set_system_prompt_report(report)

        # ---- 8. Overflow callback + agent ----
        overflow_cb = ContextOverflowCallback(
            model=cfg.model,
            context_window=context_window_tokens,
            instructions_tokens=len(instructions) // 4,
            resolved_model=resolved_model,
        )
        if session_mgr._state is not None:                       # noqa: SLF001
            session_mgr._state.context_tokens = overflow_cb.context_window  # noqa: SLF001
            session_mgr.save_state()

        agent = OpenClawComputerAgent(
            model=cfg.model,
            api_key=cfg.api_key,
            api_base=cfg.api_base,
            tools=tools,
            only_n_most_recent_images=3,
            trajectory_dir=trajectory_dir,
            instructions=instructions,
            use_prompt_caching=True,
            callbacks=[ToolLoggingCallback()],
            context_files=context_files,
            image_retention_mode=cfg.image_retention_mode,
            auto_screenshot=False,
            overflow_cb=overflow_cb,
            session_mgr=session_mgr,
            memory_store=memory_store,
            summary_model=summary_model,
            thinking_config=thinking_config,
            resolved_model=resolved_model,
            summary_runtime=resolved_summary_model,
            registry=registry,
            **thinking_api_params,
        )

        # ---- 9. Cross-run replay (always empty v1) ----
        prior_entries = session_mgr.load_history()
        replay_messages: list[dict[str, Any]] = []
        if prior_entries:
            replay_messages = build_replay_messages(prior_entries)
            replay_messages = sanitize_history(replay_messages)
            replay_messages = limit_history_turns(replay_messages, cfg.max_history_turns)
            replay_messages = sanitize_history(replay_messages)
            replay_messages = convert_to_responses_api_items(replay_messages)
        # ---- 10. Drive loop ----
        # The episode wall budget is orchestration-owned: the executor wraps
        # launch() in asyncio.wait_for(timeout=timeout_s) (derived from the
        # task), so we drive the loop directly here; a cancellation on the
        # budget propagates cleanly (no subprocess to reap).
        # litellm reads OPENROUTER_API_KEY / ANTHROPIC_API_KEY etc straight
        # from os.environ — operator populates the shell, no patching needed.
        max_steps = cfg.max_turns or 100
        total_usage = {
            "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "response_cost": 0.0,
        }
        step = 0
        task_completed = False
        transcript_path = work_dir / "openclaw_sessions" / task_id / "transcript.jsonl"
        prep_result = TaskPrepResult(status="disabled")
        reviewer_rounds: list[dict[str, Any]] = []
        reviewer_stop_reason = "disabled"
        reviewer_model = cfg.reviewer_audit_model or cfg.model
        reviewer_registry = (
            SubagentRegistry(
                max_concurrent=1,
                persist_path=session_mgr.task_dir / "reviewer-audit-runs.jsonl",
            )
            if cfg.reviewer_audit
            else None
        )
        prep_registry = (
            SubagentRegistry(
                max_concurrent=1,
                persist_path=session_mgr.task_dir / "task-prep-runs.jsonl",
            )
            if cfg.task_specific_prep
            else None
        )

        # Connect the MCP bridge(s) for the duration of the drive loop and tear
        # them down (terminating the node children) on any exit — success,
        # exception, or wall-budget cancellation. A startup failure here is
        # caught by the except below and surfaced as a failed run.
        mcp_stack = AsyncExitStack()
        try:
            if mcp_runtime is not None:
                await mcp_stack.enter_async_context(mcp_runtime)

            async def _build_prep_branch() -> TaskPrepResult:
                if not cfg.task_specific_prep:
                    return TaskPrepResult(status="disabled")
                assert prep_registry is not None
                try:
                    prep_model = cfg.task_specific_prep_model or cfg.model
                    return await run_task_specific_prep(
                        interface=session.interface,
                        os_type=sb.os,
                        task_id=cfg.task_specific_prep_task_id or task_id,
                        task_root=cfg.task_specific_prep_task_root,
                        task_prompt=prompt,
                        model=prep_model,
                        summary_model=summary_model,
                        tools=prep_tools,
                        registry=prep_registry,
                        parent_session_dir=session_mgr.task_dir,
                        max_steps=cfg.task_specific_prep_max_steps,
                        timeout_s=cfg.task_specific_prep_timeout_s,
                        thinking_params=thinking_config.to_api_params(prep_model),
                        summary_runtime=resolved_summary_model,
                        api_key=cfg.api_key,
                        api_base=cfg.api_base,
                    )
                except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
                    logger.warning("task-specific prep crashed; solver continues: %s", exc)
                    return TaskPrepResult(
                        status="failed", error=f"{type(exc).__name__}: {exc}"
                    )

            # The prep branch shares only the original public task surface and
            # is staged after it finishes; its output is never a predecessor of
            # the writer's, only inlined into the writer's first prompt.
            prep_result = await _build_prep_branch()

            solver_prompt = prompt
            if cfg.task_specific_prep:
                (work_dir / "task_prep.md").write_text(
                    prep_result.report or NO_PREP_SENTINEL,
                    encoding="utf-8",
                )
                for relative, artifact_content in sorted(
                    prep_result.artifacts.items()
                ):
                    artifact_log_path = (
                        work_dir / "task_prep_bundle" /
                        Path(*_prep_artifact_parts(relative))
                    )
                    artifact_log_path.parent.mkdir(parents=True, exist_ok=True)
                    artifact_log_path.write_text(artifact_content, encoding="utf-8")
                (work_dir / "task_prep_meta.json").write_text(
                    json.dumps(
                        prep_result.metadata(), indent=2, ensure_ascii=True
                    ) + "\n",
                    encoding="utf-8",
                )
                logger.info(
                    "task-specific prep: status=%s env=%s attempt=%s "
                    "findings=%d report_chars=%d",
                    prep_result.status,
                    prep_result.environment_status,
                    (prep_result.attempt or {}).get("outcome") or "none",
                    prep_result.finding_count,
                    len(prep_result.report),
                )
                if prep_result.report:
                    prep_report_path = await _stage_prep_bundle(
                        session.interface,
                        task_root=cfg.task_specific_prep_task_root,
                        os_type=sb.os,
                        content=prep_result.report,
                        artifacts=prep_result.artifacts,
                    )
                    # The report is consumed as a file the writer opens, not as
                    # inlined text: only the digest (runtime state, the core-step
                    # breakage, findings, where the rest is) enters the prompt.
                    # An empty digest means prep found nothing actionable, and
                    # then nothing is injected at all - announcing "prep ran"
                    # with no content would only set an agenda at turn zero.
                    digest = build_prep_digest(prep_result, prep_report_path)
                    if digest:
                        solver_prompt = (
                            f"{prompt.rstrip()}\n\n"
                            f"## Task-specific prior research\n{digest}"
                        )

            run_input = (
                replay_messages + [{"role": "user", "content": solver_prompt}]
                if replay_messages else solver_prompt
            )

            async def _drive(input_messages: Any) -> tuple[bool, str]:
                nonlocal step
                completed = False
                response_text: list[str] = []
                async for result in agent.run(input_messages):
                    sys.stdout.flush()
                    text = _assistant_text(result.get("output", []))
                    if text:
                        response_text.append(text)
                    step += 1
                    for k in total_usage:
                        total_usage[k] += result["usage"].get(k, 0)
                    session_mgr.update_step_count(step)
                    session_mgr.update_tokens(
                        result["usage"].get("input_tokens", 0),
                        result["usage"].get("output_tokens", 0),
                    )
                    if step >= max_steps:
                        logger.info("ale-claw: max_steps %d reached", max_steps)
                        break
                    if has_done_signal(result.get("output", [])):
                        logger.info("ale-claw: done signal at step %d", step)
                        completed = True
                        break
                return completed, "\n".join(response_text)

            task_completed, _ = await _drive(run_input)

            # ---- reviewer audit (the ``reviewer`` arm) --------------------
            # An independent, source-grounded delivery audit with a hard
            # zero-discrepancy gate: this loop mechanically coerces the writer's
            # "done" to "continue" until every discrepancy counter is zero over
            # the complete bundle. Every step is fail-open — an auditor crash or
            # a parse failure ends the loop on the writer's own last output and
            # never fails the unit.
            reviewer_revisions = 0
            reviewer_total_usage = {"input_tokens": 0, "output_tokens": 0}
            if cfg.reviewer_audit and not cfg.task_specific_prep_task_root:
                reviewer_stop_reason = "no_public_task_root"
            elif cfg.reviewer_audit:
                assert reviewer_registry is not None
                reviewer_stop_reason = "max_rounds"
                reviewer_disputes: set[str] = set()
                last_audit_source_sha: str | None = None
                # Pre-repair snapshot for the regression guard: each round's new
                # snapshot is compared against this to catch a repair that
                # collapsed the bundle (see snapshot_regressed / restore_snapshot).
                pre_repair_snapshot = None
                reviewer_regression: str | None = None
                for round_index in range(cfg.reviewer_audit_max_rounds + 1):
                    try:
                        snapshot = await snapshot_output(
                            interface=session.interface,
                            task_root=cfg.task_specific_prep_task_root,
                            os_type=sb.os,
                            iteration=f"audit{round_index}",
                        )
                    except Exception as exc:  # audit never fails the writer
                        logger.warning("could not snapshot for reviewer audit: %s", exc)
                        reviewer_stop_reason = "snapshot_error"
                        break
                    # Repair-regression guard. If the previous round's repair
                    # collapsed the bundle (deleted files / replaced verbatim
                    # evidence with a summary), the audit's narrow counters won't
                    # see it but a delivery grader will. Roll back to the
                    # pre-repair snapshot and stop, deterministically, before the
                    # regressed bundle is what gets graded.
                    if round_index > 0 and pre_repair_snapshot is not None:
                        reason = snapshot_regressed(snapshot, pre_repair_snapshot)
                        if reason is not None:
                            try:
                                await restore_snapshot(
                                    interface=session.interface,
                                    task_root=cfg.task_specific_prep_task_root,
                                    snapshot=pre_repair_snapshot,
                                )
                                reviewer_stop_reason = "repair_regressed"
                            except Exception as exc:  # never crash the writer
                                logger.warning(
                                    "repair regressed but rollback failed: %s", exc
                                )
                                reviewer_stop_reason = "repair_regressed_restore_failed"
                            reviewer_regression = reason
                            logger.warning(
                                "reviewer repair regressed bundle (%s); %s",
                                reason, reviewer_stop_reason,
                            )
                            reviewer_rounds.append({
                                "round": round_index,
                                "repair_regressed": reason,
                                "rolled_back": reviewer_stop_reason == "repair_regressed",
                                "pre_repair_bytes": pre_repair_snapshot.total_bytes,
                                "pre_repair_file_count": pre_repair_snapshot.file_count,
                                "post_repair_bytes": snapshot.total_bytes,
                                "post_repair_file_count": snapshot.file_count,
                            })
                            break
                    # Identical output means the writer reviewed the last audit
                    # and chose to keep its deliverable — stop, don't re-audit.
                    if round_index > 0 and snapshot.source_sha256 == last_audit_source_sha:
                        reviewer_stop_reason = "writer_no_change"
                        break
                    if round_index > 0:
                        reviewer_revisions += 1
                    last_audit_source_sha = snapshot.source_sha256
                    pre_repair_snapshot = snapshot

                    try:
                        verdict, usage, raw = await run_reviewer_audit_with_retry(
                            interface=session.interface,
                            task_prompt=prompt,
                            snapshot_path=snapshot.path,
                            round_index=round_index,
                            model=reviewer_model,
                            summary_model=summary_model,
                            tools=prep_tools,
                            registry=reviewer_registry,
                            parent_session_dir=session_mgr.task_dir,
                            max_steps=cfg.reviewer_audit_max_steps,
                            thinking_params=thinking_config.to_api_params(reviewer_model),
                            summary_runtime=resolved_summary_model,
                            api_key=cfg.api_key,
                            api_base=cfg.api_base,
                        )
                    except Exception as exc:  # audit never fails the writer
                        logger.warning("reviewer audit crashed; writer output kept: %s", exc)
                        reviewer_stop_reason = "audit_error"
                        break
                    reviewer_total_usage["input_tokens"] += usage.input_tokens
                    reviewer_total_usage["output_tokens"] += usage.output_tokens

                    effective = verdict.effective_status(reviewer_disputes)
                    record = verdict.metadata()
                    record["round"] = round_index
                    record["effective_status"] = effective
                    record["gate_passes"] = verdict.gate_passes(reviewer_disputes)
                    record["outstanding_counters"] = verdict.outstanding_counters(
                        reviewer_disputes
                    )
                    record["writer_disputes"] = sorted(reviewer_disputes)
                    record["snapshot_path"] = snapshot.path
                    record["snapshot_source_sha256"] = snapshot.source_sha256
                    record["snapshot_file_count"] = snapshot.file_count
                    record["agent_usage"] = asdict(usage)
                    audit_report_path = None
                    try:
                        audit_report_path = await stage_verifier_report(
                            session.interface,
                            task_root=cfg.task_specific_prep_task_root,
                            filename=f"reviewer_audit_round_{round_index}.json",
                            report=record,
                        )
                    except Exception as exc:  # staging is best-effort
                        logger.warning("could not stage reviewer audit report: %s", exc)
                    record["writer_report_path"] = audit_report_path
                    reviewer_rounds.append(record)
                    (work_dir / f"reviewer_audit_round_{round_index}.json").write_text(
                        json.dumps(record, indent=2, ensure_ascii=True) + "\n",
                        encoding="utf-8",
                    )

                    # Gate decision. `done` only when the mechanical gate agrees.
                    if effective == "done":
                        reviewer_stop_reason = "gate_passed"
                        break
                    if effective == "blocked":
                        reviewer_stop_reason = "blocked"
                        break
                    if round_index >= cfg.reviewer_audit_max_rounds:
                        break

                    # Push source-grounded repair feedback and let the writer act.
                    feedback_prompt = build_audit_feedback_prompt(
                        verdict,
                        disputes=reviewer_disputes,
                        report_path=audit_report_path,
                        round_index=round_index,
                    )
                    # Allowlist = the artifacts this round's findings actually
                    # named. The repair is scoped to these; everything else the
                    # writer touches is reverted below, so a whole-pipeline re-run
                    # can't clobber an un-audited graded artifact.
                    repair_allowlist = {
                        f.artifact
                        for f in verdict.outstanding(reviewer_disputes)
                        if f.artifact
                    }
                    repair_pre_snapshot = pre_repair_snapshot
                    repair_history = build_replay_messages(session_mgr.load_history())
                    repair_history = sanitize_history(repair_history)
                    repair_history = limit_history_turns(
                        repair_history, cfg.max_history_turns
                    )
                    repair_history = sanitize_history(repair_history)
                    repair_input = convert_to_responses_api_items(repair_history)
                    repair_input.append({"role": "user", "content": feedback_prompt})
                    repair_completed, writer_response = await _drive(repair_input)
                    task_completed = repair_completed or task_completed
                    # Snapshot reconcile: keep only the allowlisted (named) paths
                    # from the repaired output/, revert every other path to the
                    # pre-repair snapshot. Finer than the byte-guard above and
                    # composes with it. Fail-open: on any error keep the writer's
                    # output untouched and record it.
                    if repair_pre_snapshot is not None:
                        try:
                            reconcile = await reconcile_to_allowlist(
                                interface=session.interface,
                                task_root=cfg.task_specific_prep_task_root,
                                snapshot=repair_pre_snapshot,
                                allowlist=repair_allowlist,
                            )
                            logger.info(
                                "reviewer round %d reconcile: mode=%s kept=%s "
                                "allowlist=%s",
                                round_index, reconcile.get("mode"),
                                reconcile.get("kept"), reconcile.get("allowlist"),
                            )
                        except Exception as exc:  # never crash the writer
                            logger.warning(
                                "reviewer round %d allowlist reconcile failed; "
                                "keeping writer output: %s",
                                round_index, exc,
                            )
                            reconcile = {"mode": "error", "error": str(exc)}
                        reviewer_rounds.append({
                            "round": round_index,
                            "reconcile": reconcile,
                        })
                    if step >= max_steps:
                        reviewer_stop_reason = "writer_step_limit"
                        break
                    # Writer may reject a finding with `AUDIT_DISPUTE <id>`; a
                    # disputed id stops counting against the gate (carried
                    # forward, harmless if the fresh auditor re-derives new ids).
                    reviewer_disputes.update(parse_audit_disputes(
                        writer_response,
                        {f.id for f in verdict.findings},
                    ))

            if cfg.reviewer_audit:
                # reviewer_rounds interleaves real audit records with reconcile/
                # regression bookkeeping entries; roll the meta up over the audit
                # records only (they alone carry the gate + counters).
                audit_records = [r for r in reviewer_rounds if "gate_passes" in r]
                reviewer_meta = {
                    "protocol_digest": reviewer_audit_protocol_digest(),
                    "rounds": len(audit_records),
                    "repairs": reviewer_revisions,
                    "stop_reason": reviewer_stop_reason,
                    "gate_passed": bool(
                        audit_records and audit_records[-1].get("gate_passes")
                    ),
                    "final_counters": (
                        audit_records[-1].get("counters") if audit_records else {}
                    ),
                    "max_rounds": cfg.reviewer_audit_max_rounds,
                    "max_steps": cfg.reviewer_audit_max_steps,
                    "model": reviewer_model,
                    "agent_usage": reviewer_total_usage,
                    "repair_regressed": reviewer_regression,
                }
                (work_dir / "reviewer_audit_meta.json").write_text(
                    json.dumps(reviewer_meta, indent=2, ensure_ascii=True) + "\n",
                    encoding="utf-8",
                )

        except Exception as exc:                             # noqa: BLE001
            logger.exception("ale-claw: agent.run threw")
            return AgentRunResult(
                status="failed",
                duration_s=time.monotonic() - t0,
                error=f"{type(exc).__name__}: {exc}",
                transcript_path=str(transcript_path) if transcript_path.exists() else None,
            )
        finally:
            await mcp_stack.aclose()

        # Outcome mapping
        if task_completed:
            status = "completed"
            error: str | None = None
        elif step >= max_steps:
            status = "completed"     # finished at step budget — not a wall-clock failure
            error = None
        else:
            status = "failed"
            error = "loop exited without done signal"

        return AgentRunResult(
            status=status,
            duration_s=time.monotonic() - t0,
            transcript_path=str(transcript_path) if transcript_path.exists() else None,
            error=error,
        )

    @classmethod
    def parse_artifacts(
        cls,
        *,
        work_dir: Path,
        config: AleClawConfig,
        run_result: AgentRunResult,
        builder: TrajectoryBuilder,
    ) -> None:
        """Parse on-disk transcripts → ATIF Steps via the in-tree translator."""
        if not work_dir.exists():
            builder.add_step(
                source="system",
                message=f"ale-claw: work_dir missing {work_dir}",
                extra={"reason": "no_work_dir"},
            )
            return
        try:
            parse_transcripts_into(work_dir, builder)
        except Exception as exc:                                # noqa: BLE001
            logger.exception("ale-claw: parse_artifacts failed")
            builder.add_step(
                source="system",
                message=f"transcript parse failed: {type(exc).__name__}: {exc}",
                extra={"reason": "parse_error"},
            )
        # Surface useful debug info on trajectory.extra
        builder.trajectory.extra.setdefault("ale_claw", {}).update({
            "work_dir": str(work_dir),
            "transcript_path": run_result.transcript_path,
            "run_status": run_result.status,
        })

    # =========================================================================
    # helpers (private)
    # =========================================================================

    def _build_thinking_config(self) -> ThinkingConfig:
        c: AleClawConfig = self.config  # type: ignore[assignment]
        level = (
            ThinkLevel(c.thinking_level) if c.thinking_level
            else resolve_thinking_default(c.model)
        )
        flush = ThinkLevel(c.flush_thinking_level) if c.flush_thinking_level else level
        compact = (
            ThinkLevel(c.compaction_thinking_level) if c.compaction_thinking_level
            else level
        )
        vision = ThinkLevel(c.vision_thinking_level)
        gui = ThinkLevel(c.gui_thinking_level)
        return ThinkingConfig(
            level=level, flush_level=flush, compaction_level=compact,
            vision_level=vision, gui_level=gui,
        )
