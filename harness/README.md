# harness/

harness 优化的单一事实源。只放当前成立的认知、要注入 agent 的内容、以及运行方式。被证伪的历史做法(镜像式提醒、无差别方法后缀、任务专属 linter)已删除,不在此保留。

两份权威文档,其余都从属于它们:

| 文件 | 是什么 |
|------|--------|
| `COGNITION.md` | **先读这个**。当前认知(哪些干预被证伪、噪声底有多高)、两个 agent 的渐进式披露机制、设计、红线。 |
| `run/README.md` | 运行和 API 的权威。怎么跑、三个 API 端点怎么成对配、两条运行硬教训、哪些历史文件被删了及原因。 |

## 目录

- `skills/` — 要注入的技能库,纯 .md。每个 SKILL.md 的 frontmatter 只有 name + description(常驻索引,约 20 token),正文由模型判断相关后用 `read` 自取(渐进式披露),不匹配就零成本。载荷只能是通用方法,不含任务专属规则、评测逻辑或参考答案。两个 skill 的分工是一个清晰二分:**能不能跑一个检查?**
  - `deliverable-contract/` — 能跑检查的产出题。抽取任务自带的验收清单,写并跑一个校验器,不全绿不算完。
  - `evidence-audit/` — 只判断、没有可运行产出的题。动笔前枚举所有比对单元逐格走,每条发现锚定原文引用。
- `run/` — 运行控制面。改 `settings.yaml` 一个文件,跑 `launch.py`,用 `summarize.py` 看结果。**所有超参数(model、max_turns、并行度、cleanup_mode、API 端点、prep 的 token 上限)都集中在 settings**,不散落代码。
- `patches/` — 对 agent deployer 的实针对性修复(非提示类,保留)。

## 一句话机制

skills 是一批共用的 .md 文件,system prompt 里只放一份短索引,模型 read 对应文件才展开正文。另加一条常驻不变量(`run/invariant.txt`)挡作弊。不给 agent 设 turn / 时间上限(不等预算会凭空造出假效应),on / off 必须同预算同环境重跑,否则结论作废。跑在 pgl,清代理,具体并行度和 API 配置以 `run/README.md` 为准。
