# Prep v13 Bundle 六题测试

本目录保存 `task-prep-v13` 的首次六题 bundle 测试。2026-07-20 只启动
`ale_claw_prep`，6 题并发 6，6/6 completed。模型为 `openai/gpt-5.6-sol`，medium
thinking，writer skills 和 verifier 关闭。

主报告见 [report.html](report.html)。设计结论见 [../../PREP.md](../../PREP.md)。

## 比较口径

本轮没有同时重跑 Base。表中的 Base 来自此前同任务的单次运行。任务、模型和 writer 配置
一致，但运行时间、并发和 rollout 不同。因此分数比较是历史对照，不是严格的同期配对因果
实验。

| Task | Base | 当前 Prep | Delta |
|---|---:|---:|---:|
| BPMN supply disruption | 0.8462 | 0.8052 | -0.0410 |
| Digital audience segmentation | 0.7620 | 0.9042 | +0.1422 |
| SSE reporting | 0.6667 | 0.6667 | 0 |
| PDE grading | 0.7050 | 0.6496 | -0.0553 |
| CRF SDTM mapping | 0.6029 | 0.6459 | +0.0430 |
| FluSight forecast | 0.7279 | 0.7549 | +0.0270 |
| **Mean** | **0.7184** | **0.7377** | **+0.0193** |

六题对历史 Base 为 3 正、1 平、2 负，`t=0.665`。单次样本没有证明总体 uplift。

## 机制结果

- 6/6 writer 读取报告。按 exposure 定义，六题 Prep 都进入了 writer 上下文。
- BPMN、PDE、CRF 三题执行附件代码，共 9 次。报告读取和能力复用分别统计。
- 共生成 6 份报告、7 个 artifact，0 次 skip。
- Prep 使用 374050 input tokens、23715 output tokens 和 51 次工具调用。
- BPMN 暴露反向引导：writer 删除两个 consumer 的 `in_supplier_risk_level`，让局部
  checker 从 2 个 finding 变成 0，而不是修复 producer 路径。
- Digital 和 CRF 表明 `do_not_infer` 不能机械阻止 writer 从字段缺失或 candidate index
  推出 output policy。
- SSE 和 PDE 的 Prep 内容容易由 writer 独立完成，说明 value/skip gate 仍偏松。

## 文件

| 文件 | 内容 |
|---|---|
| [scores.csv](scores.csv) | Base、当前 Prep 分数与采用统计 |
| [summary.json](summary.json) | 实验级分数、成本和限制 |
| [behavior.csv](behavior.csv) | analyzer 生成的 writer 与 Prep 运行指标 |
| [prep_findings.csv](prep_findings.csv) | 归一化 focus、deliverable、source 和边界 |
| [prep_writer.csv](prep_writer.csv) | 报告读取位置、source 回查和 artifact 统计 |
| [trajectory_calls.tsv](trajectory_calls.tsv) | 六题 writer 的 127 次原始工具调用索引 |
| [trajectory_evidence.csv](trajectory_evidence.csv) | 人工复核的关键采用链 |
| [run_manifest.csv](run_manifest.csv) | pgl run、writer transcript 和 Prep transcript 原路径 |
| `tasks/<task>/task_prompt.md` | Prep 收到的完整公开题面 |
| `tasks/<task>/task_prep.md` | pgl 归档的原始报告 |
| `tasks/<task>/task_prep_meta.json` | 协议、token、时长、hash 和 artifact manifest |
| `tasks/<task>/artifacts/` | Prep 生成的原始代码或索引 |
| `tasks/<task>/run.json` | writer 得分、usage 和运行状态 |

完整 writer transcript 保留在 pgl，不复制进文档仓库。精确位置见 `run_manifest.csv`。
