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

import asyncio
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
from .contract_crosscheck import crosscheck_contract, render_crosscheck_note
from .task_prep import (
    NO_PREP_SENTINEL,
    TaskPrepResult,
    build_prep_digest,
    run_task_specific_prep,
)
from .verifier import (
    VERIFIER_PROTOCOL_VERSION,
    VerificationResult,
    VerifierBuildResult,
    build_candidate_suite,
    build_feedback_prompt,
    finalize_candidate_suite,
    parse_disputes,
)
from .verifier_precheck import WriterVerifyTool
from .verifier_runtime import (
    execute_test_suite,
    snapshot_manifest,
    snapshot_output,
    stage_test_suite,
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
        created_dirs: set[str] = set()
        for relative, artifact_content in sorted(artifacts.items()):
            if report_dir not in created_dirs:
                await interface.create_dir(report_dir)
                created_dirs.add(report_dir)
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
        # Pre-submission verification: the writer may run the frozen suite
        # against its own draft before DONE. The tool is registered now (the
        # agent's tool schemas are fixed at construction) and the frozen suite
        # is bound after the builder finishes; until then it reports
        # unavailable. Listing "verify" in disabled_tools removes it like any
        # other tool.
        verify_tool: WriterVerifyTool | None = None
        if cfg.verifier and cfg.verifier_writer_checks > 0:
            verify_tool = WriterVerifyTool(
                interface=session.interface,
                os_type=sb.os,
                task_root=cfg.task_specific_prep_task_root,
                task_prompt=prompt,
                max_calls=cfg.verifier_writer_checks,
                work_dir=work_dir,
            )
            tools.append(verify_tool)
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
            if verify_tool is not None and verify_tool not in tools:
                verify_tool = None
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
        verifier_build = VerifierBuildResult(status="disabled")
        prep_result = TaskPrepResult(status="disabled")
        verifier_rounds: list[dict[str, Any]] = []
        verifier_stop_reason = "disabled"
        verifier_model = cfg.verifier_model or cfg.model
        verifier_registry = (
            SubagentRegistry(
                max_concurrent=1,
                persist_path=session_mgr.task_dir / "verifier-runs.jsonl",
            )
            if cfg.verifier
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

            async def _build_verifier_branch() -> VerifierBuildResult:
                if not cfg.verifier:
                    return VerifierBuildResult(status="disabled")
                if not cfg.task_specific_prep_task_root:
                    return VerifierBuildResult(
                        status="error", error="public task root is unavailable"
                    )
                assert verifier_registry is not None
                try:
                    return await build_candidate_suite(
                        interface=session.interface,
                        os_type=sb.os,
                        task_id=cfg.task_specific_prep_task_id or task_id,
                        task_root=cfg.task_specific_prep_task_root,
                        task_prompt=prompt,
                        model=verifier_model,
                        summary_model=summary_model,
                        tools=prep_tools,
                        registry=verifier_registry,
                        parent_session_dir=session_mgr.task_dir,
                        max_steps=cfg.verifier_max_steps,
                        thinking_params=thinking_config.to_api_params(verifier_model),
                        summary_runtime=resolved_summary_model,
                        api_key=cfg.api_key,
                        api_base=cfg.api_base,
                    )
                except Exception as exc:  # noqa: BLE001 - audit is best-effort
                    logger.warning("verifier builder crashed; writer continues: %s", exc)
                    return VerifierBuildResult(
                        status="error", error=f"{type(exc).__name__}: {exc}"
                    )

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
                        deliver_self_check=cfg.task_specific_prep_self_check,
                    )
                except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
                    logger.warning("task-specific prep crashed; solver continues: %s", exc)
                    return TaskPrepResult(
                        status="failed", error=f"{type(exc).__name__}: {exc}"
                    )

            # The builders share only the original public task surface. Running
            # them concurrently prevents either optional branch from becoming a
            # semantic predecessor of the other; neither output is staged yet.
            verifier_build, prep_result = await asyncio.gather(
                _build_verifier_branch(), _build_prep_branch()
            )

            # Phase B runs now: prep has finished changing the sandbox, so the
            # fixture preflight measures the environment the writer and
            # executor will actually get. Purely mechanical - no LLM agent.
            if cfg.verifier and verifier_build.candidate is not None:
                try:
                    verifier_build = await finalize_candidate_suite(
                        interface=session.interface,
                        task_root=cfg.task_specific_prep_task_root,
                        candidate=verifier_build.candidate,
                        usage=verifier_build.usage,
                    )
                except Exception as exc:  # noqa: BLE001 - writer continues
                    logger.warning("verifier freeze crashed; writer continues: %s", exc)
                    verifier_build = VerifierBuildResult(
                        status="error", error=f"{type(exc).__name__}: {exc}"
                    )

            if verifier_build.suite is not None:
                (work_dir / "verifier_suite.json").write_text(
                    json.dumps(
                        verifier_build.suite.manifest,
                        indent=2,
                        ensure_ascii=True,
                    ) + "\n",
                    encoding="utf-8",
                )
            if verify_tool is not None:
                if verifier_build.suite is not None:
                    verify_tool.bind_suite(verifier_build.suite)
                else:
                    verify_tool.mark_unavailable(
                        verifier_build.error or verifier_build.status
                    )

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
                    "task-specific prep: status=%s env=%s contract=%d "
                    "findings=%d report_chars=%d",
                    prep_result.status,
                    prep_result.environment_status,
                    prep_result.contract_items,
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
                    # inlined text: only the digest (runtime state, self-check
                    # command, where the rest is) enters the first prompt.
                    if prep_report_path is None and prep_result.self_check:
                        prep_result.self_check = None
                    digest = build_prep_digest(prep_result, prep_report_path)
                    solver_prompt = (
                        f"{prompt.rstrip()}\n\n"
                        f"## Task-specific prior research\n{digest}"
                    )

            # Mechanical contract cross-check: two independent readings of the
            # same public surface exist only in the prep+verifier arm; compare
            # the files they cite and surface the difference to the writer.
            if prep_result.contract and verifier_build.suite is not None:
                try:
                    crosscheck = crosscheck_contract(
                        prep_result.contract, verifier_build.suite.manifest
                    )
                    (work_dir / "contract_crosscheck.json").write_text(
                        json.dumps(crosscheck, indent=2, ensure_ascii=True) + "\n",
                        encoding="utf-8",
                    )
                    note = render_crosscheck_note(crosscheck)
                    if note:
                        solver_prompt = f"{solver_prompt.rstrip()}\n\n{note}"
                except Exception as exc:  # noqa: BLE001 - advisory, never blocks
                    logger.warning("contract crosscheck failed: %s", exc)

            if verify_tool is not None and verifier_build.suite is not None:
                solver_prompt = (
                    f"{solver_prompt.rstrip()}\n\n"
                    "## Pre-submission verification\n"
                    "A public verifier suite was frozen from the task materials "
                    "before you started. You may run it against your current "
                    f"`output/` up to {verify_tool.max_calls} times with the "
                    "`verify` tool. Its results are advisory measurements "
                    "against the task's stated contract, never verdicts. Run "
                    "it once `output/` holds a complete draft, and weigh the "
                    "report while you still have budget. Passing it covers "
                    "only the publicly testable part of the task; it is not a "
                    "completion signal."
                )

            # Control arm for pricing the verifier: the same "recheck before
            # DONE" impulse with no frozen tests behind it.
            if cfg.writer_self_review_hint:
                solver_prompt = (
                    f"{solver_prompt.rstrip()}\n\n"
                    "## Pre-submission self-review\n"
                    "Before you declare DONE, reread the task prompt and "
                    "`/input`, and check `output/` against every obligation "
                    "they state - required files at their stated paths, field "
                    "names as spelled, identifiers preserved, counts, "
                    "ordering, encoding, and cross-file consistency. Nothing "
                    "is measured for you; this review is yours."
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

            task_completed, main_writer_text = await _drive(run_input)

            suite = verifier_build.suite
            if cfg.verifier and suite is not None:
                try:
                    suite = await stage_test_suite(
                        interface=session.interface,
                        task_root=cfg.task_specific_prep_task_root,
                        manifest=suite.manifest,
                    )
                    verifier_build.suite = suite
                except Exception as exc:  # verifier errors never fail the writer
                    logger.warning("could not stage frozen verifier suite: %s", exc)
                    verifier_build.status = "error"
                    verifier_build.error = f"{type(exc).__name__}: {exc}"
                    verifier_build.suite = None
                    suite = None
            writer_disputes: set[str] = set()
            if suite is not None and main_writer_text:
                # A dispute raised against a pre-submission `verify` report uses
                # the same protocol as the post-DONE review rounds, so honor it.
                # Blanket pre-emptive disputing is a theoretical hole, but with
                # zero observed disputes across every run so far, gating this
                # channel would be complexity spent on an attack that has never
                # happened; revisit only with a real abuse sample.
                writer_disputes.update(parse_disputes(
                    main_writer_text,
                    {test["check"] for test in suite.manifest["tests"]},
                ))
            verifier_revisions = 0
            if cfg.verifier and suite is not None:
                assert verifier_registry is not None
                verifier_stop_reason = "max_review_rounds"
                last_source_sha: str | None = None
                for iteration in range(cfg.verifier_max_review_rounds + 1):
                    try:
                        snapshot = await snapshot_output(
                            interface=session.interface,
                            task_root=cfg.task_specific_prep_task_root,
                            os_type=sb.os,
                            iteration=iteration,
                        )
                    except Exception as exc:  # verifier errors never fail the writer
                        logger.warning("could not create verifier snapshot: %s", exc)
                        snapshot = None
                    else:
                        # A review round only matters when the Writer actually
                        # changed output; identical output means the Writer
                        # reviewed and chose to keep it, so stop.
                        if iteration > 0 and snapshot.source_sha256 == last_source_sha:
                            verifier_stop_reason = "writer_no_change"
                            break
                        if iteration > 0:
                            verifier_revisions += 1
                        last_source_sha = snapshot.source_sha256
                    if snapshot is None:
                        result = VerificationResult(
                            overall="error",
                            suite_sha256=suite.sha256,
                            snapshot_sha256="",
                            error="could not snapshot writer output",
                        )
                    else:
                        try:
                            result = await execute_test_suite(
                                interface=session.interface,
                                task_root=cfg.task_specific_prep_task_root,
                                task_prompt=prompt,
                                suite=suite,
                                snapshot=snapshot,
                            )
                        except Exception as exc:  # verifier errors never fail the writer
                            logger.warning("could not run verifier suite: %s", exc)
                            result = VerificationResult(
                                overall="error",
                                suite_sha256=suite.sha256,
                                snapshot_sha256=snapshot.sha256,
                                error=f"{type(exc).__name__}: {exc}",
                            )
                    record = result.metadata()
                    record["iteration"] = iteration
                    record["snapshot_path"] = snapshot.path if snapshot else None
                    record["snapshot_file_count"] = snapshot.file_count if snapshot else 0
                    record["snapshot_source_sha256"] = (
                        snapshot.source_sha256 if snapshot else None
                    )
                    record["snapshot_manifest"] = (
                        await snapshot_manifest(session.interface, snapshot)
                        if snapshot else []
                    )
                    record["writer_disputes"] = sorted(writer_disputes)
                    writer_report_path = await stage_verifier_report(
                        session.interface,
                        task_root=cfg.task_specific_prep_task_root,
                        filename=f"round_{iteration}.json",
                        report=record,
                    )
                    record["writer_report_path"] = writer_report_path
                    verifier_rounds.append(record)
                    (work_dir / f"verifier_round_{iteration}.json").write_text(
                        json.dumps(record, indent=2, ensure_ascii=True) + "\n",
                        encoding="utf-8",
                    )

                    # Re-invocation is driven by the presence of a safe, reproducible
                    # observation to review (hard mismatch or advisory item), not by
                    # blocking-fail alone. Execution errors and coverage gaps are
                    # informational and never force a round.
                    reviewable = result.hard_mismatches + result.review_items
                    outstanding = [
                        check for check in reviewable
                        if check["check"] not in writer_disputes
                    ]
                    if not result.needs_review:
                        verifier_stop_reason = result.overall
                        break
                    if not outstanding:
                        verifier_stop_reason = "writer_disputed"
                        break
                    if iteration >= cfg.verifier_max_review_rounds:
                        break

                    feedback_prompt = build_feedback_prompt(
                        result,
                        report_path=writer_report_path,
                    )
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
                    if step >= max_steps:
                        verifier_stop_reason = "writer_step_limit"
                        break
                    disputed = parse_disputes(
                        writer_response,
                        {check["check"] for check in reviewable},
                    )
                    writer_disputes.update(disputed)
            elif cfg.verifier:
                verifier_stop_reason = verifier_build.status

            if cfg.verifier:
                verifier_meta = {
                    "protocol": VERIFIER_PROTOCOL_VERSION,
                    "status": verifier_build.status,
                    "agent_usage": asdict(verifier_build.usage),
                    "builder_error": verifier_build.error,
                    "lint_dropped": list(verifier_build.dropped),
                    "rounds": len(verifier_rounds),
                    "repairs": verifier_revisions,
                    "writer_disputes": sorted(writer_disputes),
                    "stop_reason": verifier_stop_reason,
                    "writer_checks_max": (
                        verify_tool.max_calls if verify_tool is not None else 0
                    ),
                    "writer_checks_used": (
                        verify_tool.calls_used if verify_tool is not None else 0
                    ),
                    "writer_check_overalls": (
                        [record.get("overall") for record in verify_tool.records]
                        if verify_tool is not None else []
                    ),
                }
                (work_dir / "verifier_meta.json").write_text(
                    json.dumps(verifier_meta, indent=2, ensure_ascii=True) + "\n",
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
