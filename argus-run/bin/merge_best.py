"""Merge two argus run roots task-by-task, keeping the higher score per task,
then report vs base with per-task token/dur from the kept run."""
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from compare_vs_base import BASE  # noqa: E402


def collect(root: pathlib.Path) -> dict[str, dict]:
    out = {}
    for rj in sorted(root.rglob("run.json")):
        try:
            r = json.loads(rj.read_text())
        except (OSError, ValueError):
            continue
        task = (r.get("task") or {}).get("id") or ""
        if not task:
            p = rj.parent.parts
            task = p[-3].replace("__", "/") if len(p) > 3 else rj.parent.name
        u = r.get("usage") or {}
        rec = {
            "score": r.get("score"),
            "in": u.get("total_input_tokens") or 0,
            "out": u.get("total_output_tokens") or 0,
            "dur": (r.get("timings") or {}).get("duration_s") or 0.0,
        }
        prev = out.get(task)
        if prev is None or (rec["score"] or -1) > (prev["score"] or -1):
            out[task] = rec
    return out


roots = [pathlib.Path(p) for p in sys.argv[1:]]
merged: dict[str, dict] = {}
for root in roots:
    for task, rec in collect(root).items():
        prev = merged.get(task)
        if prev is None or (rec["score"] or -1) > (prev["score"] or -1):
            merged[task] = rec

deltas, tin, tout, tdur = [], 0, 0, 0.0
print(f"{'task':56s} {'base':>6s} {'best':>6s} {'delta':>7s} {'in_tok':>10s} {'out':>7s} {'dur':>6s}")
for task in sorted(BASE):
    rec = merged.get(task)
    if not rec:
        print(f"{task[:56]:56s} {BASE[task]:6.3f}   MISSING")
        continue
    s = rec["score"]
    d = None if s is None else round(s - BASE[task], 4)
    if d is not None:
        deltas.append(d)
    tin += rec["in"]; tout += rec["out"]; tdur += rec["dur"]
    print(f"{task[:56]:56s} {BASE[task]:6.3f} {s:6.3f} {d:+7.3f} "
          f"{rec['in']:10d} {rec['out']:7d} {rec['dur']:6.0f}")

mean = statistics.fmean(deltas)
sd = statistics.stdev(deltas)
t = mean / (sd / len(deltas) ** 0.5)
pos = sum(1 for d in deltas if d > 1e-9)
neg = sum(1 for d in deltas if d < -1e-9)
n = len(deltas)
print(f"\nMERGED-BEST  paired mean {mean:+.4f}  sd {sd:.4f}  t {t:+.2f}  "
      f"n {n}  (+{pos} / ={n - pos - neg} / -{neg})")
print(f"argus best-of total: in {tin:,} out {tout:,}  ({tin // n:,}/{tout // n:,} per task)  wall {tdur / 3600:.1f}h")
