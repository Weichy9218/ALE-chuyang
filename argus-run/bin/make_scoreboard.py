#!/usr/bin/env python3
"""Build the argus 105-task scoreboard CSV from run roots on pgl.

Run ON pgl:  python3 make_scoreboard.py argus_scores.csv \
                logs/run26/argus_26 logs/retry/argus_retry logs/rest/argus_rest ...

For each task, keeps the BEST-scoring run and records:
  task, score, run_status, note, in_tok, out_tok, dur_s, trajectory

`note` interprets the outcome so a zero is never silently a capability failure:
  ok               ran clean, score is the model's real result
  gateway_last     scored, but the kept run's LAST round hit a Boyue stream
                   disconnect (score still trustworthy; the disconnect was after
                   the work landed)
  gateway_zero     0 purely because the Boyue stream dropped before any output —
                   retryable, NOT a capability result
  data_missing     task-data/<t>/base/input absent on the box — needs staging
  ran_zero         ran to completion and genuinely scored 0

The canonical 105 list is selected_tasks/ale_cli.txt; 9 of those have no hidden
reference even on the evaluator copy and can never be scored (they appear here
only if a run exists). This file is the single source of truth for results —
regenerate it after every new run or retry.
"""
import csv
import json
import pathlib
import sys


def review_reason(unit_dir: pathlib.Path) -> str:
    ev = unit_dir / "origin_log" / "argus" / "argus_home" / "projects" / "ale" / "events.jsonl"
    if not ev.is_file():
        return ""
    last = ""
    for line in ev.open():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("type") == "round.review.completed":
            last = (r.get("reason") or "").lower()
    return last


def note_for(unit_dir: pathlib.Path, score: float, status: str, in_tok: int,
             dur: float) -> str:
    if status == "failed":
        # A genuine data-staging failure dies in seconds having done no work
        # (dur ~10s, no tokens). A run that actually spun the agent up — ran for
        # minutes, spent tokens — and still exited failed is a real 0: the agent
        # could not produce a deliverable (e.g. amber_three_stage fails 3/3 at
        # 400-660s, eval skipped_agent_failed, empty output/). Score it like any
        # other completed 0; its trajectory is kept and referenced as-is, no
        # special-casing.
        if dur < 30 and in_tok < 5000:
            return "data_missing"
        return "ran_zero"
    reason = review_reason(unit_dir)
    streamed = "stream discon" in reason or "response.failed" in reason
    if score >= 1e-9:
        return "gateway_last" if streamed else "ok"
    # A zero is only a retryable gateway_zero if the stream drop stopped the work
    # before it happened. A real run burns millions of input tokens; a gateway
    # fake-0 uses <~60k (RUN26 diagnostic). So a zero with real token spend is a
    # genuine ran_zero even when the final review round also hit a disconnect —
    # openroad's 2.9 h PnR flow (1.44M tok) and bpmn_category's 628-check audit
    # (9.5M tok) really ran and really scored 0; only a low-token streamed zero
    # is nothing-ran-yet and worth retrying.
    ran_real = in_tok >= 200_000
    if streamed and not ran_real:
        return "gateway_zero"
    return "ran_zero"


def collect(roots):
    best = {}
    for root in roots:
        for rj in sorted(pathlib.Path(root).rglob("run.json")):
            try:
                r = json.loads(rj.read_text())
            except (OSError, ValueError):
                continue
            task = (r.get("task") or {}).get("id") or ""
            if not task:
                p = rj.parent.parts
                task = p[-3].replace("__", "/") if len(p) > 3 else rj.parent.name
            u = r.get("usage") or {}
            score = r.get("score")
            score = 0.0 if score is None else float(score)
            rec = {
                "task": task,
                "score": round(score, 4),
                "run_status": r.get("status"),
                "note": note_for(rj.parent, score, r.get("status") or "",
                                 u.get("total_input_tokens") or 0,
                                 (r.get("timings") or {}).get("duration_s") or 0.0),
                "in_tok": u.get("total_input_tokens") or 0,
                "out_tok": u.get("total_output_tokens") or 0,
                "dur_s": round((r.get("timings") or {}).get("duration_s") or 0.0, 1),
                "trajectory": str(rj.parent / "trajectory.json"),
            }
            # Keep the best run per task: higher score wins; at EQUAL score,
            # prefer a real completed run (ok/gateway_last/ran_zero) over a
            # gateway_zero/data_missing non-run — otherwise a task that truly
            # ran to a 0 (e.g. openroad's 2.9 h PnR flow) stays mislabeled
            # gateway_zero and the loop re-runs it forever for nothing.
            def _rank(r):
                real = 1 if r["note"] in ("ok", "gateway_last", "ran_zero") else 0
                return (r["score"], real)
            prev = best.get(task)
            if prev is None or _rank(rec) > _rank(prev):
                best[task] = rec
    return best


def main():
    out_csv, roots = sys.argv[1], sys.argv[2:]
    rows = sorted(collect(roots).values(), key=lambda r: r["task"])
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["task", "score", "run_status", "note",
                                           "in_tok", "out_tok", "dur_s", "trajectory"])
        w.writeheader()
        w.writerows(rows)
    n = len(rows)
    scored = [r for r in rows if r["note"] in ("ok", "gateway_last", "ran_zero")]
    gw = [r for r in rows if r["note"] == "gateway_zero"]
    dm = [r for r in rows if r["note"] == "data_missing"]
    mean_scored = sum(r["score"] for r in scored) / len(scored) if scored else 0.0
    print(f"rows: {n}")
    print(f"  trustworthy scores: {len(scored)}  (mean {mean_scored:.4f}, "
          f"perfect {sum(1 for r in scored if r['score'] >= 0.999)})")
    print(f"  gateway_zero (retry): {len(gw)}")
    print(f"  data_missing (stage): {len(dm)}")
    print(f"wrote {out_csv}")


if __name__ == "__main__":
    main()
