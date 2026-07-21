# 实验结果与历史对照

本目录集中保存当前机器结果、实验级历史表、重复题目历史和两个完整案例。旧 smoke、canary 和阶段性全量的原文件保存在 [archive/2026-07-20](../archive/2026-07-20/)。

最新版 Prep 六题测试保存在 [prep_bundle_six_v16](prep_bundle_six_v16/)，26 题机制 canary
保存在 [prep_v15_wcy26](prep_v15_wcy26/)。v13 的六题 HTML 轨迹分析仍保存在
[prep_bundle_six/report.html](prep_bundle_six/report.html)，用于查看旧 artifact 的具体副作用。

## 统计口径

四臂 verifier 实验使用 `base / prep / verifier / prep_verifier`。四臂 skills 实验使用 `base / prep / skills / skills_prep`。

以下限制适用于所有均分：

1. 每个 task/arm 只有一次 writer rollout。均分和配对 t 值用于描述本轮信噪比，不能替代 `k>=3` 的重复实验。
2. `max_repairs=0` 时，verifier 在 writer 完成后审计，不能改变 artifact。verifier arm 与 base 的分数差不是 verifier 的因果效果。
3. 旧 `verifier_compare` 按 arm 使用不同 endpoint，适合分析 verifier finding，不适合估计 arm 效应。
4. v8/v6 canary 的 CT combined 将公开 reference 混入重建。该 1.0 是无效干预；排除 CT 后再解释均值。
5. `task_prep_v1` 没有同日重跑 base。它只能提供行为和机制证据。

完整实验索引在 [run_summary.csv](run_summary.csv)，重复题目分数在 [task_history.csv](task_history.csv)。

## 最新全量

实验日期为 2026-07-20。模型和 endpoint 为同一 `openai/gpt-5.6-sol` endpoint。配置见 [`harness/run/settings_verifier_v10_full.yaml`](../../../harness/run/settings_verifier_v10_full.yaml)。任务清单有 26 题，四臂共 104 个 unit。100 个 unit completed；PE screening memo 四臂都在 evaluator 请求 `gpt-5-mini` 时得到 404，不记为 0。

| Arm | runs | completed / failed | 25 题均分 | 相对 base | 正 / 平 / 负 |
|---|---:|---:|---:|---:|---:|
| base | 26 | 25 / 1 | 0.60547 | 0 | 0 / 25 / 0 |
| prep | 26 | 25 / 1 | 0.59570 | -0.00977 | 4 / 15 / 6 |
| verifier | 26 | 25 / 1 | 0.61556 | +0.01010 | 4 / 14 / 7 |
| prep + verifier | 26 | 25 / 1 | 0.66943 | +0.06396 | 8 / 14 / 3 |

2x2 析因估计为 prep `+0.02205`，t=`0.96`；verifier `+0.04191`，t=`1.45`；交互 `+0.06364`，t=`1.43`。三个估计都没有超过本轮方差。

| 数据集 | n | prep main | verifier main | interaction | combined-base |
|---|---:|---:|---:|---:|---:|
| 全部有效题 | 25 | +0.02205 | +0.04191 | +0.06364 | +0.06396 |
| 排除 CT | 24 | +0.00213 | +0.02283 | +0.02462 | +0.02496 |
| 排除 CT 与 SSE | 23 | +0.00947 | +0.00208 | +0.01120 | +0.01155 |

CT 的四臂为 `0 / 0 / 0 / 1`，SSE 为 `0.667 / 0.333 / 1 / 1`。这两题解释了 combined 均值的大部分变化。v10 CT combined 是独立 writer 找到的真实 FBP，verifier 通过重跑证明交付数组与独立重建逐元素一致；由于本轮 0 repair，该成功仍不能归因于 verifier。

## Prep 运行统计

52 个 prep-on unit 全部写出 `task-prep-v10` metadata。50 个报告非空，2 个 SEC 报告为空。

| 指标 | 结果 |
|---|---:|
| fresh research / cache hit | 22 / 30 |
| fresh 平均时长 | 278.8 秒 |
| fresh 平均 input tokens | 116,206 |
| fresh 平均 LLM turns / tool calls | 7.1 / 11.0 |
| fresh raw findings / retained | 62 / 59 |
| 非空报告被 writer 读取 | 50 / 50 |
| source locator 被 writer 回查 | 108 / 138 |

SEC 的 3 条 raw finding 全部未交付。原因是两个 `local_source` 使用了 `input/validation/*.pdf` 和 `input/filings/*.pdf`；当前 source validation 要求 exact path 存在，并按整份报告拒绝。该行为防止模糊来源进入 writer，也会让同一报告中的有效 runtime finding 一并丢失。

## Verifier 运行统计

52 个 verifier-on unit 都构建了 `public-verifier-v10` spec，且每题两个 arm 的 fingerprint 和 spec SHA 相同。每个 unit 调用一次 runner，共 52 次；`max_repairs=0`，没有调用 writer repair。

| 指标 | 结果 |
|---|---:|
| builder decisions | 52 verify / 0 skip / 0 error |
| criteria | 344 |
| deterministic / public_evidence / unverifiable | 290 / 52 / 2 |
| source supported / ambiguous / contradicted / missing | 196 / 145 / 2 / 1 |
| verdict pass / unverifiable / fail / error | 180 / 156 / 6 / 2 |
| overall pass / unverifiable / fail / error | 5 / 38 / 4 / 5 |
| repairs | 0 |

6 个 fail 来自 BPMN supply 的拓扑与角色缺口，以及 Legal M&A 的引文 omission。CRF1 的 0 分 artifact 和 SAP 的 0.25 artifact 仍可 overall pass，说明固定 5 至 8 条 criterion 只覆盖注册项。American 和 Moodle 的 4 个 runner 通过任务 wrapper 修改了 writer 原 output 下的运行环境文件；前后哈希将其记为 error。该结果支持把 runner 移入独立容器。

平均 builder 为 76.5 秒、27.8k input tokens；平均 runner 为 223.4 秒、95.2k input tokens。builder 有缓存，fresh builder 的实际平均约为 153.1 秒、55.5k input tokens。当前没有 repair uplift 证据，这项成本不适合默认开启。

## 历史实验

| 实验 | 协议 | 规模 | 可用结论 |
|---|---|---:|---|
| old general prep | general prep + skills | 26 题四臂 | 旧短 notes 没有稳定收益 |
| task prep v1 | task-specific prep + skills | 26 题三个新臂 | 发现 Variant、CT 和报告交付机制；base 跨日期 |
| skills v2 | prep v5 + 两个短 skills | 25 题同协议四臂 | skills `-0.0161`，50/50 成功加载 |
| verifier smoke | prep v7 + verifier v4 | 5 题四臂 | 找到 TCGA false positive，repair 默认改为 0 |
| verifier compare | prep v7 + verifier v4 | 25 题四臂 | 34 fail 中 30 条有公开证据，3 条明确误报 |
| v8/v6 canary | prep v8 + verifier v6 | 10 题四臂 | 27/27 finding 保留；7 次 repair 暴露振荡和 leakage |
| prep v9 canary | prep v9 | 3 题两臂 | FluSight 使用公开 backtest；Variant 回归仍在 |
| prep v10 canary | prep v10 | Variant 两臂 | exact submitted-ALT 修复得到 0.793 到 0.999 |
| verifier v7 至 v9 | quote protocol canary | Legal 各一臂 | 逐步修复多 excerpt、source entailment 和 ellipsis |
| v10 full | prep v10 + verifier v10 | 25 题有效四臂 | 没有总体 uplift；审计 precision 和 provenance 改善 |

`task_prep_skills_v2_partial` 是运行中快照，终版已覆盖其结论。`verifier_trajectory` 是对 `verifier_compare` 原 run 的二次行为审计。`prep_v8_verifier_v6_canary_no_ct` 是排除 CT 的派生统计。这三项不计为新的独立实验。

## 重复题目

Variant 给出了最清楚的 Prep 版本回归与修复链：

| 版本 | base | prep | 解释 |
|---|---:|---:|---|
| task prep v1 | 0.999 | 0.793 | 上游 normalized allele 覆盖 task-local submitted ALT |
| skills v2，prep v5 | 0.999 | 0.793 | 同一路径复现 |
| prep v8 canary | 0.999 | 0.793 | 删除词法过滤后仍复现 |
| prep v9 canary | 0.999 | 0.793 | 中性措辞没有阻断 alternate key |
| prep v10 canary | 0.793 | 0.999 | 明确禁止 alternate lookup key 后反转 |
| prep v10 full | 0.793 | 0.999 | 同一实现机制再次复现 |

CT 展示 verifier repair 的风险：v6 canary 首轮 SSIM 为 0.9024，repair 后 writer 将 32% public reference 混入 reconstruction，verifier 只复算阈值并判 pass。v10 增加 provenance criterion 并关闭 repair；最终 combined 的 1.0 经独立 FBP 重跑验证为真实重建。

FluSight 展示 verifier 的可验证边界。它能检查 212 行、template key、非负整数和区间顺序，无法看到提交后四周的 finalized admissions。v10 combined 的 0.7210 不能由 verifier 预先证明。

其余 BPMN、Legal、SEC、TCGA 和 Agora 的逐轮值见 [task_history.csv](task_history.csv)。

## 文件索引

`latest/` 保存当前全量的 `summary.json`、`scores.csv`、`behavior.csv`、Prep 与 Verifier 审计表，以及 26 题清单。`examples/variant-v10/` 保存 Prep 改变 writer 实现但 verifier 不参与 repair 的正例。`examples/ct-verifier-v6/` 保存 verifier 反馈改变 writer、随后产生 reference mixing 的负例。

原目录迁移如下：

| 原目录 | 当前路径 |
|---|---|
| `prep_v10_verifier_v10_full` | `results/latest` |
| `example_variant_v10_pgl` | `results/examples/variant-v10` |
| `example_ct_v6_pgl` | `results/examples/ct-verifier-v6` |
| `prep_v8_verifier_v6_canary` | `archive/2026-07-20/prep_v8_verifier_v6_canary` |
| `prep_v8_verifier_v6_canary_no_ct` | `archive/2026-07-20/prep_v8_verifier_v6_canary_no_ct` |
| `task_prep_skills_v2` 与 `task_prep_skills_v2_partial` | `archive/2026-07-20/` 下同名目录 |
| `task_prep_v1_behavior` | `archive/2026-07-20/task_prep_v1_behavior` |
| `task_prep_v9_outcome_canary` 与 `task_prep_v10_variant_canary` | `archive/2026-07-20/` 下同名目录 |
| `verifier_compare`、`verifier_smoke`、`verifier_trajectory` | `archive/2026-07-20/` 下同名目录 |
| `verifier_v7_quote_canary` 至 `verifier_v9_quote_canary` | `archive/2026-07-20/` 下同名目录 |
