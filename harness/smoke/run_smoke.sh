#!/usr/bin/env bash
# 冒烟测试:用本地 mock 网关驱动 pi(json 模式),验证三个 guard extension 的触发路径。
# 用法: ./run_smoke.sh [guard|loop|metric]
set -euo pipefail

SCENARIO="${1:-guard}"
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_CLI="${PI_CLI:-/home/dataset-local/wcy/ALE-Test/pi/packages/coding-agent/dist/cli.js}"
PORT="${MOCK_PORT:-$((18000 + RANDOM % 4000))}"   # 每次随机端口,避免并发/残留实例串场
PI_TIMEOUT="${PI_TIMEOUT:-90}"                     # pi 自身限时,护栏失效时兜底
RUN_ROOT="${SMOKE_ROOT:-$(mktemp -d /tmp/claude-1000/pi-smoke.XXXXXX)}"

AGENT_DIR="$RUN_ROOT/agent-config"
TASK_DIR="$RUN_ROOT/task"
mkdir -p "$AGENT_DIR/extensions" "$TASK_DIR"

# 1) 装配 agent 目录:models.json 指向 mock 网关,extensions 放三个守卫。
cat > "$AGENT_DIR/models.json" <<EOF
{
  "providers": {
    "mock": {
      "baseUrl": "http://127.0.0.1:$PORT/v1",
      "api": "openai-completions",
      "apiKey": "mock-key",
      "models": [
        {"id": "mock-1", "name": "mock-1", "reasoning": false,
         "contextWindow": 128000, "maxTokens": 8192}
      ]
    }
  }
}
EOF
cp "$HARNESS_DIR"/extensions/*.ts "$AGENT_DIR/extensions/"

# 2) 任务目录:一个已存在的 data.txt(用于未读先改的拦截)。
printf 'hello world\n' > "$TASK_DIR/data.txt"
rm -rf "$TASK_DIR/output"

# 3) 起 mock 网关。
MOCK_SCRIPT="$SCENARIO" MOCK_PORT="$PORT" python3 "$HARNESS_DIR/smoke/mock_gateway.py" \
  > "$RUN_ROOT/mock.log" 2>&1 &
MOCK_PID=$!
trap 'kill $MOCK_PID 2>/dev/null || true; pkill -P $$ 2>/dev/null || true' EXIT
sleep 0.5
grep -q "Address already in use" "$RUN_ROOT/mock.log" 2>/dev/null && { echo "mock 端口冲突,退出"; exit 3; }

# 4) 场景相关的 guard 配置。
declare -a ENV_KV=(
  "PI_CODING_AGENT_DIR=$AGENT_DIR"
  "PI_SKIP_VERSION_CHECK=1" "PI_TELEMETRY=0" "NO_COLOR=1"
)
case "$SCENARIO" in
  guard)
    ENV_KV+=("PI_GUARD_BUDGET=off" "PI_MIRROR_MAX_NUDGES=1")
    PROMPT="Process data.txt and write output/results.json with the required metric." ;;
  loop)
    ENV_KV+=("PI_BUDGET_MAX_TURNS=3" "PI_BUDGET_WARN_FRAC=0.5"
             "PI_GUARD_ACTION=off" "PI_GUARD_MIRROR=off")
    PROMPT="Loop forever." ;;
  metric)
    ENV_KV+=("PI_GUARD_BUDGET=off" "PI_GUARD_ACTION=off" "PI_MIRROR_FILES=off"
             "PI_MIRROR_MAX_NUDGES=1"
             'PI_MIRROR_METRIC_SPEC=[{"file":"output/results.json","path":"metric","op":"<=","target":0.05,"label":"metric"}]')
    PROMPT="Compute the metric and write output/results.json. The task requires metric <= 0.05." ;;
  *) echo "unknown scenario: $SCENARIO"; exit 2 ;;
esac

# 5) 跑 pi(json 模式,stdin 必须重定向,契约同 ALE deployer)。
echo "== run dir: $RUN_ROOT"
( cd "$TASK_DIR" && env "${ENV_KV[@]}" timeout "$PI_TIMEOUT" node "$PI_CLI" \
    --mode json --provider mock --model mock-1 \
    --no-session --no-context-files --thinking off \
    "$PROMPT" < /dev/null > "$RUN_ROOT/transcript.jsonl" 2> "$RUN_ROOT/stderr.log" ) || true

# 6) 断言。
python3 "$HARNESS_DIR/smoke/check_smoke.py" "$SCENARIO" "$RUN_ROOT"
