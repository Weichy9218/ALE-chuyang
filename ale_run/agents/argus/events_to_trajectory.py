"""Argus event log → ALE trajectory steps.

Argus writes one JSONL row per orchestration event to
``ARGUS_SKILL_HOME/projects/<session>/events.jsonl``. Three row families matter
here:

``agent.io.start`` / ``agent.io.complete``
    One pair per role invocation (``run_label`` is ``manager.*`` /
    ``planner.*`` / ``engineer.*`` / ``reviewer.*``). The complete row carries
    the token counts.

``agent.io.stream``
    The raw ``codex exec --json`` NDJSON frames of that invocation, one per
    row under ``line``. This is where the actual tool calls, shell commands,
    MCP calls, and assistant messages live — the same frame format the codex
    agent's own ``parse_artifacts`` consumes, so that mapping is reused rather
    than reimplemented. These rows land in a **sibling** file,
    ``agent_io.jsonl`` (``_io_log.py`` derives it with
    ``log_path.with_name("agent_io.jsonl")``), so both files are read and
    merged on ``ts``. The sibling exists only when
    ``ARGUS_SKILL_AGENT_IO_MODE`` is the default ``full``; in ``compact`` mode
    the trajectory degrades to role-level steps, which is a gap worth stating
    rather than hiding.

Everything else (``life.mission.*``, ``round.*``, budget events) becomes a
``source="system"`` marker step so the role structure is legible in the
trajectory without inventing agent turns that did not happen.

A missing or truncated log is a valid outcome (SIGKILL on episode timeout):
emit one system step describing the gap and return cleanly.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ale_run.base_interface import (
    AgentRunResult,
    StepMetrics,
    TrajectoryBuilder,
)

logger = logging.getLogger(__name__)

#: Orchestration events surfaced as system markers. Everything else is noise
#: for a trajectory reader (budget reservations, status heartbeats, stream
#: bookkeeping) and is dropped.
_MARKER_TYPES = frozenset({
    "life.manager.intent.started",
    "life.manager.intent.completed",
    "life.mission.started",
    "life.mission.completed",
    "life.mission.failed",
    "life.mission.skipped",
    "loop.start",
    "loop.done",
    "round.start",
    "round.main.completed",
    "round.review.completed",
    "round.escalated",
    "round.stall",
    "agent.io.error",
})


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # A SIGKILL mid-append leaves one torn line; the rest is good.
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _merged_rows(events_path: Path, stream_path: Path) -> list[dict[str, Any]]:
    """Both logs interleaved on ``ts``.

    Each file is append-ordered and truthful on its own, so a stable sort on
    the timestamp reconstructs the real sequence. Orchestration rows are placed
    ahead of stream rows on an exact tie: a role's ``agent.io.start`` and its
    first frame can share a timestamp, and the start must come first for the
    per-call NDJSON state to be initialised.
    """
    tagged: list[tuple[float, int, dict[str, Any]]] = []
    for rank, path in ((0, events_path), (1, stream_path)):
        for row in _read_rows(path):
            try:
                ts = float(row.get("ts") or 0.0)
            except (TypeError, ValueError):
                ts = 0.0
            tagged.append((ts, rank, row))
    tagged.sort(key=lambda item: (item[0], item[1]))
    return [row for _ts, _rank, row in tagged]


def _marker_text(row: dict[str, Any]) -> str:
    kind = str(row.get("type") or "")
    bits = [kind]
    for key in ("run_label", "item_id", "title", "status", "verdict",
                "reason", "error", "objective"):
        value = row.get(key)
        if value:
            bits.append(f"{key}={str(value)[:400]}")
    return "  ".join(bits)


def build_steps(
    *,
    work_dir: Path,
    session_id: str,
    run_result: AgentRunResult,
    builder: TrajectoryBuilder,
) -> None:
    """Populate ``builder`` from this episode's argus artifacts."""
    project_root = work_dir / "argus_home" / "projects" / session_id
    events_path = project_root / "events.jsonl"
    stream_path = project_root / "agent_io.jsonl"
    summary_path = work_dir / "argus_summary.json"

    summary: dict[str, Any] = {}
    if summary_path.is_file():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                summary = loaded
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("argus: could not read argus_summary.json: %s", exc)

    if not events_path.is_file() and not stream_path.is_file():
        rel = (
            events_path.relative_to(work_dir)
            if events_path.is_relative_to(work_dir)
            else events_path
        )
        builder.add_step(
            source="system",
            message=(
                f"argus: no event log at {rel}. "
                f"launcher status={run_result.status} exit_code={run_result.exit_code} "
                f"error={run_result.error or '-'}"
            ),
        )
        _attach_extra(builder, summary, run_result, events_seen=0, stream_seen=0)
        return

    rows = _merged_rows(events_path, stream_path)
    stream_seen = _consume(rows, builder)
    _attach_extra(
        builder, summary, run_result,
        events_seen=len(rows), stream_seen=stream_seen,
    )


def _consume(rows: list[dict[str, Any]], builder: TrajectoryBuilder) -> int:
    """Walk the log in order, appending steps. Returns the stream-row count."""
    from ale_run.agents.codex.deployer import CodexDeployer

    # Per-invocation NDJSON state: codex item ids are only unique within one
    # ``codex exec`` process, and argus runs many of them.
    started: dict[str, dict[str, dict]] = {}
    completed: dict[str, set[str]] = {}
    # Token accounting has two possible sources for the same call: the codex
    # ``turn.completed`` frames (attached to agent steps by the reused codex
    # mapping) and argus's own ``agent.io.complete`` summary. ``finalize`` sums
    # every step's metrics, so counting both would double the episode's tokens.
    # The frames win when present; the summary is the fallback for a call whose
    # raw stream was not persisted.
    stream_by_call: dict[str, int] = {}
    stream_seen = 0

    for row in rows:
        kind = str(row.get("type") or "")
        call_id = str(row.get("call_id") or "-")

        if kind == "agent.io.start":
            started.setdefault(call_id, {})
            completed.setdefault(call_id, set())
            builder.add_step(
                source="system",
                message=(
                    f"argus role start: {row.get('run_label') or '?'} "
                    f"(model={row.get('model') or '?'}, "
                    f"effort={row.get('reasoning_effort') or '?'})"
                ),
                extra={
                    "argus_event": kind,
                    "run_label": row.get("run_label"),
                    "call_id": call_id,
                    "working_dir": row.get("working_dir"),
                },
            )
            continue

        if kind == "agent.io.stream":
            stream_seen += 1
            stream_by_call[call_id] = stream_by_call.get(call_id, 0) + 1
            line = str(row.get("line") or "").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            _consume_codex_frame(
                event,
                started.setdefault(call_id, {}),
                completed.setdefault(call_id, set()),
                builder,
                CodexDeployer,
            )
            continue

        if kind == "agent.io.complete":
            counted_from_frames = stream_by_call.get(call_id, 0) > 0
            builder.add_step(
                source="system",
                message=(
                    f"argus role done: {row.get('run_label') or '?'} "
                    f"(exit={row.get('exit_code')}, "
                    f"turn_completed={row.get('turn_completed')})"
                ),
                metrics=None if counted_from_frames else StepMetrics(
                    input_tokens=_int(row.get("input_tokens")),
                    output_tokens=_int(row.get("output_tokens")),
                    cache_read_tokens=_int(row.get("cached_input_tokens")),
                    cache_creation_tokens=_int(row.get("cache_write_tokens")),
                ),
                extra={
                    "argus_event": kind,
                    "run_label": row.get("run_label"),
                    "call_id": call_id,
                    "fatal_error": row.get("fatal_error"),
                    "agent_message_count": row.get("agent_message_count"),
                    "input_tokens": row.get("input_tokens"),
                    "output_tokens": row.get("output_tokens"),
                    "tokens_counted_from": (
                        "codex_frames" if counted_from_frames else "argus_summary"
                    ),
                },
            )
            continue

        if kind in _MARKER_TYPES:
            builder.add_step(
                source="system",
                message=_marker_text(row),
                extra={"argus_event": kind},
            )

    # Items that started but never completed: the episode was killed mid-turn.
    for call_id, items in started.items():
        done = completed.get(call_id, set())
        for item_id, item in items.items():
            if item_id in done:
                continue
            builder.add_step(
                source="system",
                message=(
                    f"argus: {item.get('type') or 'item'} {item_id} never "
                    f"completed (call {call_id})"
                ),
                extra={"status": "incomplete", "call_id": call_id},
            )
    return stream_seen


def _consume_codex_frame(
    event: dict[str, Any],
    started: dict[str, dict],
    completed: set[str],
    builder: TrajectoryBuilder,
    codex_cls: Any,
) -> None:
    """Dispatch one ``codex exec --json`` frame through the codex mapping."""
    etype = str(event.get("type") or "")
    if etype == "item.started":
        item = event.get("item") or {}
        item_id = item.get("id")
        if item_id:
            started[str(item_id)] = item
        return
    if etype == "item.completed":
        codex_cls._consume_item_completed(event, started, completed, builder)
        return
    if etype == "turn.completed":
        codex_cls._consume_turn_completed(event, builder)
        return
    if etype == "error":
        builder.add_step(
            source="system",
            message=str(event.get("message") or event.get("error") or ""),
        )


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _attach_extra(
    builder: TrajectoryBuilder,
    summary: dict[str, Any],
    run_result: AgentRunResult,
    *,
    events_seen: int,
    stream_seen: int,
) -> None:
    payload: dict[str, Any] = {
        "exit_code": run_result.exit_code,
        "events_seen": events_seen,
        "stream_rows_seen": stream_seen,
        "launcher_ok": summary.get("ok"),
    }
    if summary.get("error"):
        payload["launcher_error"] = summary["error"]
    if isinstance(summary.get("summary"), dict):
        payload["supervisor_summary"] = summary["summary"]
    if events_seen and not stream_seen:
        payload["note"] = (
            "no agent.io.stream rows — role-level steps only "
            "(ARGUS_SKILL_AGENT_IO_MODE was not 'full')"
        )
    builder.trajectory.extra.setdefault("argus", {}).update(payload)
