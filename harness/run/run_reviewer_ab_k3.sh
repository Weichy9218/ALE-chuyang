#!/usr/bin/env bash
# ============================================================================
# k=3 SEQUENTIAL A/B driver for the reviewer arm (base vs reviewer), boyue.
#
# k=3 mechanism: there is no repeat knob. run_writer timestamps each run dir,
# and summarize.py keeps only the NEWEST run per (arm,task). So k=3 = run each
# arm's generated exp yaml 3x SEQUENTIALLY (fresh GMT-second stamp per pass) and
# aggregate the 3 stamps at read time. Passes are minutes apart, so no run-dir
# collision.
#
# Parallelism is kept LOW for boyue (shared Azure quota behind a load balancer):
#   - concurrency=2 WITHIN a pass (from settings) => <=2 units in flight;
#   - the two ARMS run sequentially (not concurrently) => the arm's audit
#     sub-agent never competes with the other arm's writers.
# The reviewer arm runs FIRST so the fresh-auditor Responses path validates early.
#
# Transport note: gpt-5.6-sol runs over /v1/responses with store=False and prior
# reasoning items dropped from the input (boyue is load-balanced + does not
# persist/return reasoning content; resending an rs_ shell 400s). See
# unified_loop._responses_input / _predict_step_responses.
#
# Launch (from ~/ale/agents-last-exam, after the dry-run generated the exp yamls):
#   nohup bash harness/run/run_reviewer_ab_k3.sh > k3_driver.log 2>&1 & disown
# Read back:
#   python3 harness/run/summarize.py .logs/ale/reviewer_ab --baseline ale_claw_base
# ============================================================================
set -u
cd ~/ale/agents-last-exam || exit 1

# Endpoint env (mirrors launch.py's env_block). secret_file in the exp yaml
# (secret/.env.boyue) is what the runner reloads with override to pick the REAL
# endpoint; this prelude only supplies the base-URL shell vars.
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
set -a; . secret/.env; set +a
export PATH="$HOME/.local/bin:$PATH"
BOYUE_OPENAI_BASE=${ale_url%/}
case $BOYUE_OPENAI_BASE in */v1) ;; *) BOYUE_OPENAI_BASE=$BOYUE_OPENAI_BASE/v1 ;; esac
export GPT_SUB2API_OPENAI_BASE=${GPT_sub2api_URL%/} BOYUE_OPENAI_BASE

run_arm () {
  local arm="$1" exp="exp_reviewer_ab_smoke_${1}.yaml" pass
  for pass in 1 2 3; do
    echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) arm=$arm pass=$pass START ==="
    .venv/bin/python -m ale_run run "$exp" >> "k3_${arm}.log" 2>&1
    echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) arm=$arm pass=$pass END rc=$? ==="
  done
}

run_arm reviewer
run_arm base
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ALL DONE ==="
