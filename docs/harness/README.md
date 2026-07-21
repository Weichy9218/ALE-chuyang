# ALE Harness 文档入口

当前代码协议为 `task-prep-v20` 和 `public-verifier-v16`。Prep 默认开启，Verifier 和现有两个
writer-side skills 默认关闭。Prep 在 writer 之前、在同一沙箱里跑通题目的运行时，从题面和
`input/` 编译交付物合同清单（机械条目多时同时交付一个可运行的 self-check 脚本，writer 对
自己的草稿反复运行），并补上题面缺失的精确事实；它不检查 writer 的候选 output。Verifier
不读取 Prep，在 Writer 前独立冻结 source-backed tests：quote 唯一时行号错误由 harness 机械
修正，定位失败有一轮机械修复，来源歧义的检查以 advisory 身份运行而不是弃跑。Writer 可以在
提交前用 `verify` 工具对当前草稿运行完整冻结测试包（默认 2 次），DONE 后 Executor 照常在
隔离环境中运行并驱动有上限的复核。prep_verifier 臂里，harness 机械对账两份独立合同阅读引用
的公开文件，分歧注入 writer 初始 prompt。两个 agent 的定位、通信方式和痛点见
[FABLE.md](FABLE.md)，版本演化见 [EVOLUTION.md](EVOLUTION.md)。

## 当前文档

- [系统设计](ARCHITECTURE.md)：ALE 生命周期、ALE-Claw、Prep、Skills、Verifier、评测器之间的职责和数据流。
- [Prep 设计](PREP.md)：`task_prep.py` 的实现、版本变化、报告注入和具体轨迹。
- [Verifier 设计](VERIFIER.md)：`verifier.py` 的三维模型（execution/observation/authority）、四类顶层输出、冻结测试包、隔离执行和 `needs_review` 驱动的 Writer 复核。
- [版本演化](EVOLUTION.md)：Prep 与 Verifier 历史问题、协议修改和验证记录。
- [结果与历史对照](results/README.md)：最新统计、协议级历史表、重复题目对照和案例目录。
- [历史归档](archive/README.md)：旧分析、smoke、canary、阶段性结果和任务清单的迁移表。

## 当前结论

Prep 侧最新证据是 v18 六题配对（[results/prep_v18_six](results/prep_v18_six/)）：生成率
6/6（v17 为 0/6），但配对差 `-0.0562`（n=6），三题交付的 artifact 在 writer 轨迹里零调用，
SEC 的 +0.26 经轨迹核对与 prep 无关，Agora 的 -0.34 是清单点名维度挤掉未点名维度的定向
优化。结论：产出问题已解决，消费问题成为主矛盾。v20 据此把合同自检升为一等 `self_check`
字段（拉取式、给确切命令）、在清单措辞里固化反过拟合边界，并保留结构化 contract 做机械
对账。历史脉络见 [EVOLUTION.md](EVOLUTION.md)。下面的 25 题四臂统计是 v10 历史结果。

Verifier 侧，当前设计沿三条硬约束收敛（详见 [VERIFIER.md](VERIFIER.md)）：反馈要无损到达
（四类输出全给 Writer）、要到得够早（`verify` 工具，DONE 前拉取）、测量要真的发生（重定位
+ 机械修复轮 + ambiguous 以 advisory 运行）。历史量级参考：反馈只在 DONE 后推送的协议下
52 run 0 repair，344 条 check 有 156 条死在来源门上未运行。得分收益未测量，Verifier 维持
默认关闭，等待六题机制 canary（v13 六题门的"无效"结论已撤回，理由见
[EVOLUTION.md](EVOLUTION.md)）。

2026-07-20 的 v10 全量覆盖 26 题和四个 arm，共 104 个 unit。PE screening memo 的四个 evaluator 调用都因不可用的 `gpt-5-mini` 返回 404，因此主表使用其余 25 个完整配对任务。

| Arm | 25 题均分 | 相对 base | 解释 |
|---|---:|---:|---|
| base | 0.60547 | 0 | 当前同轮基线 |
| prep | 0.59570 | -0.00977 | t=-0.54，没有总体正信号 |
| verifier | 0.61556 | +0.01010 | 0 repair，差值来自独立 writer rollout |
| prep + verifier | 0.66943 | +0.06396 | 主要受 CT 与 SSE 两题影响 |

去掉 CT 与 SSE 后，combined 相对 base 为 `+0.01155`，verifier 主效应为 `+0.00208`。这些值没有证明稳定提升。

现有 skills v2 的 25 题同协议结果为 skills 相对 base `-0.0161`，其中 3 题提高、15 题不变、7 题下降。50 个 skill-enabled unit 都完成了 skill 加载。结果说明当前 `deliverable-contract` 和 `evidence-audit` 不适合默认加载；它不支持“所有 skill 机制都无用”的结论。

## 目录规则

`docs/harness/` 顶层只放当前文档。最新机器结果和可复核案例进入 `results/`。旧 run、旧分析、任务清单和中间网页进入 `archive/2026-07-20/`。历史文件保留原名，避免丢失实验依据。

当前 26 题清单位于 [results/latest/tasks.txt](results/latest/tasks.txt)。运行配置已经改用该路径；历史配置改为引用 archive 中对应的任务清单。
