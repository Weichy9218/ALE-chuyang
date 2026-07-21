# Harness 历史归档

`2026-07-20/` 保存本轮整理前位于 `docs/harness/` 顶层的旧分析、smoke、canary、阶段性结果、任务清单、CSV 和 HTML。文件没有删除。当前结论和路径从 [上级 README](../README.md) 进入。

`2026-07-21/` 保存文档收敛前的快照：`PREP-pre-convergence.md` 和
`VERIFIER-pre-convergence.md` 是含全部版本叙事（v17 复盘、v18 实测、v19/v20 与 v14-v16
逐版改动）的旧版设计文档；`FABLE-changelog-v15-v16.md` 是 FABLE 还是增量改动日志时的
两轮记录（预提交自检、边界修正、信号率、self_check、合同对账的完整动机/实现/决策/验证）。
收敛后的现行文档只描述当前设计，版本叙事归 [EVOLUTION.md](../EVOLUTION.md)。

## 归档原则

- 原始 run 目录和对应分析保留原名，便于从旧记录定位。
- `partial`、`no_ct` 和 `trajectory` 标为派生结果，不计为新实验。
- 历史任务清单留在 archive，相关 `harness/run/settings_*.yaml` 已改为引用新路径。
- 最新 v10 机器结果位于 [results/latest](../results/latest/)，没有在 archive 重复保存。
- 两个完整案例位于 [results/examples](../results/examples/)，用于当前 Prep 和 Verifier 文档引用。

## 运行目录

| 目录 | 类型 | 用途 |
|---|---|---|
| `prep_v8_verifier_v6_canary` | 10 题 canary | 验证 Prep finding 交付、source gate 和一次 repair |
| `prep_v8_verifier_v6_canary_no_ct` | 派生统计 | 排除 CT reference mixing 后复算 9 题 |
| `task_prep_skills_v2` | 阶段性全量 | 评估两个 writer-side skills 与 Prep v5 |
| `task_prep_skills_v2_partial` | 中间快照 | 终版完成前的部分结果 |
| `task_prep_v1_behavior` | 派生行为表 | 复算时长、回合、报告读取和 skill 触发 |
| `task_prep_v9_outcome_canary` | 3 题 canary | 检查 public backtest 与 outcome heuristic 边界 |
| `task_prep_v10_variant_canary` | 单题 canary | 验证 exact submitted-ALT 规则 |
| `verifier_compare` | 25 题审计 | Prep v7、Verifier v4，repair 为 0 |
| `verifier_smoke` | 5 题 smoke | 找 source false positive 和可验证边界 |
| `verifier_trajectory` | 派生行为表 | 对 `verifier_compare` 的 finding 和 writer 轨迹复算 |
| `verifier_v7_quote_canary` | 单题 canary | 验证多段 source quote 定位 |
| `verifier_v8_quote_canary` | 单题 canary | 验证 requirement/check/expected 的 source entailment |
| `verifier_v9_quote_canary` | 单题 canary | 验证 artifact ellipsis 分片 |

## 旧分析

以下文档保留当时结论，不再作为当前入口：

- `README.md`、`ARCHITECTURE.md`、`VERIFIER.md`、`EXPERIMENTS.md`：整理前的顶层文档。
- `prep_v10_verifier_v10_full_analysis.md`：v10 全量的长报告，是当前五份主题文档的主要事实来源。
- `prep_v8_verifier_v6_canary_analysis.md`：10 题 canary 与 7 次 repair 的逐项分析。
- `prep_verifier_protocol_iteration_analysis.md`：Prep v8 至 v10、Verifier v6 至 v10 的窄复验记录。
- `prep_verifier_trajectory_analysis.md`：Prep v7 lexical filter 和 Verifier v4 finding 的行为审计。
- `task_prep_skills_v2_analysis.md` 与 `task_prep_skills_v2_partial_analysis.md`：skills v2 终版和中间快照。
- `task_prep_v1_behavior_analysis.md`、`task_prep_v1_report.html`、`task_prep_v1_scores.csv`：v1 行为、网页和逐题分数。
- `verifier_compare_analysis.md` 与 `verifier_smoke_analysis.md`：旧 full 和 smoke 的人工审计。

旧文档移动了两级目录，文内部分相对链接仍按原顶层位置书写。当前文档中的链接已经改用新路径；需要核对旧文档时，以本清单和 [结果索引](../results/README.md) 为准。

## 任务清单

`research_batch_v2_ale.txt`、`research_batch_v2_gpt.txt` 以及所有 `*_canary_tasks.txt`、`verifier_smoke_tasks.txt` 都保存在 `2026-07-20/`。当前 26 题清单位于 [results/latest/tasks.txt](../results/latest/tasks.txt)。
