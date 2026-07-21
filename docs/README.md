# docs 索引与项目进展

ALE-Test 在 agents-last-exam(ALE)基准上研究 agent harness:对比两套 harness(pi 与 gpt_claw/ale_claw)跑同一模型,目标是 harness 与模型的协同进化——harness 产出高质量可学习轨迹,轨迹经筛选喂后训练,模型把能力内化。

本文件是 docs 目录的索引。当前活跃的工作线只有一条：ale_claw 的 Prep 与 Verifier
（代码协议 `task-prep-v20`、`public-verifier-v16`），入口是
[harness/README.md](harness/README.md)。其余文档是历史背景，按主题列在下面；
已被当前设计取代的分析和原型统一放在 [archive/](archive/)。

## 当前状态（2026-07-21）

- Prep 默认开启：跑通运行时、编译合同清单（含可运行 self-check 脚本）、补精确先验。
- Verifier 默认关闭，实验臂开启：solve 前冻结公开测试，writer 可在 DONE 前用 `verify`
  工具预运行，DONE 后照常复核。
- prep_verifier 臂新增机械合同对账：比较两份独立阅读引用的公开文件，分歧注入 writer。
- 设计、证据和版本演化见 [harness/](harness/)：README、ARCHITECTURE、PREP、VERIFIER、
  EVOLUTION、FABLE（2026-07-21 两轮优化的完整记录）、results/。

## 逐题分析（26 题）与 harness 复盘：不在本仓库

`docs/task_analysis/`（26 页逐题分析加索引）和 `docs/harness_pitfalls.html`（prep 与 verifier
的实验复盘）不进本仓库，因为它们包含从隐藏 `reference/` 复原出来的参考取值、评分公式与容差、
答案键标签，公开会污染 ALE 这批题目。需要时向仓库所有者索取离线 zip（`dist/` 下打包，
单文件 HTML，无外链、无 JS，本地双击即可看）。

两份材料记录的是同一批实验的两侧：逐题分析给出 base 臂在每道题上的得分、失分位置和复算过程；
harness 复盘给出 prep 与 verifier 各版本的设计、实验统计和被推翻的结论。本仓库内可公开的
对应证据是 [harness/results/](harness/results/) 下的分数表与审计 CSV。

## 历史背景（按读的顺序）

1. [archive/analysis.md](archive/analysis.md) — 项目主线起点:pi 架构、ALE 任务形态、两条典型轨迹、harness 该补什么。
2. [archive/next_step.md](archive/next_step.md) — 当时的下一步设想(pi harness 与规则库);后被 ale_claw prep/verifier 线取代。
3. [pi-agent.md](pi-agent.md) — pi 的三个循环钩子和 extension 系统。
4. [comp_pi_aleclaw.md](comp_pi_aleclaw.md) — pi 与 ale_claw 两套 harness 的架构对比。
5. [archive/progress_2026-07-13.md](archive/progress_2026-07-13.md) — 2026-07-13 的阶段汇报快照。

## 系统审计与数据方案（2026-07 中旬交付）

- [system_issues.md](system_issues.md) — 全链路系统问题清单,56 条,按链路分组。
- [remediation_status.md](remediation_status.md) — 上述问题的修复状态。
- [archive/harness_design.md](archive/harness_design.md) — 三类 pi 干预原型的设计与消融方案;对应代码在 ALE-Test 仓库,本仓库未包含,已被 ale_claw prep/verifier 线取代。
- [data_construction.md](data_construction.md) — 从 pi 轨迹抽 SFT / 偏好数据的 schema、筛选规则。

## 运行环境与批次

- [harness/results/latest/tasks.txt](harness/results/latest/tasks.txt) — 当前 26 题研究批次。
- [archive/harness-general-prep-2026-07/env.md](archive/harness-general-prep-2026-07/env.md) — pgl 环境历史配置记录。
- [archive/ALE-COMPUTER-USE-SOFTWARE-INVENTORY.md](archive/ALE-COMPUTER-USE-SOFTWARE-INVENTORY.md) — ALE 各题所需软件清单。

## 报告与选题(HTML,可直接看)

- [harness/archive/2026-07-20/task_prep_v1_report.html](harness/archive/2026-07-20/task_prep_v1_report.html) — task-specific prep v1 的 26 题全量报告(历史)。
- [gpt_analysis/index.html](gpt_analysis/index.html) — pi 与 gpt_claw 25 题对跑的完整结论。
- [gpt_analysis/task_selection.html](gpt_analysis/task_selection.html) — 165 题盘点、77 题合格池、36 题 P1 研究批次。
- [task_analysis/](task_analysis/) — 逐题轨迹分析页。
- [archive/qwen390b_analysis/ALE_qwen_run.md](archive/qwen390b_analysis/ALE_qwen_run.md) — Qwen3.5-397B 全量 99 题逐题结果。

## 网络安全子领域

- [cybersecurity_solve.md](cybersecurity_solve.md) — 4 道 cybersecurity 题在纯 Linux 上的手工解题过程与产物。

## 面试准备(与项目主线无关,可选保留)

- [interview_prep/](interview_prep/) — 面试准备材料,交接可忽略。

## 目录约定

- `../harness/` — 运行控制面(run/launch.py、settings、presets、analyze_factorial、summarize)、skills 历史库与 COGNITION 红线。
- `../ale_run/agents/ale_claw/` — writer、prep、verifier、预提交自检与合同对账的实现。
- `../data/` — 训练数据抽取脚本。
- `../llm/` — 模型网关客户端封装。
- `../pi/` — pi 编码 agent 上游源码(第三方,不入版本库)。
- `../.env` — 凭据,不入版本库。
