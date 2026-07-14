#!/usr/bin/env python3
"""Pretty-print an ALE trajectory.json (pi harness). Usage: view_pi_trajectory.py <trajectory.json | run_output_dir>"""
import json, sys, os
p = sys.argv[1]
if os.path.isdir(p):
    p = os.path.join(p, "trajectory.json")
d = json.load(open(p))
def clip(s, n=260):
    s = " ".join(str(s).split())
    return s[:n] + (" …" if len(s) > n else "")
a = d["agent"]
print(f"agent={a['name']} model={a.get('model')}  steps={len(d['steps'])}")
fm = d.get("final_metrics", {})
print(f"status={fm.get('status')} reward={fm.get('reward')} in_tok={fm.get('total_input_tokens')} out_tok={fm.get('total_output_tokens')}")
print("=" * 90)
for s in d["steps"]:
    sid, src = s["step_id"], s["source"]
    if s.get("reasoning"):
        print(f"[{sid}] THINK {src}: {clip(s['reasoning'],220)}")
    if s.get("message"):
        print(f"[{sid}] MSG   {src}: {clip(s['message'],220)}")
    for tc in s.get("tool_calls") or []:
        print(f"[{sid}] CALL  {src}: {tc['name']}({clip(json.dumps(tc['arguments']),180)})")
    obs = s.get("observation")
    if obs:
        for r in obs.get("results", []):
            txt = "".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")
            print(f"[{sid}] RSLT  {src}: {'ERR ' if r.get('is_error') else ''}{clip(txt,180)}")
