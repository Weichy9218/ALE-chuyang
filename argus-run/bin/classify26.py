"""Classify each argus unit by its terminal failure mode + score."""
import glob
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
rows = []
for traj in sorted(root.glob("*/v0/*/trajectory.json")):
    task = traj.parts[-4]
    d = json.loads(traj.read_text())
    score = (d.get("final_metrics") or {}).get("reward")
    ev = traj.parent / "origin_log" / "argus" / "argus_home" / "projects" / "ale" / "events.jsonl"
    last_reason = ""
    if ev.is_file():
        for line in ev.open():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("type") == "round.review.completed":
                last_reason = r.get("reason") or ""
    low = last_reason.lower()
    if "stream discon" in low or "response.failed" in low:
        cls = "GATEWAY_STREAM_FAIL"
    elif "engineer backend failed" in low or "reviewer backend" in low:
        cls = "BACKEND_FAIL"
    else:
        cls = "ran"
    rows.append((score if score is not None else -1.0, task, cls, last_reason[:90]))

rows.sort()
for score, task, cls, reason in rows:
    print(f"{score:>6}  {cls:20s}  {task[:44]:44s}  {reason}")

retry = [t for s, t, c, r in rows if c in ("GATEWAY_STREAM_FAIL", "BACKEND_FAIL")]
print("\n# retry candidates:", len(retry))
for t in retry:
    print(t.replace("__", "/"))
