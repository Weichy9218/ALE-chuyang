#!/bin/bash
# Drive Argus toward full 105-task coverage on pgl, at a gateway-safe concurrency.
#
# Each round:
#   1. score every run root so far  -> who already has a trustworthy score
#   2. to_run = tasks whose CORRECT-variant data is staged AND not yet trustworthy
#      (trustworthy = note ok/gateway_last/ran_zero; gateway_zero is retried)
#   3. run to_run (concurrency from config/exp_argus.yaml = 3)
#   4. repeat, sleeping between empty rounds so still-transferring task-data is
#      picked up as it lands.
# Stops when all 105 have a trustworthy score, or when nothing is staged-and-unscored
# and no more data is arriving.
#
# Run from pgl:  cd ~/ale/agents-last-exam && nohup bash ~/argus/bin/loop_run.sh > ~/argus/logs/loop_main.log 2>&1 &
set -u
cd ~/ale/agents-last-exam
ARG=$HOME/argus
# ABSOLUTE roots — the cwd is the ALE repo, not ~/argus, so relative "runs/..."
# would resolve wrong and score 0 (learned the hard way).
BASE_ROOTS="$ARG/runs/run26/argus_26 $ARG/runs/retry/argus_retry $ARG/runs/rest/argus_rest $ARG/runs/full96/argus_full96"
mkdir -p $ARG/runs/loop $ARG/logs
DRIVER=$ARG/logs/loop_driver.log

round=0
while true; do
  round=$((round+1))
  LOOPROOTS=$(ls -d $ARG/runs/loop/*/ 2>/dev/null | tr '\n' ' ')
  ALLROOTS="$BASE_ROOTS $LOOPROOTS"

  python3 $ARG/bin/make_scoreboard.py $ARG/argus_scores.csv $ALLROOTS >/dev/null 2>&1
  python3 - <<PY
import csv, os
scored=set()
try:
    for r in csv.DictReader(open("$ARG/argus_scores.csv")):
        if r["note"] in ("ok","gateway_last","ran_zero"): scored.add(r["task"])
except FileNotFoundError: pass
torun=[]
for line in open("$ARG/config/task_variants.txt"):
    t,v=line.rstrip("\n").split("\t")
    if v=="None": continue
    d=f"task-data/{t}/{v}"
    if os.path.isdir(f"{d}/input") and os.path.isdir(f"{d}/reference") and t not in scored:
        torun.append(t)
open("$ARG/config/loop_torun.txt","w").write("\n".join(torun)+"\n")
print(f"round scored={len(scored)} staged_unscored={len(torun)}")
PY

  N=$(grep -cvE '^$' $ARG/config/loop_torun.txt)
  SCORED=$(python3 -c "import csv;print(sum(1 for r in csv.DictReader(open('$ARG/argus_scores.csv')) if r['note'] in ('ok','gateway_last','ran_zero')))" 2>/dev/null || echo 0)
  echo "[round $round $(date +%H:%M)] scored=$SCORED to_run=$N" >> $DRIVER

  if [ "$SCORED" -ge 105 ]; then echo "[DONE all 105 scored]" >> $DRIVER; break; fi
  if [ "$N" -eq 0 ]; then
    echo "[round $round] nothing staged&unscored — waiting 10min for more task-data" >> $DRIVER
    sleep 600; continue
  fi

  ts=$(date +%Y%m%d_%H%M%S)
  sed -e "s#tasks:.*#tasks: $ARG/config/loop_torun.txt#" \
      -e "s#root:.*#root: $ARG/runs/loop/$ts#" \
      $ARG/config/exp_argus.yaml > $ARG/config/_exp_round_$ts.yaml
  echo "[round $round] launching $N tasks @conc3 -> runs/loop/$ts" >> $DRIVER
  .venv/bin/python -m ale_run run $ARG/config/_exp_round_$ts.yaml >> $ARG/logs/round_$ts.log 2>&1
  echo "[round $round done $(date +%H:%M)]" >> $DRIVER
done
python3 $ARG/bin/make_scoreboard.py $ARG/argus_scores.csv $BASE_ROOTS $(ls -d $ARG/runs/loop/*/ 2>/dev/null) >> $DRIVER 2>&1
echo "[loop finished $(date +%H:%M)]" >> $DRIVER
