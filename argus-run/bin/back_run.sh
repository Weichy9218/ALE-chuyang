#!/bin/bash
# Second concurrency-3 pass over the REMAINING tasks, tail-first (back-to-front),
# to roughly double throughput against the front-to-back main loop (loop_run.sh).
# Combined gateway load is ~conc6 — an experiment to see if Boyue tolerates more
# now that the box is uncontested. If stream-drops (gateway_zero) spike, kill this.
#
# Excludes, so nothing already-done is re-run and nothing running is disturbed:
#   - trustworthy-scored tasks (note ok/gateway_last/ran_zero)
#   - tasks whose _launcher is currently running (the main loop's live tasks)
#   - variant==None tasks (quarantined, e.g. amber: baked reference in image)
#
# Run once:  cd ~/ale/agents-last-exam && nohup bash ~/argus/bin/back_run.sh > ~/argus/logs/back_main.log 2>&1 &
set -u
cd ~/ale/agents-last-exam
ARG=$HOME/argus
ts=$(date +%Y%m%d_%H%M%S)
mkdir -p $ARG/runs/back $ARG/logs
DRIVER=$ARG/logs/back_driver.log

LOOP=$(ls -d $ARG/runs/loop/*/ 2>/dev/null | tr '\n' ' ')
BACKS=$(ls -d $ARG/runs/back/*/ 2>/dev/null | tr '\n' ' ')
python3 $ARG/bin/make_scoreboard.py /tmp/back_score_$ts.csv \
  $ARG/runs/run26/argus_26 $ARG/runs/retry/argus_retry \
  $ARG/runs/rest/argus_rest $ARG/runs/full96/argus_full96 $BACKS $LOOP >/dev/null 2>&1

python3 - "$ts" <<'PY'
import csv, os, re, subprocess, sys
ts = sys.argv[1]; ARG = os.path.expanduser("~/argus")
scored = set()
try:
    for r in csv.DictReader(open(f"/tmp/back_score_{ts}.csv")):
        if r["note"] in ("ok", "gateway_last", "ran_zero"):
            scored.add(r["task"])
except FileNotFoundError:
    pass
# currently-running task ids (domain/task) from the launcher command lines
running = set()
ps = subprocess.run(["bash", "-lc", "ps -eo args | grep _launcher | grep -v grep"],
                    capture_output=True, text=True).stdout
for m in re.finditer(r"argus_full4__gpt-5-6-sol__([a-z0-9_]+)__v0__", ps, re.I):
    dom, task = m.group(1).split("__", 1)
    running.add(f"{dom}/{task}")
back = []
for line in open(f"{ARG}/config/task_variants.txt"):
    t, v = line.rstrip("\n").split("\t")
    if v == "None":
        continue
    d = f"task-data/{t}/{v}"
    if (os.path.isdir(f"{d}/input") and os.path.isdir(f"{d}/reference")
            and t not in scored and t not in running):
        back.append(t)
back.reverse()  # tail-first
open(f"{ARG}/config/back_torun.txt", "w").write("\n".join(back) + "\n")
print(len(back))
PY

N=$(grep -cvE '^$' $ARG/config/back_torun.txt)
echo "[back $ts] launching $N tasks tail-first @conc3 -> runs/back/$ts" | tee -a $DRIVER
sed -e "s#tasks:.*#tasks: $ARG/config/back_torun.txt#" \
    -e "s#root:.*#root: $ARG/runs/back/$ts#" \
    $ARG/config/exp_argus.yaml > $ARG/config/_exp_back_$ts.yaml
.venv/bin/python -m ale_run run $ARG/config/_exp_back_$ts.yaml >> $ARG/logs/back_round_$ts.log 2>&1
echo "[back $ts done $(date +%H:%M)]" | tee -a $DRIVER
