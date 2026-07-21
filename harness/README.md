# harness/

harness 的实现与运行控制面。面向人的最新进展入口是
`docs/harness/README.md`；被证伪的历史做法和报告保存在
`docs/archive/harness-general-prep-2026-07/`。

两份权威文档,其余都从属于它们:

| 文件 | 是什么 |
|------|--------|
| `COGNITION.md` | 实现必须遵守的当前认知、职责和红线。 |
| `run/README.md` | 运行和 API 的权威。怎么跑、三个 API 端点怎么成对配、两条运行硬教训、哪些历史文件被删了及原因。 |

## 目录

- `skills/` — 历史 writer 方法库，代码兼容性保留，但 v2 无正向总体信号，已从默认实验轴隐藏。
  - `deliverable-contract/` — 检查公开材料中可观测的 artifact 契约；区分 checked / failed / unverifiable，不能用 schema PASS 代替内容或 outcome 正确。
  - `evidence-audit/` — 多源判断任务的证据追踪；只覆盖题目要求的单元，每个结论锚定对应 primary evidence。
- `run/` — 运行控制面。改 `settings.yaml` 一个文件,跑 `launch.py`,用 `summarize.py` 看结果。实验级超参数集中在 settings。
- `patches/` — 对 agent deployer 的实针对性修复(非提示类,保留)。

## 一句话机制

task-specific prep-agent 先研究本地可锚定的新信息；Verifier 在 main agent 前证明 source、
预检 Checker 并冻结脚本，main agent 完成后由隔离 Executor 检查只读 snapshot。skills 不参与默认实验轴。另加一条常驻不变量
(`run/invariant.txt`)挡作弊。on/off 必须同预算同环境重复运行，具体配置以
`run/README.md` 为准。
