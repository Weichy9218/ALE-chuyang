# docs 索引与项目进展

ALE-Test 在 agents-last-exam(ALE)基准上研究 agent harness:对比两套 harness(pi 与 gpt_claw/ale_claw)跑同一模型,目标是 harness 与模型的协同进化——harness 产出高质量可学习轨迹,轨迹经筛选喂后训练,模型把能力内化。

本文件是 docs 目录的索引,兼项目进展脉络。按"读的顺序"和"主题"两种方式组织。

## 一分钟进展

到目前为止做完了三段工作:

1. **摸清 harness 与基准**。用 pi 跑 Qwen3.5-397B 全量 99 题(均分约 0.29),逐轨迹分析出 pi 的架构特点(薄 harness、无步数护栏)和 ALE 的失败构成(超时、跑完零分两大类)。
2. **两套 harness 对跑**。用 gpt-5.6-sol 让 pi 和 gpt_claw 在 25 题上对跑,总分打平(pi 0.404 / gpt_claw 0.399),确认无界面代码题上分数由题目决定、不由 harness 决定;并从 165 题里筛出可跑的研究批次。
3. **系统审计 + harness 原型 + 数据方案**(本轮)。全链路审计出 56 条问题,给出三类只给事实不给答案的 pi 干预原型(已冒烟验证),以及从轨迹抽可验证训练数据的脚本和方案。

下一步是把 harness 干预在真实题上做消融(基线对加钩子),验证提分且不靠泄露,再走向让模型自己看轨迹改 harness 的闭环。

## 按读的顺序(新接手先读这几篇)

1. [analysis.md](analysis.md) — 项目主线:pi 架构、ALE 任务形态、两条典型轨迹(成功的 Ising、失控的 CFR)、harness 该补什么。
2. [next_step.md](next_step.md) — 下一步:给 pi 搭不泄露的 harness,六条规则库,以及让模型自改 harness 的远景。
3. [pi-agent.md](pi-agent.md) — 重点:pi 的三个循环钩子(shouldStopAfterTurn / beforeToolCall / afterToolCall)和 extension 系统,是搭 harness 的抓手。
4. [comp_pi_aleclaw.md](comp_pi_aleclaw.md) — pi 与 ale_claw 两套 harness 的架构对比。

## 本轮交付(系统审计 + harness + 数据)

- [system_issues.md](system_issues.md) — 全链路系统问题清单,56 条,按链路分组,每条含复现、根因、影响、修复。
- [remediation_status.md](remediation_status.md) — 上述问题的修复状态:已修并验证 / 待轮换凭据 / 待与同学协调改 zmh。
- [harness_design.md](harness_design.md) — 三类 pi 干预(预算止损、动作前守卫、事实反射)的设计、消融方案、不泄露论证。对应代码在 `../harness/`。
- [data_construction.md](data_construction.md) — 从 pi 轨迹抽 SFT / 偏好数据的 schema、筛选规则、新题扩造路线。对应脚本在 `../data/`。

## 运行环境与批次

- [new_run/env.md](new_run/env.md) — pgl 远程机的 ALE 环境配置与使用(Linux CLI 优先)。
- [new_run/research_batch_wcy.txt](new_run/research_batch_wcy.txt) — chuyang 的 26 题批次(headless Docker 可跑)。
- [new_run/setup_docker.sh](new_run/setup_docker.sh) — 远程机装 Docker 的一键脚本。
- [ALE-COMPUTER-USE-SOFTWARE-INVENTORY.md](ALE-COMPUTER-USE-SOFTWARE-INVENTORY.md) — ALE 各题所需软件清单(用于判断哪些题需 GUI)。

## 报告与选题(HTML,可直接看)

- [gpt_analysis/index.html](gpt_analysis/index.html) — pi 与 gpt_claw 25 题对跑的完整结论、原始数据、取数脚本。
- [gpt_analysis/task_selection.html](gpt_analysis/task_selection.html) — 165 题盘点、77 题合格池、36 题 P1 研究批次与分数预判。
- [qwen390b_analysis/ALE_qwen_run.md](qwen390b_analysis/ALE_qwen_run.md) — Qwen3.5-397B 全量 99 题逐题结果与归因。
- [qwen390b_analysis/ALE_report.html](qwen390b_analysis/ALE_report.html) — 同一批数据的可视化报告。

## 网络安全子领域

- [cybersecurity.md](cybersecurity.md) — 4 道 cybersecurity 题为何在本地跑不了官方评测(需 Windows 桌面)。
- [cybersecurity_solve.md](cybersecurity_solve.md) — 这 4 题在纯 Linux 上的手工解题过程与产物。

## 面试准备(与项目主线无关,可选保留)

- [interview_prep/](interview_prep/) — 一批面试准备材料。不是项目工作进展,收在这里备查;若做工作交接可忽略。

## 目录约定

- `../harness/` — pi 干预 extension 原型、冒烟测试、假零分补丁。
- `../data/` — 训练数据抽取脚本;`data/samples/` 是产出的样本(含 ALE 题面轨迹,不入版本库)。
- `../llm/` — 模型网关客户端封装。
- `../pi/` — pi 编码 agent 上游源码(第三方,不入版本库)。
- `../.env` — 凭据,不入版本库。
