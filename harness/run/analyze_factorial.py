#!/usr/bin/env python3
"""Audit one factorial ALE experiment across one or more disjoint roots.

The script keeps the newest timestamped run for each (arm, task), writes tidy
score and behavior tables, and checks prep/combined cache identity. It is
stdlib-only so it can run on the benchmark host without extra dependencies.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DESIGNS = {
    "prep": (
        "ale_claw_base",
        "ale_claw_prep",
    ),
    "skills": (
        "ale_claw_base",
        "ale_claw_skills",
        "ale_claw_prep",
        "ale_claw_skills_prep",
    ),
    "verifier": (
        "ale_claw_base",
        "ale_claw_prep",
        "ale_claw_verifier",
        "ale_claw_prep_verifier",
    ),
}
ARMS = DESIGNS["skills"]
SHORT_ARM = {arm: arm.removeprefix("ale_claw_") for arm in set().union(*DESIGNS.values())}

def _factorial_axes() -> tuple[str, str, str] | None:
    """Return (first factor, second factor, combined arm) for a 2x2 design."""
    if ARMS == DESIGNS["skills"]:
        return "skills", "prep", "skills_prep"
    if ARMS == DESIGNS["verifier"]:
        return "verifier", "prep", "prep_verifier"
    return None


def _factorial_effects(values: dict[str, float | None]) -> dict[str, float] | None:
    axes = _factorial_axes()
    if axes is None:
        return None
    first_name, second_name, combined_name = axes
    base = values.get("base")
    first = values.get(first_name)
    second = values.get(second_name)
    combined = values.get(combined_name)
    if any(value is None for value in (base, first, second, combined)):
        return None
    assert base is not None and first is not None
    assert second is not None and combined is not None
    return {
        f"{first_name}_main_effect": ((first - base) + (combined - second)) / 2,
        f"{second_name}_main_effect": ((second - base) + (combined - first)) / 2,
        f"{first_name}_{second_name}_interaction": combined - first - second + base,
    }


@dataclass(frozen=True)
class Run:
    endpoint: str
    arm: str
    task: str
    run_dir: Path
    mtime: float
    data: dict[str, Any]


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    values: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def _prep_response(run: Run) -> tuple[dict[str, Any] | None, str | None]:
    registry_paths = list(
        (run.run_dir / "origin_log" / "ale-claw" / "openclaw_sessions").glob(
            "*/task-prep-runs.jsonl"
        )
    )
    if not registry_paths:
        return None, None
    terminal = [
        value
        for value in _read_jsonl(registry_paths[0])
        if value.get("status") in {"complete", "failed"}
    ]
    if not terminal:
        return None, "prep registry has no terminal record"
    text = str(terminal[-1].get("result_text") or "")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid prep JSON: {exc}"
    if not isinstance(value, dict):
        return None, "prep response is not an object"
    return value, None


def _retained_prep_claims(report: str) -> set[str]:
    legacy = re.findall(r"^## \d+\. (.+)$", report, flags=re.MULTILINE)
    current = re.findall(
        r"^### \d+\. (.+?)(?: \[[^\]]+\])?$", report, flags=re.MULTILINE
    )
    deliverables = re.findall(
        r"^### D\d+\. (.+?)(?: \[[^\]]+\])?$", report, flags=re.MULTILINE
    )
    return set(legacy + current + deliverables)



def _main_transcript_calls(run: Run) -> list[tuple[str, str]]:
    transcripts = list(
        (run.run_dir / "origin_log" / "ale-claw" / "openclaw_sessions").glob(
            "*/transcript.jsonl"
        )
    )
    if not transcripts:
        return []
    calls: list[tuple[str, str]] = []
    for value in _read_jsonl(transcripts[0]):
        message = value.get("message") or {}
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content") or []
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "function_call":
                continue
            calls.append((
                str(block.get("name") or ""),
                str(block.get("arguments") or ""),
            ))
    return calls


def _nested_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _nested_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nested_strings(child)


def _prep_report_inlined(run: Run, report: str) -> bool:
    """Whether prep content reached the writer's first prompt (the digest).

    Measured on the raw turn-0 API request, never on transcript.jsonl: the
    transcript can lose the initial prompt to compaction, and a grep there
    produced three false "prep never arrived" units in the 2026-07-22 run.
    The current protocol injects a digest under this heading and delivers the
    full report as a file, so the report text itself is not expected inline.
    """
    report = report.strip()
    if not report or report == "NO_TASK_SPECIFIC_PREP":
        return False
    request_paths = (
        run.run_dir / "origin_log" / "ale-claw" / "trajectories"
    ).glob("*/turn_000/0000_api_start.json")
    for path in request_paths:
        value = _read_json(path)
        if value is not None and any(
            "## Task-specific prior research" in text
            for text in _nested_strings(value)
        ):
            return True
    return False


def load_runs(roots: list[Path]) -> dict[tuple[str, str], Run]:
    best: dict[tuple[str, str], Run] = {}
    task_endpoint: dict[str, str] = {}
    for root in roots:
        if not root.is_dir():
            raise ValueError(f"result root not found: {root}")
        endpoint = root.name.removeprefix("task_prep_skills_v2_")
        for run_json in root.rglob("run.json"):
            data = _read_json(run_json)
            if data is None:
                continue
            arm = str((data.get("agent") or {}).get("id") or "")
            task = str((data.get("task") or {}).get("slug") or "")
            if arm not in ARMS or not task:
                continue
            previous_endpoint = task_endpoint.setdefault(task, endpoint)
            if previous_endpoint != endpoint:
                raise ValueError(
                    f"task appears in multiple endpoint shards: {task}: "
                    f"{previous_endpoint}, {endpoint}"
                )
            try:
                mtime = run_json.stat().st_mtime
            except OSError:
                mtime = 0.0
            run = Run(endpoint, arm, task, run_json.parent, mtime, data)
            key = (arm, task)
            if key not in best or mtime > best[key].mtime:
                best[key] = run
    return best


def exclude_tasks(
    runs: dict[tuple[str, str], Run], task_slugs: set[str]
) -> dict[tuple[str, str], Run]:
    """Return runs whose task slug was not explicitly excluded."""
    return {
        key: run
        for key, run in runs.items()
        if run.task not in task_slugs
    }


def _trajectory_metrics(run: Run) -> dict[str, Any]:
    trajectory = _read_json(run.run_dir / "trajectory.json") or {}
    llm_turns = 0
    tool_calls = 0
    loads: list[tuple[str, int | None]] = []
    for step in trajectory.get("steps") or []:
        if not isinstance(step, dict) or step.get("source") != "agent":
            continue
        calls = step.get("tool_calls") or []
        if step.get("metrics") is not None or calls or step.get("message"):
            llm_turns += 1
        tool_calls += len(calls)
        for call in calls:
            if not isinstance(call, dict) or call.get("name") != "memory_get":
                continue
            path = str((call.get("arguments") or {}).get("path") or "")
            if "method-" not in path:
                continue
            skill = path.rsplit("method-", 1)[-1].removesuffix(".md")
            loads.append((skill, step.get("step_id")))
    return {
        "llm_turns": llm_turns,
        "tool_calls": tool_calls,
        "loaded_skills": ";".join(name for name, _ in loads),
        "skill_load_steps": ";".join(str(step) for _, step in loads),
    }


def _prep_metrics(run: Run) -> dict[str, Any]:
    meta_path = run.run_dir / "origin_log" / "ale-claw" / "task_prep_meta.json"
    report_path = run.run_dir / "origin_log" / "ale-claw" / "task_prep.md"
    meta = _read_json(meta_path) or {}
    try:
        report = report_path.read_bytes()
    except OSError:
        report = b""
    return {
        "prep_protocol_digest": meta.get("protocol_digest"),
        "prep_status": meta.get("status"),
        "prep_environment_status": meta.get("environment_status"),
        "prep_attempt_outcome": (meta.get("attempt") or {}).get("outcome"),
        "prep_finding_count": meta.get("finding_count"),
        "prep_dropped": ";".join(meta.get("dropped") or []) or None,
        "prep_report_chars": meta.get("report_chars"),
        "prep_duration_s": meta.get("duration_s"),
        "prep_input_tokens": meta.get("input_tokens"),
        "prep_output_tokens": meta.get("output_tokens"),
        "prep_llm_turns": meta.get("llm_turns"),
        "prep_tool_calls": meta.get("tool_calls"),
        "prep_report_bytes": len(report) if report else None,
        "prep_report_sha256": hashlib.sha256(report).hexdigest() if report else None,
        "prep_final_report_chars": meta.get("final_report_chars"),
        "prep_report_capture_error": meta.get("report_capture_error"),
    }




def _verifier_metrics(run: Run) -> dict[str, Any]:
    root = run.run_dir / "origin_log" / "ale-claw"
    meta = _read_json(root / "verifier_meta.json") or {}
    suite_path = root / "verifier_suite.json"
    try:
        suite_bytes = suite_path.read_bytes()
    except OSError:
        suite_bytes = b""
    rounds = []
    for path in sorted(root.glob("verifier_round_*.json")):
        value = _read_json(path)
        if value is not None:
            rounds.append(value)
    writer_checks = []
    for path in sorted(root.glob("verifier_writer_check_*.json")):
        value = _read_json(path)
        if value is not None:
            writer_checks.append(value)
    statuses: Counter[str] = Counter()
    source_statuses: Counter[str] = Counter()
    blocking: Counter[str] = Counter()
    executor_duration = 0.0
    for result in rounds:
        executor_duration += float(_number(result.get("duration_s")) or 0)
        for check in result.get("checks") or []:
            if isinstance(check, dict):
                statuses[str(check.get("status") or "missing")] += 1
                validation = check.get("validation") or {}
                source_statuses[str(validation.get("source_status") or "unregistered")] += 1
                blocking["blocking" if check.get("blocking") else "nonblocking"] += 1
    agent_usage = meta.get("agent_usage") or {}
    return {
        "verifier_protocol": meta.get("protocol"),
        "verifier_status": meta.get("status"),
        "verifier_builder_error": meta.get("builder_error"),
        "verifier_suite_sha256": hashlib.sha256(suite_bytes).hexdigest() if suite_bytes else None,
        "verifier_rounds": meta.get("rounds"),
        "verifier_repairs": meta.get("repairs"),
        "verifier_stop_reason": meta.get("stop_reason"),
        "verifier_last_overall": rounds[-1].get("overall") if rounds else None,
        "verifier_error": rounds[-1].get("error") if rounds else None,
        "verifier_check_statuses": json.dumps(dict(sorted(statuses.items()))),
        "verifier_source_statuses": json.dumps(
            dict(sorted(source_statuses.items()))
        ),
        "verifier_blocking_checks": json.dumps(dict(sorted(blocking.items()))),
        "verifier_agent_input_tokens": agent_usage.get("input_tokens"),
        "verifier_agent_output_tokens": agent_usage.get("output_tokens"),
        "verifier_agent_duration_s": agent_usage.get("duration_s"),
        "verifier_executor_duration_s": executor_duration if rounds else None,
        "verifier_writer_checks_max": meta.get("writer_checks_max"),
        "verifier_writer_checks_used": meta.get(
            "writer_checks_used", len(writer_checks) or None
        ),
        "verifier_writer_check_overalls": json.dumps(
            [record.get("overall") for record in writer_checks]
        ) if writer_checks else None,
        "verifier_writer_check_review_items": sum(
            len((record.get("categories") or {}).get("review_items") or [])
            for record in writer_checks
        ) if writer_checks else None,
        **_output_drift(writer_checks + rounds),
    }


def _output_drift(records: list[dict[str, Any]]) -> dict[str, Any]:
    """How the output changed across consecutive snapshots of one run.

    Deleting content is the cheapest way to pass a mechanical check and the
    likeliest way to lose hidden-rubric credit, so the direction of change
    after a signal arrives is the reading that matters. Snapshots are ordered
    as recorded: writer-triggered checks first, then post-DONE rounds.
    """
    steps: list[dict[str, Any]] = []
    previous: dict[str, dict[str, Any]] | None = None
    for record in records:
        manifest = record.get("snapshot_manifest")
        if not isinstance(manifest, list) or not manifest:
            continue
        current = {
            str(item.get("path")): item
            for item in manifest
            if isinstance(item, dict) and item.get("path")
        }
        if previous is not None and current != previous:
            steps.append({
                "bytes": sum(item.get("bytes") or 0 for item in current.values())
                - sum(item.get("bytes") or 0 for item in previous.values()),
                "files": len(current) - len(previous),
                "dropped": sorted(set(previous) - set(current)),
            })
        previous = current
    if not steps:
        return {
            "output_drift_steps": None,
            "output_drift_bytes": None,
            "output_drift_files": None,
            "output_dropped_files": None,
            "output_shrank": None,
        }
    return {
        "output_drift_steps": len(steps),
        "output_drift_bytes": sum(step["bytes"] for step in steps),
        "output_drift_files": sum(step["files"] for step in steps),
        "output_dropped_files": json.dumps(
            sorted({path for step in steps for path in step["dropped"]})
        ),
        "output_shrank": any(
            step["bytes"] < 0 or step["files"] < 0 for step in steps
        ),
    }


def behavior_row(run: Run) -> dict[str, Any]:
    usage = run.data.get("usage") or {}
    timings = run.data.get("timings") or {}
    row = {
        "endpoint": run.endpoint,
        "task": run.task,
        "arm": SHORT_ARM[run.arm],
        "status": run.data.get("status"),
        "score": run.data.get("score"),
        "score_valid": run.data.get("score_valid"),
        "duration_s": timings.get("duration_s"),
        "steps": usage.get("total_steps"),
        "input_tokens": usage.get("total_input_tokens"),
        "output_tokens": usage.get("total_output_tokens"),
        "cost_usd": usage.get("total_cost_usd"),
        "run_dir": str(run.run_dir),
    }
    row.update(_trajectory_metrics(run))
    row.update(_prep_metrics(run))
    row.update(_verifier_metrics(run))
    return row


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def score_rows(runs: dict[tuple[str, str], Run]) -> list[dict[str, Any]]:
    tasks = sorted({task for _, task in runs})
    rows: list[dict[str, Any]] = []
    for task in tasks:
        present = [runs[(arm, task)] for arm in ARMS if (arm, task) in runs]
        endpoint = present[0].endpoint if present else ""
        row: dict[str, Any] = {"endpoint": endpoint, "task": task}
        for arm in ARMS:
            short = SHORT_ARM[arm]
            run = runs.get((arm, task))
            row[f"{short}_status"] = run.data.get("status") if run else None
            row[short] = run.data.get("score") if run else None
        base = _number(row["base"])
        for short in (SHORT_ARM[arm] for arm in ARMS[1:]):
            value = _number(row[short])
            row[f"{short}_delta"] = value - base if value is not None and base is not None else None
        axes = _factorial_axes()
        if axes is not None:
            effect_names = (
                f"{axes[0]}_main_effect",
                f"{axes[1]}_main_effect",
                f"{axes[0]}_{axes[1]}_interaction",
            )
            effects = _factorial_effects({
                short: _number(row.get(short))
                for short in ("base", *axes)
            })
            for name in effect_names:
                row[name] = effects[name] if effects is not None else None
        rows.append(row)
    return rows


def prep_audit_rows(runs: dict[tuple[str, str], Run]) -> list[dict[str, Any]]:
    if len(ARMS) < 3 or ARMS[-1] == "ale_claw_prep":
        return []
    tasks = sorted({task for _, task in runs})
    rows: list[dict[str, Any]] = []
    for task in tasks:
        prep = runs.get(("ale_claw_prep", task))
        combined = runs.get((ARMS[-1], task))
        if not prep or not combined:
            continue
        pm = _prep_metrics(prep)
        cm = _prep_metrics(combined)
        fingerprint_equal = (
            pm["prep_fingerprint"] is not None
            and pm["prep_fingerprint"] == cm["prep_fingerprint"]
        )
        report_sha_equal = (
            pm["prep_report_sha256"] is not None
            and pm["prep_report_sha256"] == cm["prep_report_sha256"]
        )
        report_bytes_equal = (
            pm["prep_report_bytes"] is not None
            and pm["prep_report_bytes"] == cm["prep_report_bytes"]
        )
        rows.append(
            {
                "endpoint": prep.endpoint,
                "task": task,
                "prep_status": pm["prep_status"],
                "combined_status": cm["prep_status"],
                "prep_cached": pm["prep_cached"],
                "combined_cached": cm["prep_cached"],
                "cache_pattern_valid": pm["prep_cached"] is False
                and cm["prep_cached"] is True,
                "fingerprint_equal": fingerprint_equal,
                "report_sha256_equal": report_sha_equal,
                "report_bytes_equal": report_bytes_equal,
                "prep_fingerprint": pm["prep_fingerprint"],
                "report_sha256": pm["prep_report_sha256"],
                "report_bytes": pm["prep_report_bytes"],
            }
        )
    return rows


def prep_finding_rows(runs: dict[tuple[str, str], Run]) -> list[dict[str, Any]]:
    """Show each raw prep finding and why the protocol kept or dropped it.

    One shape only. The version-gated branches this replaced silently stopped
    working when protocol version numbers were dropped: every gate evaluated
    false, so current findings were parsed by a pre-v11 branch and came out
    empty. An analyzer that fails this way reports "the component produced
    nothing" instead of "the analyzer is out of date".
    """
    rows: list[dict[str, Any]] = []
    for run in sorted(runs.values(), key=lambda item: item.task):
        if run.arm != "ale_claw_prep":
            continue
        response, error = _prep_response(run)
        report_path = run.run_dir / "origin_log" / "ale-claw" / "task_prep.md"
        try:
            report = report_path.read_text(encoding="utf-8")
        except OSError:
            report = ""
        retained = _retained_prep_claims(report)
        raw_items = (response or {}).get("findings") or []
        if not isinstance(raw_items, list):
            raw_items = []
            error = error or "prep findings is not an array"
        for index, raw_item in enumerate(raw_items, 1):
            if not isinstance(raw_item, dict):
                continue
            raw_sources = raw_item.get("sources")
            item = {
                "title": str(raw_item.get("title") or "").strip(),
                "claim": str(raw_item.get("observation") or "").strip(),
                "writer_action": str(raw_item.get("writer_action") or "").strip(),
                "local_source": ";".join(
                    str(source).strip() for source in raw_sources
                ) if isinstance(raw_sources, list) else "",
                "do_not_infer": str(raw_item.get("do_not_infer") or "").strip(),
            }
            item["solver_impact"] = item["writer_action"]
            is_retained = item["title"] in retained
            reasons: list[str] = []
            if not is_retained:
                if not all(
                    item[key] for key in ("claim", "writer_action", "local_source")
                ):
                    reasons.append("missing_field")
                for source in item["local_source"].split(";"):
                    path = source.split("#", 1)[0]
                    if not (
                        source.startswith(("runtime:", "https://", "http://"))
                        or path.startswith(("input/", "software/"))
                    ):
                        reasons.append("invalid_source")
                        break
                if not reasons:
                    reasons.append("report_rejected" if not retained else "unknown")
            rows.append({
                "endpoint": run.endpoint,
                "task": run.task,
                "index": index,
                "retained": is_retained,
                "filter_reason": ";".join(reasons),
                **item,
                "parse_error": error,
            })
    return rows


def prep_writer_rows(runs: dict[tuple[str, str], Run]) -> list[dict[str, Any]]:
    """Trace the prep report from the research response into writer actions."""
    rows: list[dict[str, Any]] = []
    for run in sorted(runs.values(), key=lambda item: (item.task, item.arm)):
        if run.arm not in {"ale_claw_prep", ARMS[-1]}:
            continue
        response, error = _prep_response(run)
        report_path = run.run_dir / "origin_log" / "ale-claw" / "task_prep.md"
        try:
            report = report_path.read_text(encoding="utf-8")
        except OSError:
            report = ""
        calls = _main_transcript_calls(run)
        read_calls = [
            index
            for index, (_, arguments) in enumerate(calls, 1)
            if "PREP_REPORT.md" in arguments
        ]
        read_call = read_calls[0] if read_calls else None
        report_inlined = _prep_report_inlined(run, report)
        later_arguments = "\n".join(
            arguments
            for index, (_, arguments) in enumerate(calls, 1)
            if read_call is None or index > read_call
        )
        sources = re.findall(
            r"^(?:- Local source|- Task basis|  - Source(?: \[[^\]]+\])?): `([^`]+)`",
            report,
            flags=re.MULTILINE,
        )
        revisited = 0
        for source in sources:
            path = source.split("#", 1)[0]
            marker = (
                path.split(":", 1)[1].split()[0]
                if path.startswith("runtime:")
                else path
            )
            revisited += bool(marker and marker in later_arguments)
        raw_items = (response or {}).get("findings") or []
        raw_count = len(raw_items) if isinstance(raw_items, list) else None
        prep_meta = _read_json(
            run.run_dir / "origin_log" / "ale-claw" / "task_prep_meta.json"
        ) or {}
        # Consumption, not delivery: a prep artifact earns its place when the
        # writer actually calls or reads it, so tool calls that reference the
        # staged artifact directory are the success metric for job 3.
        artifact_calls = sum(
            1 for _, arguments in calls if "task_prep/artifacts/" in arguments
        )
        rows.append({
            "endpoint": run.endpoint,
            "task": run.task,
            "arm": SHORT_ARM[run.arm],
            "prep_status": _prep_metrics(run).get("prep_status"),
                "raw_findings": raw_count,
            "retained_findings": len(_retained_prep_claims(report)),
            "writer_tool_calls": len(calls),
            "report_read_call": read_call,
            "report_inlined": report_inlined,
            "report_exposed": bool(report.strip() and (read_call or report_inlined)),
            "report_sources": len(sources),
            "sources_revisited": revisited,
            "artifact_count": prep_meta.get("artifact_count"),
            "artifact_chars": prep_meta.get("artifact_chars"),
            "artifact_calls": artifact_calls,
            "parse_error": error,
        })
    return rows


def verifier_audit_rows(runs: dict[tuple[str, str], Run]) -> list[dict[str, Any]]:
    if "ale_claw_verifier" not in ARMS:
        return []
    rows: list[dict[str, Any]] = []
    tasks = sorted({task for _, task in runs})
    for task in tasks:
        verifier = runs.get(("ale_claw_verifier", task))
        combined = runs.get(("ale_claw_prep_verifier", task))
        if not verifier or not combined:
            continue
        vm = _verifier_metrics(verifier)
        cm = _verifier_metrics(combined)
        rows.append({
            "endpoint": verifier.endpoint,
            "task": task,
            "verifier_status": vm["verifier_status"],
            "combined_status": cm["verifier_status"],
            "suite_sha256_equal": vm["verifier_suite_sha256"] == cm["verifier_suite_sha256"],
            "suite_sha256": vm["verifier_suite_sha256"],
        })
    return rows


def verifier_check_rows(runs: dict[tuple[str, str], Run]) -> list[dict[str, Any]]:
    """Flatten every frozen-test result and its source/checker gate."""
    rows: list[dict[str, Any]] = []
    for run in sorted(runs.values(), key=lambda item: (item.task, item.arm)):
        if run.arm not in {"ale_claw_verifier", "ale_claw_prep_verifier"}:
            continue
        root = run.run_dir / "origin_log" / "ale-claw"
        for round_path in sorted(root.glob("verifier_round_*.json")):
            result = _read_json(round_path)
            if result is None:
                continue
            fallback_iteration = round_path.stem.rsplit("_", 1)[-1]
            iteration = result.get("iteration", fallback_iteration)
            for check in result.get("checks") or []:
                if not isinstance(check, dict):
                    continue
                sources = check.get("sources") or []
                validation = check.get("validation") or {}
                rows.append({
                    "endpoint": run.endpoint,
                    "task": run.task,
                    "arm": SHORT_ARM[run.arm],
                    "iteration": iteration,
                    "overall": result.get("overall"),
                    "snapshot_sha256": result.get("snapshot_sha256"),
                    "check": check.get("check"),
                    "requested_blocking": check.get("requested_blocking"),
                    "blocking": check.get("blocking"),
                    "status": check.get("status"),
                    "requirement": check.get("requirement"),
                    "source_count": len(sources),
                    "sources": json.dumps(sources, ensure_ascii=True, sort_keys=True),
                    "source_status": validation.get("source_status"),
                    "source_evidence": validation.get("source_evidence"),
                    "source_entails_expected": validation.get("source_entails_expected"),
                    "checker_matches_requirement": validation.get("checker_matches_requirement"),
                    "checker_reproducible": validation.get("checker_reproducible"),
                    "environment_healthy": validation.get("environment_healthy"),
                    "interpretation": check.get("interpretation"),
                    "execution_mode": check.get("execution_mode"),
                    "execution_reason": check.get("execution_reason"),
                    "command": json.dumps(check.get("command") or []),
                    "evidence": check.get("evidence"),
                    "observed": check.get("observed"),
                    "expected": check.get("expected"),
                    "analysis": json.dumps(check.get("analysis"), sort_keys=True),
                })
    return rows


def verifier_repair_rows(runs: dict[tuple[str, str], Run]) -> list[dict[str, Any]]:
    """Summarize every artifact and verdict transition across repair rounds."""
    rows: list[dict[str, Any]] = []
    for run in sorted(runs.values(), key=lambda item: (item.task, item.arm)):
        if run.arm not in {"ale_claw_verifier", "ale_claw_prep_verifier"}:
            continue
        root = run.run_dir / "origin_log" / "ale-claw"
        rounds = [
            value
            for path in sorted(root.glob("verifier_round_*.json"))
            if (value := _read_json(path)) is not None
        ]
        for before, after in zip(rounds, rounds[1:]):
            before_items = {
                str(item.get("check")): item
                for item in before.get("checks") or []
                if isinstance(item, dict) and item.get("check")
            }
            after_items = {
                str(item.get("check")): item
                for item in after.get("checks") or []
                if isinstance(item, dict) and item.get("check")
            }
            before_failures = {
                name for name, item in before_items.items()
                if item.get("status") == "fail"
            }
            after_failures = {
                name for name, item in after_items.items()
                if item.get("status") == "fail"
            }
            authority_changes = []
            for name in sorted(before_items.keys() & after_items.keys()):
                old = str(before_items[name].get("blocking"))
                new = str(after_items[name].get("blocking"))
                if old != new:
                    authority_changes.append(f"{name}:{old}->{new}")
            before_hash = str(before.get("snapshot_sha256") or "")
            after_hash = str(after.get("snapshot_sha256") or "")
            before_suite = str(before.get("suite_sha256") or "")
            after_suite = str(after.get("suite_sha256") or "")
            rows.append({
                "endpoint": run.endpoint,
                "task": run.task,
                "arm": SHORT_ARM[run.arm],
                "from_iteration": before.get("iteration"),
                "to_iteration": after.get("iteration"),
                "from_overall": before.get("overall"),
                "to_overall": after.get("overall"),
                "from_snapshot_sha256": before_hash,
                "to_snapshot_sha256": after_hash,
                "snapshot_changed": before_hash != after_hash,
                "from_suite_sha256": before_suite,
                "to_suite_sha256": after_suite,
                "suite_sha256_equal": bool(
                    before_suite and before_suite == after_suite
                ),
                "failures_before": ";".join(sorted(before_failures)),
                "failures_after": ";".join(sorted(after_failures)),
                "resolved_failures": ";".join(sorted(before_failures - after_failures)),
                "new_failures": ";".join(sorted(after_failures - before_failures)),
                "blocking_authority_changes": ";".join(authority_changes),
            })
    return rows


def summarize(
    runs: dict[tuple[str, str], Run], behavior: list[dict[str, Any]]
) -> dict[str, Any]:
    tasks = sorted({task for _, task in runs})
    summary: dict[str, Any] = {"tasks": len(tasks), "expected_units": len(tasks) * len(ARMS)}
    by_arm: dict[str, Any] = {}
    for arm in ARMS:
        short = SHORT_ARM[arm]
        arm_runs = [runs[(arm, task)] for task in tasks if (arm, task) in runs]
        completed = [r for r in arm_runs if r.data.get("status") == "completed"]
        scored = [r for r in completed if _number(r.data.get("score")) is not None]
        b_rows = [row for row in behavior if row["arm"] == short and row["status"] == "completed"]

        def mean_field(field: str) -> float | None:
            values = [_number(row.get(field)) for row in b_rows]
            clean = [value for value in values if value is not None]
            return statistics.mean(clean) if clean else None

        by_arm[short] = {
            "runs": len(arm_runs),
            "completed": len(completed),
            "failed": sum(r.data.get("status") == "failed" for r in arm_runs),
            "score_n": len(scored),
            "score_mean": statistics.mean(float(r.data["score"]) for r in scored) if scored else None,
            "score_total": sum(float(r.data["score"]) for r in scored),
            "duration_s_mean": mean_field("duration_s"),
            "steps_mean": mean_field("steps"),
            "input_tokens_mean": mean_field("input_tokens"),
            "output_tokens_mean": mean_field("output_tokens"),
            "cost_usd_mean": mean_field("cost_usd"),
            "llm_turns_mean": mean_field("llm_turns"),
            "tool_calls_mean": mean_field("tool_calls"),
        }
    summary["arms"] = by_arm

    paired: dict[str, Any] = {}
    for arm in ARMS[1:]:
        deltas: list[float] = []
        for task in tasks:
            base = runs.get(("ale_claw_base", task))
            other = runs.get((arm, task))
            if not base or not other:
                continue
            if base.data.get("status") != "completed" or other.data.get("status") != "completed":
                continue
            base_score = _number(base.data.get("score"))
            other_score = _number(other.data.get("score"))
            if base_score is not None and other_score is not None:
                deltas.append(other_score - base_score)
        mean = statistics.mean(deltas) if deltas else None
        sd = statistics.stdev(deltas) if len(deltas) > 1 else None
        se = sd / math.sqrt(len(deltas)) if sd is not None else None
        paired[SHORT_ARM[arm]] = {
            "n": len(deltas),
            "mean_delta": mean,
            "sd": sd,
            "se": se,
            "t": mean / se if mean is not None and se else None,
            "positive": sum(delta > 1e-12 for delta in deltas),
            "zero": sum(abs(delta) <= 1e-12 for delta in deltas),
            "negative": sum(delta < -1e-12 for delta in deltas),
        }
    summary["paired_vs_base"] = paired

    axes = _factorial_axes()
    if axes is not None:
        effect_names = (
            f"{axes[0]}_main_effect",
            f"{axes[1]}_main_effect",
            f"{axes[0]}_{axes[1]}_interaction",
        )
        factorial_values: dict[str, list[float]] = {name: [] for name in effect_names}
        for task in tasks:
            values = {
                SHORT_ARM[arm]: _number(runs[(arm, task)].data.get("score"))
                for arm in ARMS
                if (arm, task) in runs
                and runs[(arm, task)].data.get("status") == "completed"
            }
            effects = _factorial_effects(values)
            if effects is None:
                continue
            for name, value in effects.items():
                factorial_values[name].append(value)

        def effect_stats(values: list[float]) -> dict[str, Any]:
            mean = statistics.mean(values) if values else None
            sd = statistics.stdev(values) if len(values) > 1 else None
            se = sd / math.sqrt(len(values)) if sd is not None else None
            return {
                "n": len(values),
                "mean": mean,
                "sd": sd,
                "se": se,
                "t": mean / se if mean is not None and se else None,
                "positive": sum(value > 1e-12 for value in values),
                "zero": sum(abs(value) <= 1e-12 for value in values),
                "negative": sum(value < -1e-12 for value in values),
            }

        summary["factorial_effects"] = {
            name: effect_stats(values) for name, values in factorial_values.items()
        }

    if ARMS == DESIGNS["skills"]:
        skill_load_calls: Counter[str] = Counter()
        skill_units: Counter[str] = Counter()
        skill_enabled_completed_units = 0
        skill_units_with_any_load = 0
        for row in behavior:
            if (
                row["status"] != "completed"
                or row["arm"] not in {"skills", "skills_prep"}
            ):
                continue
            skill_enabled_completed_units += 1
            loaded = [
                skill for skill in str(row.get("loaded_skills") or "").split(";")
                if skill
            ]
            if loaded:
                skill_units_with_any_load += 1
            for skill in loaded:
                skill_load_calls[skill] += 1
            for skill in set(loaded):
                if skill:
                    skill_units[skill] += 1
        summary["skills"] = {
            "enabled_completed_units": skill_enabled_completed_units,
            "units_with_any_load": skill_units_with_any_load,
            "units_by_skill": dict(sorted(skill_units.items())),
            "load_calls_by_skill": dict(sorted(skill_load_calls.items())),
        }
    prep_rows = [row for row in behavior if row.get("prep_status")]
    if prep_rows:
        prep_durations = [
            value for row in prep_rows
            if (value := _number(row.get("prep_duration_s"))) is not None
        ]
        prep_inputs = [
            value for row in prep_rows
            if (value := _number(row.get("prep_input_tokens"))) is not None
        ]
        summary["prep"] = {
            "runs": len(prep_rows),
            "statuses": dict(sorted(
                Counter(str(row["prep_status"]) for row in prep_rows).items()
            )),
            "duration_s_mean": statistics.mean(prep_durations) if prep_durations else None,
            "input_tokens_mean": statistics.mean(prep_inputs) if prep_inputs else None,
        }
    verifier_rows = [row for row in behavior if row.get("verifier_status")]
    if verifier_rows:
        stop_reasons = Counter(str(row.get("verifier_stop_reason")) for row in verifier_rows)
        overall = Counter(str(row.get("verifier_last_overall")) for row in verifier_rows)
        repairs = [
            float(value) for row in verifier_rows
            if (value := _number(row.get("verifier_repairs"))) is not None
        ]
        verifier_usage = {}
        for field in (
            "verifier_agent_input_tokens",
            "verifier_agent_output_tokens",
            "verifier_agent_duration_s",
            "verifier_executor_duration_s",
        ):
            values = [
                value for row in verifier_rows
                if (value := _number(row.get(field))) is not None
            ]
            verifier_usage[f"{field.removeprefix('verifier_')}_mean"] = (
                statistics.mean(values) if values else None
            )
        summary["verifier"] = {
            "runs": len(verifier_rows),
            "stop_reasons": dict(sorted(stop_reasons.items())),
            "last_overall": dict(sorted(overall.items())),
            "repairs_mean": statistics.mean(repairs) if repairs else None,
            **verifier_usage,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--design", choices=sorted(DESIGNS), default="skills")
    parser.add_argument(
        "--exclude-task",
        action="append",
        default=[],
        metavar="TASK_SLUG",
        help="exclude an exact task slug; may be repeated",
    )
    args = parser.parse_args()

    global ARMS
    ARMS = DESIGNS[args.design]

    try:
        runs = load_runs(args.roots)
    except ValueError as exc:
        parser.error(str(exc))
    runs = exclude_tasks(runs, set(args.exclude_task))
    behavior = [behavior_row(run) for run in sorted(runs.values(), key=lambda r: (r.task, r.arm))]
    scores = score_rows(runs)
    prep_audit = prep_audit_rows(runs)
    prep_findings = prep_finding_rows(runs)
    prep_writer = prep_writer_rows(runs)
    verifier_audit = verifier_audit_rows(runs)
    verifier_checks = verifier_check_rows(runs)
    verifier_repairs = verifier_repair_rows(runs)
    summary = summarize(runs, behavior)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.out_dir / "scores.csv", scores)
    _write_csv(args.out_dir / "behavior.csv", behavior)
    _write_csv(args.out_dir / "prep_audit.csv", prep_audit)
    _write_csv(args.out_dir / "prep_findings.csv", prep_findings)
    _write_csv(args.out_dir / "prep_writer.csv", prep_writer)
    _write_csv(args.out_dir / "verifier_audit.csv", verifier_audit)
    _write_csv(args.out_dir / "verifier_checks.csv", verifier_checks)
    _write_csv(args.out_dir / "verifier_repairs.csv", verifier_repairs)
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))

    actual = len(runs)
    expected = int(summary["expected_units"])
    noncompleted = [
        f"{SHORT_ARM[run.arm]}:{run.task}:{run.data.get('status')}"
        for run in runs.values()
        if run.data.get("status") != "completed"
    ]
    if not args.allow_incomplete:
        if actual != expected:
            print(f"incomplete: newest units={actual}, expected={expected}")
            return 1
        if noncompleted:
            print(f"non-completed newest units ({len(noncompleted)}):")
            print("\n".join(sorted(noncompleted)))
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
