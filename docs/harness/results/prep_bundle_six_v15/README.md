# Prep v15 六题 canary

本目录保存 2026-07-20 的六题 Prep canary 原件。Base 和 Prep 使用同一模型
`openai/gpt-5.6-sol`、同一 API endpoint、同一任务版本、同一 writer 配置。两臂顺序运行，
每臂 `concurrency=8`，实际六题同时运行。Base 位于 pgl 的
`.logs/ale/prep_bundle_six_v14_base`，Prep 位于 `.logs/ale/prep_bundle_six_v15`。

## 结果

| 题目 | Base | Prep v15 | 差值 | Prep 状态 |
|---|---:|---:|---:|---|
| BPMN Supply | 0.8505 | 0.9324 | +0.0819 | completed，cache |
| Digital Audience | 0.8667 | 0.9042 | +0.0375 | empty，cache |
| SSE Northbound | 0.6667 | 0.6667 | 0.0000 | completed，fresh |
| PDE Grading | 0.6316 | 0.6650 | +0.0333 | empty，fresh gate reject |
| CRF SDTM 4 | 0.6746 | 0.6722 | -0.0024 | completed，fresh |
| FluSight | 0.7034 | 0.7616 | +0.0582 | empty，fresh gate reject |
| **均值** | **0.7322** | **0.7670** | **+0.0348** | n=6 |

全六题差值的样本标准差为 0.0328，标准误为 0.0134，配对 `t=2.60`，harm rate 为
1/6。该统计不能单独证明 Prep 有效。三份 empty Prep 的平均差值是 +0.0430；它们没有向
writer 提供报告，因此这部分上升来自 writer rollout。三份有效报告的平均差值是 +0.0265，
由 BPMN 一题的 +0.0819 驱动；SSE 持平，CRF 为 -0.0024。

## Prep 产物

- BPMN：报告一个 task-local 冲突。原 process ID 是
  `monthlyProductionScheduling_original`，题面同时要求保留原 ID、使用 modified key，并让
  两个 definition 共存。报告不提供 output checker，不替 writer 选择复制或改名方案。
- SSE：报告 same-LEI 账户和集中填报杠杆资金字段之间的 join，并附 1,007 字节静态 TSV。
  writer 读取报告并复核 TSV，最终分数持平。
- CRF：指出 `supp_define.xml` 实际声明 ADaM-IG 1.1，真实 `IG.SUPPAE` 和
  `VL.SUPPAE.QVAL` 位于 `sdtm_define.xml`。writer 复核两个 XML 后使用该 provenance 分工，
  得分与 Base 基本相同。
- Digital：`NO_TASK_SPECIFIC_PREP`。没有再次交付 AUD-005 缺字段候选策略。
- PDE：研究发现绝对路径冲突，但 `task_basis` 未通过精确引用 gate，报告被丢弃。
- FluSight：研究得到缺失值 receipt，但 `recheck` 超过 500 字符，deliverable 被丢弃。

三份有效报告均被 writer 读取。v15 没有 candidate-output linter，也没有可执行
`input_index` 附件；唯一附件是 SSE 的静态 TSV。四次 fresh Prep 共消耗 383,882 input
tokens、1,700 秒和 27 次工具调用。BPMN 和 Digital 命中同指纹 cache，当前 run 的 meta
不记录它们原始研究成本。

## 解释限制

BPMN 刷新本机历史最高分，但报告的直接作用不能从一次 rollout 中分离。writer 最终仍选择
修改 process key，没有采用报告列出的复制方案。v15 writer 也在没有 Prep checker 的情况下
主动删除两个无上游 producer 的输入字段，说明 v14 中相同删除不能完全归因于 Prep checker。
可以确认的是，candidate checker 与 writer 自己的自检重复，没有提供独立能力。

本 canary 支持把 v15 扩到 26 题做泛化测试，因为 harm rate 降低且未观察到旧版附件副作用；
它不支持默认开启 Prep，也不支持跳过更大样本直接跑 105 题。

## 文件

- `paired_scores.csv`：同 endpoint 配对分数和 Prep 状态。
- `analysis/`：`analyze_factorial.py` 生成的分数、行为和 Prep 采用表。
- `raw/prep/`：六题 Prep 的 `run.json`、`eval_result.json`、`task_prep.md`、meta 和附件。
- `raw/base/`：配对 Base 的 `run.json` 和 `eval_result.json`。
