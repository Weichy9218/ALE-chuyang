"""Fresh sub-agent runner + snapshot value types shared by the reviewer arm.

This module used to build/audit/freeze public test suites for the retired
``verifier`` arm; that machinery was removed 2026-08-05. What survives is what
the ``reviewer`` arm still imports:

  * ``AgentUsage`` — token/turn accounting for a sub-agent run.
  * ``ArtifactSnapshot`` — the receipt for one immutable ``output/`` snapshot
    (consumed by ``verifier_runtime``'s regression guard + allowlist reconcile).
  * ``_run_fresh_agent`` — spawn an independent, memory-less sub-agent (used by
    ``reviewer_audit`` to run the source-grounded auditor).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# The fresh auditor gets only read/exec/vision — never write/edit or delegation,
# so it can recompute from the public inputs but cannot touch the writer's output.
VERIFIER_AGENT_TOOL_NAMES = frozenset({"read", "exec", "analyze_image"})


@dataclass
class AgentUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    duration_s: float = 0.0
    llm_turns: int = 0
    tool_calls: int = 0
    tool_call_counts: dict[str, int] = field(default_factory=dict)

    def add(self, other: AgentUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.duration_s += other.duration_s
        self.llm_turns += other.llm_turns
        self.tool_calls += other.tool_calls
        for name, count in other.tool_call_counts.items():
            self.tool_call_counts[name] = self.tool_call_counts.get(name, 0) + count


@dataclass(frozen=True)
class ArtifactSnapshot:
    path: str
    sha256: str
    source_sha256: str
    file_count: int
    total_bytes: int = 0
    rejected_symlinks_path: str | None = None


async def _run_fresh_agent(
    *,
    label: str,
    task: str,
    system_prompt: str,
    model: str,
    summary_model: str,
    tools: list,
    registry: Any,
    parent_session_dir: Path,
    max_steps: int,
    thinking_params: dict[str, Any] | None,
    summary_runtime: Any | None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> tuple[str, AgentUsage]:
    """Run one independent, memory-less sub-agent to completion.

    ``memory_store=None`` and the restricted tool allowlist make this a clean
    room: the auditor sees only what its ``task``/``system_prompt`` carry plus
    the public inputs it can read, never the writer's session or memory. Raises
    if the sub-agent hits its step ceiling; the caller fails open.
    """
    from .harness.subagent.subagent_registry import SubagentType
    from .harness.subagent.subagent_session import GeneralSubagentSession

    run = registry.register(type=SubagentType.GENERAL, task=task, label=label, model=model)
    registry.mark_running(run.run_id)
    session = GeneralSubagentSession(
        run_id=run.run_id,
        task=task,
        model=model,
        tools=tools,
        registry=registry,
        summary_model=summary_model,
        parent_session_dir=parent_session_dir,
        memory_store=None,
        max_steps=max_steps,
        thinking_params=thinking_params,
        summary_runtime=summary_runtime,
        allowed_tool_names=VERIFIER_AGENT_TOOL_NAMES,
        system_prompt=system_prompt,
        api_key=api_key,
        api_base=api_base,
    )
    registry.attach_inbox(run.run_id, session.inbox)
    started = time.monotonic()
    try:
        text = (await session.run()).strip()
        if text.startswith("(subagent reached max steps"):
            raise RuntimeError(f"{label} reached max steps")
        registry.complete(run.run_id, text, session.usage)
        return text, AgentUsage(
            input_tokens=session.usage.input_tokens,
            output_tokens=session.usage.output_tokens,
            duration_s=time.monotonic() - started,
            llm_turns=session.llm_turns,
            tool_calls=session.tool_call_count,
            tool_call_counts=dict(sorted(session.tool_call_counts.items())),
        )
    except Exception as exc:
        registry.fail(run.run_id, str(exc), session.usage)
        raise
