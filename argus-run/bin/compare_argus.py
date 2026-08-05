#!/usr/bin/env python3
"""Score + cost comparison for an argus run root against ale_claw history.

Scores reuse the historical base means already pinned in ``compare_vs_base.py``
(multi-run averages; the base arm is not re-run). Cost is reported in tokens and
wall time rather than USD: ale_claw prices its calls through litellm, but the
codex frames argus records carry no price for a gateway model, so
``total_cost_usd`` is 0 on the argus side and a USD comparison would be a
fabricated number.

Usage:
    python3 compare_argus.py <argus_run_root> [<ale_claw_run_root> ...]
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from compare_vs_base import BASE  # noqa: E402


def collect(root: pathlib.Path) -> dict[str, dict[str, dict]]:
    """arm -> task -> {score, status, tokens, duration}."""
    out: dict[str, dict[str, dict]] = {}
    for run_json in sorted(root.rglob("run.json")):
        try:
            r = json.loads(run_json.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        arm = (r.get("agent") or {}).get("id") or "?"
        task = (r.get("task") or {}).get("id") or ""
        if not task:
            parts = run_json.parent.parts
            task = parts[-3].replace("__", "/") if len(parts) > 3 else run_json.parent.name
        usage = r.get("usage") or {}
        rec = {
            "score": r.get("score"),
            "status": r.get("status"),
            "in": usage.get("total_input_tokens") or 0,
            "out": usage.get("total_output_tokens") or 0,
            "usd": usage.get("total_cost_usd") or 0.0,
            "dur": (r.get("timings") or {}).get("duration_s") or 0.0,
        }
        prev = out.setdefault(arm, {}).get(task)
        if prev is None or (prev.get("score") is None and rec["score"] is not None):
            out[arm][task] = rec
    return out


def report(root: pathlib.Path) -> None:
    data = collect(root)
    print(f"\n{'=' * 104}\n{root}\n{'=' * 104}")
    for arm in sorted(data):
        rows, deltas = [], []
        for task in sorted(BASE):
            rec = data[arm].get(task)
            if not rec:
                continue
            score = rec["score"]
            delta = None if score is None else round(score - BASE[task], 4)
            if delta is not None:
                deltas.append(delta)
            rows.append((task, BASE[task], score, delta, rec))

        print(f"\n--- {arm}  ({len(rows)} units, {len(deltas)} scored) ---")
        print(f"{'task':56s} {'base':>6s} {'run':>6s} {'delta':>7s} "
              f"{'in_tok':>9s} {'out_tok':>8s} {'dur_s':>7s}  notes")
        for task, base, score, delta, rec in rows:
            note = "" if rec["status"] == "completed" else str(rec["status"])
            print(f"{task[:56]:56s} {base:6.3f} "
                  f"{'-' if score is None else format(score, '6.3f')} "
                  f"{'-' if delta is None else format(delta, '+7.3f')} "
                  f"{rec['in']:9d} {rec['out']:8d} {rec['dur']:7.0f}  {note}")

        if deltas:
            mean = statistics.fmean(deltas)
            sd = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
            t = mean / (sd / len(deltas) ** 0.5) if sd else float("inf")
            pos = sum(1 for d in deltas if d > 1e-9)
            neg = sum(1 for d in deltas if d < -1e-9)
            print(f"\n  score   paired mean {mean:+.4f}  sd {sd:.4f}  t {t:+.2f}  "
                  f"n {len(deltas)}  (+{pos} / ={len(deltas) - pos - neg} / -{neg})")
        tot_in = sum(r["in"] for r in data[arm].values())
        tot_out = sum(r["out"] for r in data[arm].values())
        tot_usd = sum(r["usd"] for r in data[arm].values())
        tot_dur = sum(r["dur"] for r in data[arm].values())
        n = len(rows) or 1
        print(f"  cost    in {tot_in:,} out {tot_out:,} tok "
              f"({tot_in // n:,}/{tot_out // n:,} per task)  "
              f"wall {tot_dur / 3600:.2f} h  usd {tot_usd:.2f}"
              f"{'  (usd unpriced on this arm)' if tot_usd == 0 else ''}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    for r in sys.argv[1:]:
        report(pathlib.Path(r))
