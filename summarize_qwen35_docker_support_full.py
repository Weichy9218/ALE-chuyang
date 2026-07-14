#!/usr/bin/env python3
"""Summarize the local Qwen full Docker-supported ALE run."""

from __future__ import annotations

import json
from pathlib import Path


RUN_ROOT = Path(".logs/ale/local_docker_qwen35_docker_support_full")


def main() -> int:
    rows: list[tuple[str, str, float | None, Path]] = []
    for run_json in sorted(RUN_ROOT.rglob("run.json")):
        run = json.loads(run_json.read_text(encoding="utf-8"))
        eval_json = run_json.with_name("eval_result.json")
        score = None
        if eval_json.exists():
            eval_result = json.loads(eval_json.read_text(encoding="utf-8"))
            raw_score = eval_result.get("score", run.get("score"))
            score = float(raw_score) if raw_score is not None else None
        task = run.get("task", {}).get("slug", str(run_json.parent))
        status = str(run.get("status", "unknown"))
        rows.append((task, status, score, run_json.parent))

    completed = [row for row in rows if row[2] is not None]
    total_score = sum(row[2] for row in completed if row[2] is not None)
    mean_score = total_score / len(completed) if completed else 0.0

    print(f"run_root: {RUN_ROOT}")
    print(f"tasks_with_run_json: {len(rows)}")
    print(f"scored_tasks: {len(completed)}")
    print(f"score_sum: {total_score:.6f}")
    print(f"score_mean_scored: {mean_score:.6f}")
    print()
    print("score\tstatus\ttask")
    for task, status, score, _path in rows:
        score_text = "" if score is None else f"{score:.6f}"
        print(f"{score_text}\t{status}\t{task}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
