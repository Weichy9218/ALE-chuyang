#!/usr/bin/env python3
"""Summarize a pi ALE run: score distribution, status breakdown, and flag
zero-score tasks that look internet/search-dependent (to attribute web-tool gap).
Usage: summarize_pi_cli.py [output_root]
"""
import json, glob, os, sys, collections

root = sys.argv[1] if len(sys.argv) > 1 else ".logs/ale/local_docker_pi_qwen35_cli"
NET_KW = ["download", "http://", "https://", "internet", "fetch the", "web search",
          "search the", "api endpoint", "curl ", "wget ", "scrape", "crawl"]

def task_prompt(slug):
    parts = slug.split("__", 1)
    if len(parts) != 2: return ""
    p = f"tasks/{parts[0]}/{parts[1]}/task_card.json"
    try:
        d = json.load(open(p))
        return (d.get("taskPrompt","") + " " + json.dumps(d.get("inputFiles",[]))).lower()
    except Exception: return ""

rows = []
for f in sorted(glob.glob(os.path.join(root, "**", "run.json"), recursive=True)):
    try: d = json.load(open(f))
    except Exception: continue
    rows.append({
        "slug": d.get("task",{}).get("slug", os.path.basename(os.path.dirname(f))),
        "status": d.get("status"), "score": d.get("score"),
        "dur": (d.get("timings",{}) or {}).get("duration_s"),
        "term": (d.get("termination",{}) or {}).get("reason"),
    })

n = len(rows)
by_status = collections.Counter(r["status"] for r in rows)
scores = [r["score"] for r in rows if isinstance(r["score"], (int,float))]
solved = [r for r in rows if (r["score"] or 0) >= 1.0]
partial = [r for r in rows if 0 < (r["score"] or 0) < 1.0]
zero = [r for r in rows if (r["score"] or 0) == 0]

print(f"=== pi CLI run summary: {root} ===")
print(f"runs found: {n}   status: {dict(by_status)}")
if scores:
    print(f"score_sum={sum(scores):.3f}  mean={sum(scores)/len(scores):.3f}  "
          f"solved(=1.0)={len(solved)}  partial={len(partial)}  zero={len(zero)}")
print("\n=== SOLVED (score=1.0) ===")
for r in sorted(solved, key=lambda x: x["slug"]):
    print(f"  1.00  {r['slug']}  ({(r['dur'] or 0):.0f}s)")
print("\n=== PARTIAL (0<score<1) ===")
for r in sorted(partial, key=lambda x: -(x["score"] or 0)):
    print(f"  {r['score']:.3f}  {r['slug']}  ({(r['dur'] or 0):.0f}s)")

timeouts = [r for r in rows if r["status"] == "timeout"]
print(f"\n=== TIMEOUTS: {len(timeouts)} ===")
for r in sorted(timeouts, key=lambda x: x["slug"]):
    print(f"  score={r['score']}  {r['slug']}  ({(r['dur'] or 0):.0f}s)")

net_fail = [r for r in zero if any(k in task_prompt(r["slug"]) for k in NET_KW)]
print(f"\n=== ZERO-SCORE: {len(zero)} ; internet-keyword subset: {len(net_fail)} ===")
print("  [internet-keyword zero-score - web-tool-gap candidates]")
for r in sorted(net_fail, key=lambda x: x["slug"]):
    print(f"    {r['status']:<10} term={r['term']}  {r['slug']}")
print("  [other zero-score]")
for r in sorted([r for r in zero if r not in net_fail], key=lambda x: x["slug"]):
    print(f"    {r['status']:<10} term={r['term']}  {r['slug']}")
