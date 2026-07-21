# 从 pi 轨迹构造可验证训练数据

本文给数据构造方案:数据来源、schema、筛选规则、抽取脚本、当前样本,以及新题扩造的路线。目标是把 pi 在 ALE 上跑出的轨迹变成 SFT 正样本和偏好对,喂给后训练;同时守住不泄露红线,轨迹里不能带任何参考答案。

结论先说:抽取脚本 `data/extract_pi_training_data.py` 已跑通,从本机 `.logs` 的 pi 运行里抽出 15 条满分 SFT 正样本(gpt-5.6-sol 6 条、Qwen3.5-397B 9 条)和 3 对偏好样本,泄露检测为零命中。方案分两块:先从现有轨迹筛,再基于现有题型参数化扩造新题、跑新轨迹、再筛。

## 1. 为什么用 pi 的轨迹做训练源

三个理由,都来自 pi 的工程特性,不是空话。

第一,判分可验证。每个任务目录有 `run.json`,里面 `score` 是 ALE 评测器给的 [0,1] 分,`status` 是 completed/failed/timeout。这是确定性奖励,不需要再训一个奖励模型来打分。SFT 正样本直接按 score 阈值筛,偏好对按同任务的分差构造。

第二,轨迹高保真且可解析。pi 的原始事件流 `origin_log/pi/transcript.jsonl` 逐条记录 message_end 事件,每条带完整字段:assistant 的 thinking 块、text、tool_calls,toolResult 的内容和 isError,以及每轮的 usage(input/output/cacheRead token)。这些是 SFT 需要的全部信号,不用从渲染日志里反解。

第三,格式稳定。pi 的 transcript schema 有版本号(当前 v3),字段固定,跨模型跨任务一致。同一个抽取脚本能处理 gpt-5.6-sol 和 Qwen3.5-397B 两批,不用改代码。

## 2. 数据来源的目录结构

ale_run 的输出根是 `.logs/ale/<实验名>/<harness>/<model>/`,其下每个任务一个目录,再往下是 `v<变体>/<时间戳>/` 一次 attempt。一次 attempt 目录里,抽取脚本用到三个文件:

- `run.json`:分数、状态、用量汇总。取 `score`、`status`、`usage.total_steps`、`usage.total_input_tokens` 等。
- `origin_log/pi/transcript.jsonl`:pi 原始事件流,消息级训练源。
- `origin_log/pi/prompt.txt`:任务 prompt(用于新题去重和泄露审计的路径提取)。

一个任务可能有多次 attempt(不同实验、重跑),抽取脚本按 (任务, 变体, 时间戳) 唯一标识每次 attempt,偏好对就在同任务的不同 attempt 之间配。

## 3. schema

抽取产出三个文件,都在 `--out` 指定的目录下。

### 3.1 sft.jsonl（每行一条成功轨迹）

```
{
  "schema_version": 1,
  "source": {"harness": "pi", "run_dir": "<attempt 目录绝对路径>", "attempt_ts": "20260712_062522"},
  "task": {"slug": "computing_math__branch_bound_atsp", "domain": "computing_math",
           "name": "branch_bound_atsp", "variant": "v0"},
  "model": "gpt-5.6-sol",
  "reward": {"score": 1.0, "status": "completed", "verifier": "ale.evaluate"},
  "usage": {"steps": 40, "input_tokens": 22649, "output_tokens": 5140,
            "cache_read_tokens": 143872, "duration_ms": 1203689},
  "quality": {"reference_touches": [], "leak_mentions": [], "harness_injections": 0,
              "abnormal_stop_reasons": []},
  "messages": [
    {"role": "user", "content": "You are working on a Linux VM. ## Task ..."},
    {"role": "assistant", "thinking": "**Planning inspection**", "content": "I'll read the spec first.",
     "tool_calls": [{"id": "call_...", "name": "read", "arguments": {"path": "..."}}],
     "usage": {"input": 5734, "output": 239}},
    {"role": "tool", "tool_call_id": "call_...", "content": "<文件内容,超长会被截断>", "is_error": false},
    ...
  ]
}
```

messages 是 OpenAI 风格的多轮对话,role 取 user/assistant/tool。assistant 消息保留 thinking(供过程监督用,不需要就丢),tool_calls 是原生工具调用数组,tool 消息带 tool_call_id 对齐调用。`quality` 是审计字段,训练前可据此再过滤。

### 3.2 pairs.jsonl（每行一对偏好样本）

```
{
  "schema_version": 1,
  "task": "transport_safety__capacitated_vehicle_routing_problems",
  "chosen":   {"run_dir": "...", "score": 1.0},
  "rejected": {"run_dir": "...", "score": 0.0},
  "margin": 1.0,
  "chosen_messages":   [...],
  "rejected_messages": [...]
}
```

同一任务的两次 attempt,分高的做 chosen、分低的做 rejected,分差达阈值才成对。用于 DPO 类偏好优化,或做过程监督的正负对照。

### 3.3 stats.json（抽取统计）

记 attempts_seen、sft_kept、各类剔除计数(drop_score/drop_status/drop_steps/drop_leak)、pairs_kept、truncated_tool_results 等。每次抽取都要看这个,确认筛掉的量和原因符合预期。

## 4. 筛选规则

### 4.1 SFT 正样本

四个条件全过才留:

- `status == "completed"`。排除超时(timeout)和进程报错(failed)。
- `score >= --min-score`(默认 1.0)。只要满分轨迹当正样本;想放宽到部分正确就调低。
- 步数 `<= --max-steps`(默认 200)。挡住失控的长轨迹。
- 无硬泄露标记(见 4.3)。

按这个顺序检查,记录第一个命中的剔除原因,方便从 stats 看筛选构成。

### 4.2 偏好对

同任务跨 attempt,`chosen.score - rejected.score >= --pair-margin`(默认 0.3)。两条都不能有硬泄露标记。分差越大对比越干净,但太严会没有对;0.3 是当前数据下能出对的阈值。

### 4.3 泄露检测（红线的自动兜底）

这是数据管线守不泄露红线的关键,分两级。

硬标记,命中即剔除:检查 agent 的**工具调用参数**里有没有触碰评测答案目录。ALE 的任务布局是 `base/{input,reference,software}`,`base/reference/` 是评测答案,`base/input/` 是 agent 合法输入。所以只锚定 `base/reference` 这一层路径。这是行为级核查——看 agent 实际读没读答案,而不是看文本里有没有 reference 这个词。

这里踩过一个坑,值得记下。第一版正则宽泛匹配 `reference`,把生物信息任务的参考基因组 `base/input/starter_project/reference/GRCh38_chr22.fa`、以及自检数据 `base/input/reference_output/` 都误判成泄露。这些是任务给 agent 的合法输入,不是答案。收紧到只匹配 `base/reference` 后,7 条误报清零,真实硬泄露命中为零——这反过来验证了项目声称的干净基线:agent 运行期确实没有读过参考答案。

软标记,只记录不剔除:文本里出现 ground-truth、answer-key 这类词,可能来自任务说明自身(任务会明说"不要读 reference"),不构成泄露,记进 `quality.leak_mentions` 供人工复查。

harness 注入的 `[harness ...]` 文本单独计数记进 `quality.harness_injections`。`--strip-harness` 时从消息里剥掉,用来训练"没有 harness 也会做对"的干净行为,对应 harness 研究的 strip 测试。

## 5. 抽取脚本与当前样本

脚本:`data/extract_pi_training_data.py`。用法:

```bash
python3 data/extract_pi_training_data.py \
  --run-root .logs/ale/gpt56_full_pi/pi/gpt-5-6-sol \
  --run-root .logs/ale/gpt56_batch_pi/pi/gpt-5-6-sol \
  --out data/samples/gpt56 --min-score 1.0 --pair-margin 0.3
```

`--run-root` 可传多个,把同模型的多个实验合起来抽(全量跑 + 重跑 + 补跑)。`--strip-harness` 剥掉 harness 注入,`--keep-leaky` 调试时保留泄露轨迹看命中了什么。

当前从本机 `.logs` 抽出的样本:

| 批次 | attempts | SFT 正样本 | 偏好对 | 硬泄露命中 |
|---|---|---|---|---|
| gpt-5.6-sol（gpt56_full_pi + batch） | 31 | 6 | 0 | 0 |
| Qwen3.5-397B（cli 99 + rerun13 + retry3） | 115 | 9 | 3 | 0 |

样本落在 `data/samples/gpt56/` 和 `data/samples/qwen35/`。SFT 正样本覆盖 branch_bound_atsp、ising_post_measurement、k3_abelian_extensions、os_log_permission_guard 这些有确定性算法、判分明确的题——和 25 题对跑里两套 harness 都拿满分的题重合,不是偶然,这类题正是可验证奖励最干净的来源。偏好对目前只有 3 对,因为多数任务只跑了一次 attempt,没有同任务的分数分化可配。

样本量小是现状的真实反映:满分轨迹本来就少(96 个真实尝试里只有约 10 个满分)。这直接指向第 6 节——要扩大可验证任务集,得自己造同分布的新题,而不是指望从现有 165 题里榨出更多满分轨迹。

## 6. 新题扩造

现有满分轨迹稀缺,且不能用 ALE 原题做训练(会把 benchmark 泄露进训练集)。所以要基于现有题型构造同构的新题,用它们跑新轨迹再筛。三条原则。

### 6.1 参数化变体,不复制原题

选判分确定、参数可换的题型,把题面里的数值、实例、随机种子换掉,生成同分布但不同实例的新题。chuyang 的 26 题批次(`docs/harness/results/latest/tasks.txt`)里有现成的可参数化题型:

- american_option_pricing_ls(蒙特卡洛期权定价):换期权参数(行权价、波动率、到期、利率)、随机种子,判分仍是数值容差,答案由参数唯一确定。
- capacitated_vehicle_routing_problems(CVRP):换客户坐标、需求、车容量,判分是解的成本对最优的比值,可用求解器算参考。
- exact_diag_heisenberg(海森堡精确对角化):换格子尺寸、耦合常数,判分是本征值容差。
- gillespie 随机模拟、蒙特卡洛类:换反应速率、初始态、种子。

这些题的共同点是:题面参数 → 唯一正确答案是一个可程序计算的映射。造新题 = 采一组新参数 + 用一个独立的参考实现算出答案 + 写判分器。agent 看到的只有题面参数,看不到答案。

### 6.2 新题也守不泄露红线

造新题时,参考答案和判分器必须和 agent 可见输入物理隔离,沿用 ALE 的 `base/{input,reference}` 布局:agent 只挂到 `input/`,`reference/` 只在 agent 输出 DONE 之后才 staged 进容器供评测器读。造题脚本要保证 `input/` 里不含任何能反推答案的中间产物(比如别把参考实现的中间输出留在 input 里)。

### 6.3 先造后筛的闭环

流程和现有轨迹一致,只是任务源换成自造的:

1. 造一批新题实例(参数化采样),每题带独立参考实现和判分器。
2. 用 pi(可挂上任务 B 的 harness 干预)跑这批新题,收 transcript 和 run.json。
3. 用本抽取脚本按 score 筛,出 SFT 正样本和偏好对。
4. 泄露审计过一遍(4.3 的硬标记必须为零)。
5. 成功轨迹做 SFT,失败到成功的 attempt 对做偏好/过程监督。

这个闭环和 `next_step.md` 第 5 节的"采轨迹、分析、改规则、验证"是同一套基础设施,数据侧和 harness 侧共用一份轨迹抽取。

## 7. 待办与限制

- 偏好对少,因为多数任务单次 attempt。要多出偏好数据,得对同一批题重复跑几次(每题 3 到 5 次),制造分数分化。这也和对比页说的"单题方差 0.34、需要重复跑才能分出 harness 高下"是同一个需求,重复跑一举两得。
- 当前 SFT 只用满分轨迹。部分正确(0.5 到 0.99)的轨迹里也有可学习的正确片段,但整条不能无条件当正样本。下一步可以做步级筛选:在部分正确轨迹里,挑出那些通过了自检、被后续步骤确认有效的片段。这需要更细的过程标注,先不做。
- tool 结果超长会被截断(默认 8000 字符,记进 truncated_tool_results),截断保留头尾。训练时若需要完整观察,调大 `--max-obs-chars`,但要留意 context 长度。
- 新题扩造还没落地脚本,第 6 节是方案。落地时先做 american_option_pricing 和 CVRP 两个题型的参数化生成器,它们的参考实现最直接。
