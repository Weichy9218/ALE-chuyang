#!/usr/bin/env bash
# k=3 driver — reviewer arm, sec_10k only, GUARD validation. See
# settings_reviewer_guard_sec10k.yaml. Runs the generated reviewer exp 3x
# sequentially (fresh GMT-second stamp per pass; summarize keeps newest, so we
# aggregate the 3 stamps at read time).
set -u
cd ~/ale/agents-last-exam || exit 1
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
set -a; . secret/.env; set +a
export PATH="$HOME/.local/bin:$PATH"
BOYUE_OPENAI_BASE=${ale_url%/}
case $BOYUE_OPENAI_BASE in */v1) ;; *) BOYUE_OPENAI_BASE=$BOYUE_OPENAI_BASE/v1 ;; esac
export GPT_SUB2API_OPENAI_BASE=${GPT_sub2api_URL%/} BOYUE_OPENAI_BASE

exp="exp_reviewer_guard_sec10k_reviewer.yaml"
for pass in 1 2 3; do
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) guard sec_10k pass=$pass START ==="
  .venv/bin/python -m ale_run run "$exp" >> "k3_guard_reviewer.log" 2>&1
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) guard sec_10k pass=$pass END rc=$? ==="
done
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ALL DONE ==="
