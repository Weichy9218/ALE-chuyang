#!/usr/bin/env python3
"""Read an ale_run output root and print a per-arm x per-task score table plus
per-arm summary stats and deltas vs a baseline arm. Stdlib only.

Usage:
  python3 harness/run/summarize.py <output_root>/harness_compare [--baseline ale_claw_base]

Counts only status=completed scores in means (an infra failure -> score null is
excluded, matching run.json's score_valid). Prints which units are non-completed.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def load_rows(root: Path):
    rows = []  # (arm_id, task_slug, status, score)
    for rj in root.rglob("run.json"):
        try:
            d = json.loads(rj.read_text(encoding="utf-8"))
        except Exception:
            continue
        agent = (d.get("agent") or {}).get("id") or (d.get("agent") or {}).get("class", "?")
        task = (d.get("task") or {}).get("slug", "?")
        rows.append((agent, task, d.get("status"), d.get("score")))
    return rows


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--baseline", default=None, help="arm id to diff against (default: first)")
    args = ap.parse_args()
    root = Path(args.root)
    if not root.exists():
        print(f"error: {root} not found")
        return 2

    rows = load_rows(root)
    if not rows:
        print(f"no run.json under {root}")
        return 1
    arms = sorted({r[0] for r in rows})
    tasks = sorted({r[1] for r in rows})
    score = {(a, t): s for a, t, st, s in rows}
    status = {(a, t): st for a, t, st, s in rows}

    w = max((len(t) for t in tasks), default=10)
    cw = 16
    print(f"{'task':<{w}}  " + "  ".join(f"{a[:cw]:>{cw}}" for a in arms))
    print("-" * (w + 2 + (cw + 2) * len(arms)))
    for t in tasks:
        cells = []
        for a in arms:
            s = score.get((a, t))
            if _num(s):
                cells.append(f"{s:>{cw}.4f}")
            elif (a, t) in status:
                cells.append(f"{('['+str(status[(a,t)])[:cw-2]+']'):>{cw}}")
            else:
                cells.append(f"{'—':>{cw}}")
        print(f"{t:<{w}}  " + "  ".join(cells))

    print("-" * (w + 2 + (cw + 2) * len(arms)))
    means = {}
    for a in arms:
        vals = [score[(a, t)] for t in tasks
                if _num(score.get((a, t))) and status.get((a, t)) == "completed"]
        means[a] = sum(vals) / len(vals) if vals else float("nan")
        total = sum(vals)
        perfect = sum(1 for t in tasks if score.get((a, t)) == 1)
        zero = sum(1 for t in tasks if score.get((a, t)) == 0 and status.get((a, t)) == "completed")
        nonpass = sum(1 for t in tasks if status.get((a, t)) not in (None, "completed"))
        print(f"{a:<22} mean={means[a]:.4f}  total={total:.3f}  perfect={perfect}  "
              f"zero={zero}  nonpass={nonpass}  n={len(vals)}")

    base = args.baseline or (arms[0] if arms else None)
    if base in arms and len(arms) > 1:
        print(f"--- paired delta vs {base} (tasks both completed) ---")
        for a in arms:
            if a == base:
                continue
            deltas = []
            for t in tasks:
                sa, sb = score.get((a, t)), score.get((base, t))
                if _num(sa) and _num(sb) and status.get((a, t)) == "completed" \
                        and status.get((base, t)) == "completed":
                    deltas.append(sa - sb)
            if not deltas:
                print(f"{a:<22} (no paired tasks)")
                continue
            md = sum(deltas) / len(deltas)
            if len(deltas) > 1:
                sd = math.sqrt(sum((d - md) ** 2 for d in deltas) / (len(deltas) - 1))
                se = sd / math.sqrt(len(deltas))
                t_stat = md / se if se > 0 else float("nan")
                print(f"{a:<22} mean_delta={md:+.4f}  sd={sd:.4f}  se={se:.4f}  "
                      f"t={t_stat:+.2f}  n={len(deltas)}")
            else:
                print(f"{a:<22} mean_delta={md:+.4f}  n={len(deltas)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
