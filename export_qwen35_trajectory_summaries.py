#!/usr/bin/env python3
"""Export compact trajectory summaries for the local Qwen ALE Docker run."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_RUN_ROOT = Path(".logs/ale/local_docker_qwen35_docker_support_full")
DEFAULT_OUT_DIR = Path("analysis/qwen35_docker_support_full")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        return {"_json_error": str(exc)}


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _text_preview(value: Any, max_chars: int) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _duration_s(started_at: str | None, ended_at: str | None) -> float | None:
    start = _parse_timestamp(started_at)
    end = _parse_timestamp(ended_at)
    if start is None or end is None:
        return None
    return round((end - start).total_seconds(), 3)


def _task_slug(run_dir: Path, run_root: Path, run_json: dict[str, Any]) -> str:
    task = run_json.get("task") or {}
    slug = task.get("slug")
    if isinstance(slug, str) and slug:
        return slug
    try:
        parts = run_dir.relative_to(run_root).parts
        if len(parts) >= 3:
            return parts[2]
    except ValueError:
        pass
    return run_dir.name


def _tool_command_preview(tool_calls: Any, max_chars: int) -> str:
    if not isinstance(tool_calls, list):
        return ""
    commands: list[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        args = call.get("arguments") or {}
        if isinstance(args, dict) and "keystrokes" in args:
            commands.append(str(args.get("keystrokes", "")).strip())
        elif "name" in call:
            commands.append(str(call.get("name")))
    return _text_preview(commands, max_chars)


def _observation_text(observation: Any) -> str:
    if not isinstance(observation, dict):
        return ""
    results = observation.get("results")
    if not isinstance(results, list):
        return _text_preview(observation, 2000)
    chunks: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        content = result.get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    return "\n".join(chunks)


def _count_warning_fragments(steps: list[dict[str, Any]]) -> dict[str, int]:
    combined = "\n".join(
        [
            str(step.get("message") or "")
            + "\n"
            + _observation_text(step.get("observation"))
            for step in steps
        ]
    ).lower()
    return {
        "json_warning_count": combined.count("extra text detected before json object"),
        "permission_denied_count": combined.count("permission denied"),
        "missing_file_count": combined.count("no such file or directory")
        + combined.count("missing output")
        + combined.count("missing required files"),
        "timeout_mentions": combined.count("timeout"),
        "traceback_count": combined.count("traceback"),
    }


def _collect_run_dirs(run_root: Path) -> list[Path]:
    return sorted(path.parent for path in run_root.rglob("trajectory.json") if "origin_log" not in path.parts)


def export_summaries(run_root: Path, out_dir: Path, max_text_chars: int) -> tuple[Path, Path, int]:
    run_rows: list[dict[str, Any]] = []
    step_rows: list[dict[str, Any]] = []

    for run_dir in _collect_run_dirs(run_root):
        trajectory = _read_json(run_dir / "trajectory.json")
        run_json = _read_json(run_dir / "run.json")
        eval_json = _read_json(run_dir / "eval_result.json")
        origin_trajectory = _read_json(run_dir / "origin_log" / "terminus_2" / "logs" / "agent" / "trajectory.json")

        steps = trajectory.get("steps") if isinstance(trajectory.get("steps"), list) else []
        origin_steps = origin_trajectory.get("steps") if isinstance(origin_trajectory.get("steps"), list) else []
        final_metrics = trajectory.get("final_metrics") if isinstance(trajectory.get("final_metrics"), dict) else {}
        task_slug = _task_slug(run_dir, run_root, run_json)
        rel_run_dir = str(run_dir.relative_to(run_root))
        warning_counts = _count_warning_fragments(steps)

        score = eval_json.get("score", run_json.get("score", final_metrics.get("reward")))
        status = run_json.get("status", final_metrics.get("status"))
        started_at = trajectory.get("started_at")
        ended_at = trajectory.get("ended_at")

        run_rows.append(
            {
                "task": task_slug,
                "run_dir": rel_run_dir,
                "status": status,
                "score": score,
                "eval_status": eval_json.get("eval_status"),
                "steps": len(steps),
                "origin_steps": len(origin_steps),
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_s": _duration_s(started_at, ended_at),
                "total_input_tokens": final_metrics.get("total_input_tokens"),
                "total_output_tokens": final_metrics.get("total_output_tokens"),
                "total_duration_ms": final_metrics.get("total_duration_ms"),
                **warning_counts,
            }
        )

        for index, step in enumerate(steps):
            metrics = step.get("metrics") if isinstance(step.get("metrics"), dict) else {}
            tool_calls = step.get("tool_calls")
            observation = step.get("observation")
            step_rows.append(
                {
                    "task": task_slug,
                    "run_dir": rel_run_dir,
                    "step_index": index,
                    "step_id": step.get("step_id"),
                    "timestamp": step.get("timestamp"),
                    "source": step.get("source"),
                    "message_preview": _text_preview(step.get("message"), max_text_chars),
                    "tool_call_count": len(tool_calls) if isinstance(tool_calls, list) else 0,
                    "tool_commands_preview": _tool_command_preview(tool_calls, max_text_chars),
                    "observation_preview": _text_preview(_observation_text(observation), max_text_chars),
                    "input_tokens": metrics.get("input_tokens"),
                    "output_tokens": metrics.get("output_tokens"),
                    "duration_ms": metrics.get("duration_ms"),
                }
            )

    run_summary_path = out_dir / "run_summary.jsonl"
    step_summary_path = out_dir / "step_summary.jsonl"
    _write_jsonl(run_summary_path, run_rows)
    _write_jsonl(step_summary_path, step_rows)
    return run_summary_path, step_summary_path, len(run_rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-text-chars", type=int, default=500)
    args = parser.parse_args()

    run_summary_path, step_summary_path, run_count = export_summaries(
        args.run_root, args.out_dir, args.max_text_chars
    )
    print(f"run_root: {args.run_root}")
    print(f"runs_exported: {run_count}")
    print(f"run_summary: {run_summary_path}")
    print(f"step_summary: {step_summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
