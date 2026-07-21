# Prep v16 六题测试

本目录保存 2026-07-20 至 2026-07-21 的 `task-prep-v16` 六题测试。Base 与 Prep 使用
`openai/gpt-5.6-sol`、同一 API endpoint、同一任务版本和 writer 配置。Base 来自
`prep_bundle_six_v14_base`；最终 Prep writer run 来自 `prep_bundle_six_v16_final`，六题均
并行运行。

## 结果

| 题目 | Base | Prep v16 | 差值 | writer 收到的 Prep |
|---|---:|---:|---:|---|
| BPMN Supply | 0.8505 | 0.8395 | -0.0110 | empty |
| Digital Audience | 0.8667 | 0.9042 | +0.0375 | uv runtime observation |
| SSE Northbound | 0.6667 | 0.6667 | 0.0000 | empty |
| PDE Grading | 0.6316 | 0.6598 | +0.0282 | empty |
| CRF SDTM 4 | 0.6746 | 0.6340 | -0.0406 | empty |
| FluSight | 0.7034 | 0.7469 | +0.0435 | empty |
| **均值** | **0.7322** | **0.7418** | **+0.0096** | 1 completed / 5 empty |

配对差值标准差为 0.0326，标准误为 0.0133，`t=0.72`，harm rate 为 2/6。五个 empty
Prep 的平均差值为 +0.0040；唯一有效报告 Digital 的差值为 +0.0375。Digital 在 v15 的
empty Prep rollout 中也曾得到 0.9042，因此本轮不能把该差值全部归因于 Prep。结果支持
“副作用面已收缩”，不支持“已出现稳定 uplift”。

## Prep 生成和交付

最终 writer run 命中同一公开 task surface 的 Prep cache，用来隔离交付方式：有效报告在
staging 后同时内联到 writer 初始 prompt；empty 任务只收到原任务。Fresh Prep 原件保存在
`raw/fresh_prep/`，其汇总如下：

- 307,056 input tokens，1,095.1 秒，29 次工具调用。
- 1 份报告通过，4 份 skip 或 gate rejection，1 次 300 秒 timeout。
- 通过报告共 2,026 字符；0 个 artifact 通过并交付。
- 单轮 tool result 总量限制为 20KB。开发 preflight 中 SSE 的同类 skip 从 68,078 input
  tokens 降到本轮 47,443；方向有效，但一个 skip 仍然偏贵。

报告先原子写入 `task_prep/PREP_REPORT.md`，再将同一内容内联。Digital 的首个 API request
原件包含完整 Prep 报告；writer 不需要额外文件调用即可 exposure。它先读 brief、governance
和 schema，系统 Python 缺包后使用报告所述的 `/tmp` `UV_CACHE_DIR` 与
`UV_PROJECT_ENVIRONMENT` 执行 `uv sync`。Prep 改变的是 runtime 路径，没有提供 audience
规则、overlap 值或缺失字段处理策略。

## 六题逐项解释

### BPMN Supply

Fresh Prep 尝试生成按 scenario ID 查询规则位置的 resolver，但 task basis 引用了不存在的
`input/task_prompt.md`。source validation 丢弃整个 bundle。即使修正 locator，该 resolver
主要包装 `jq`/`rg`，没有提供 writer 缺少的 Flowable runtime 能力。最终 empty rollout 的
-0.0110 不能归因于 Prep。

### Digital Audience

唯一有效报告确认默认 uv cache 不可写，`/tmp` 重定向能越过初始化阻塞。报告覆盖 1/1 全局
Python execution path，明确禁止推导 segmentation、eligibility 或 missing-data policy。writer
使用该 runtime 方法，并得到 0.9042。旧版 AUD-005 单行 finding 没有再次出现。

### SSE Northbound

Prep 在定向检索后 `skip`：三个问题都可用题内短文本和 manifest 普通检索完成，不需要
concordance 脚本或三行 TSV。得分与 Base 同为 0.6667。

### PDE Grading

Prep 找到 public prompt 的 `education_info` 路径与内嵌 `input/TASK_PROMPT.md` 的
`education` 路径不一致，但把 coverage 推断追加在 `task_prompt` 精确引用中，evidence gate
拒绝。writer 用工作目录即可解决该路径问题；最终 +0.0282 属于 empty rollout 差异。

### CRF SDTM 4

Fresh Prep 没有在 300 秒内完成，fail open。最终 writer 没有收到候选字段表、页码 roster 或
resolver。-0.0406 是本轮最大的负差，但没有 Prep exposure，不能作为 Prep harm。

### FluSight

Prep 生成了一个有价值的 WIS 候选：实现 95% interval WIS、自测 5 个 case，并默认排除 US。
但它把实际 source path 写成错误大小写 `input/TASK_INSTRUCTIONS.md`，source validation 丢弃
整个 bundle。最终 writer 没有收到该工具，+0.0435 仍是 empty rollout 差异。该例说明当前
正向能力的瓶颈之一是精确 locator 和时限内交付，而不是 artifact 数量上限。

## Artifact 结论

v13 六题有 7 个 artifact，其中包含 candidate-output checker、候选 roster 和普通 grep
包装器；v16 最终交付 0 个。这个变化没有删除已证明有效的能力类型：按 key 的 resolver、精确
metric 和参数化 runtime probe 仍允许。它只要求 artifact 无法由短报告替代、采用 pull 接口、
不读取 writer output，并在交付前通过 locator、大小、suffix 和内容检查。

本轮没有 artifact 通过，说明过滤强度已经足够，但 artifact precision 还不能从六题估计。
FluSight WIS 是应提高交付成功率的候选；BPMN scenario lookup 不是。下一步应提高 exact
locator hygiene 和高价值能力的准时完成率，不应重新放宽 candidate roster 或 output checker。

## 决策

无需重跑 Base：已有 Base 与最终 Prep 是同日、同 endpoint、同模型、同任务和同 writer 配置，
足以提供六题 canary 对照。当前证据不支持运行 105 题：`+0.0096` 无法与噪声区分，只有一个
有效报告，Fresh Prep 仍消耗 307K tokens。Prep 保持默认关闭，只保留窄机制实验。

## 文件

- `analysis/scores.csv`：六题配对分数。
- `analysis/summary.json`：均值、配对差、harm 和运行统计。
- `raw/base/`：Base 的 `run.json` 与 `eval_result.json`。
- `raw/final/`：最终 writer run、归档 Prep、主 transcript、trajectory 和初始 API request。
- `raw/fresh_prep/`：Fresh Prep meta 与 subagent transcript，用于审计成本和 rejection。

pgl 最终原件根目录：
`/home/ubuntu/ale/agents-last-exam/.logs/ale/prep_bundle_six_v16_final/`。
