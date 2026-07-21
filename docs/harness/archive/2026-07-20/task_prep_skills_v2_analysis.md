# Task Prep / Skills v2 分析报告

更新于 2026-07-19。本报告以本轮同配置、同预算、同评分端点的四臂结果为主；每个
task/arm 只有一次运行，因此效应量和方向可用于筛选机制，不能当成稳定显著性结论。

## 执行摘要

现有两个 writer-side skills 没有跨任务净收益证据，v5 task-specific prep 也没有。
在 25 道同协议完整题上，skills、prep 和 combined 均未超过 base；combined 最差，说明
两种注入不能假定可加。

| 臂 | n | 均分 | 相对 base | 配对差 SE | t | 正/平/负 |
|---|---:|---:|---:|---:|---:|---:|
| base | 25 | 0.6068 | - | - | - | - |
| skills | 25 | 0.5907 | -0.0161 | 0.0192 | -0.84 | 3 / 15 / 7 |
| prep | 25 | 0.6056 | -0.0012 | 0.0145 | -0.08 | 4 / 17 / 4 |
| skills + prep | 25 | 0.5842 | -0.0226 | 0.0132 | -1.71 | 2 / 16 / 7 |

四臂析因估计把 skills 在 prep off/on 下的差取平均，把 prep 在 skills off/on 下的差取
平均。结果仍是负向：skills 主效应 `-0.0188`（SE `0.0092`，t `-2.04`），prep 主效应
`-0.0039`（SE `0.0129`，t `-0.30`），交互项 `-0.0053`（SE `0.0270`，t `-0.20`）。
这里没有做多重比较校正，且每格 `k=1`；t 值只描述本轮信噪比，不应写成确认性显著结论。

准确决策是：**当前版本不应默认加载，也不应继续把 writer 自检称为 verifier。** 保留
窄用途方法库是合理的；若要验证产物，应使用 solve 前固定标准、solve 后隔离运行的独立
反馈闭环。

## 全部逐题分数

下表 25 题来自同一正式协议。PE 的四臂 solver 均生成了产物，但原评分模型
`gpt-5-mini` 在 solver 端点不可用；其恢复实验和原产物重评分单列在下一节，避免混入主表。

| 题目 | Base | Skills | Prep | Combined | S-B | P-B | C-B |
|---|---:|---:|---:|---:|---:|---:|---:|
| American option pricing | 1.000 | 1.000 | 1.000 | 1.000 | +0.000 | +0.000 | +0.000 |
| BPMN category governance | 0.000 | 0.000 | 0.000 | 0.000 | +0.000 | +0.000 | +0.000 |
| BPMN supply disruption | 0.825 | 0.820 | 0.841 | 0.815 | -0.006 | +0.015 | -0.010 |
| Digital marketing A/B | 1.000 | 1.000 | 1.000 | 1.000 | +0.000 | +0.000 | +0.000 |
| Audience segmentation | 0.867 | 0.725 | 0.904 | 0.904 | -0.142 | +0.037 | +0.037 |
| Financial statement reconstruction | 1.000 | 1.000 | 1.000 | 1.000 | +0.000 | +0.000 | +0.000 |
| Internal employee agent | 1.000 | 1.000 | 1.000 | 1.000 | +0.000 | +0.000 | +0.000 |
| Legal M&A consistency audit | 0.000 | 0.000 | 0.000 | 0.000 | +0.000 | +0.000 | +0.000 |
| LLM privacy audit | 0.500 | 0.500 | 0.500 | 0.500 | +0.000 | +0.000 | +0.000 |
| SEC 10-K parsing | 0.639 | 0.629 | 0.631 | 0.595 | -0.010 | -0.008 | -0.044 |
| SSE northbound trading | 0.667 | 0.333 | 0.667 | 0.667 | -0.333 | +0.000 | +0.000 |
| Numerical PDE grading | 0.565 | 0.695 | 0.713 | 0.650 | +0.130 | +0.148 | +0.085 |
| MARC remediation | 0.200 | 0.200 | 0.200 | 0.200 | +0.000 | +0.000 | +0.000 |
| Moodle gradebook | 0.950 | 0.885 | 0.950 | 0.950 | -0.065 | +0.000 | +0.000 |
| CRF SDTM mapping 1 | 0.000 | 0.000 | 0.000 | 0.000 | +0.000 | +0.000 | +0.000 |
| CRF SDTM mapping 4 | 0.612 | 0.428 | 0.467 | 0.414 | -0.184 | -0.146 | -0.199 |
| CT geometry | 0.000 | 0.000 | 0.000 | 0.000 | +0.000 | +0.000 | +0.000 |
| Epidemiology forecast | 1.000 | 1.000 | 1.000 | 1.000 | +0.000 | +0.000 | +0.000 |
| FluSight offline forecast | 0.776 | 0.717 | 0.717 | 0.686 | -0.058 | -0.059 | -0.090 |
| Healthcare bias audit | 0.000 | 0.000 | 0.000 | 0.000 | +0.000 | +0.000 | +0.000 |
| SAP group sequential | 0.250 | 0.350 | 0.250 | 0.240 | +0.100 | +0.000 | -0.010 |
| TCGA LUAD survival KRAS | 0.840 | 0.840 | 0.840 | 0.840 | +0.000 | +0.000 | +0.000 |
| Variant annotation | 0.999 | 0.999 | 0.793 | 0.793 | +0.000 | -0.206 | -0.206 |
| Agora governance | 0.481 | 0.648 | 0.668 | 0.351 | +0.167 | +0.188 | -0.129 |
| Legal DR fees | 1.000 | 1.000 | 1.000 | 1.000 | +0.000 | +0.000 | +0.000 |

## PE screening memo：单列的协议恢复

原四臂 run 在 evaluator 阶段共同失败，不应记为 0。为恢复可用分数，harness 已支持
solver 与 evaluator 分端点：solver、prep、subagent 和 compaction 继续使用原模型；只有
任务 evaluator 使用支持 `gpt-5-mini` 的端点。

恢复单元得到 base `0.8938`、skills `0.9750`、prep `0.9563`、combined `0.9063`。
本轮恢复的 prep cache 是历史失败留下的空报告，combined 也没有实际加载 skill；所以
prep 和 combined 的 arm 标签不代表真实 intervention，只能作为端点/rollout 敏感性观测，
不能并入 25 题主分析。

分析器已产出操作层面的 `104/104 completed` 汇总：base/skills/prep/combined 均分为
`0.6179/0.6055/0.6191/0.5966`。这张表适合确认运行完整性，不适合做 26 题因果推断；
PE 标签污染的事实保存在 `pe_recovery.json`。

另对原同协议四个 solver artifact 使用任务原生 scorer 直接重评分，得到 base `0.8063`、
skills `0.9188`、prep `0.8938`、combined `0.8688`。把这组同源 artifact 当敏感性检查
加入后，26 题 skills/base 平均差为 `-0.0111`，prep/base 为 `+0.0022`，combined/base
为 `-0.0193`；总体决策不变。PE 是单个 LLM-judge 样本，且 combined 低于两个单臂，
不能据此宣布 `evidence-audit` 已稳定有效。

## 关键题逐例分析

### TCGA LUAD survival KRAS

本轮四臂全部为 `0.84`，所以“只有 TCGA 有实际贡献”不再成立。四组的 artifact、cohort、
derivations、reproducibility 等分项相同，唯一 cap 来自 `ph_test_valid=false`。公开任务允许
灵活表达 PH test；隐藏 parser 却只接受 per-variable/table/direct 等包装，拒绝语义完整的
`variables`/`results` wrapper。早期 skills run 恰好命中 parser 形状而得到 `1.0`，这是
schema coincidence，不是可迁移的生存分析能力。正确修复位置是题目 validator 公开唯一
schema 或规范化等价 JSON，不是把隐藏 parser 写入 skill。

这道题仍适合独立 verifier：GDC 是公开 source truth，可以隔离重跑并逐项核对 file ->
sample -> patient 映射、重复样本选择、KRAS gene id、TPM、survival time 和 Cox/PH 计算。

### SEC 10-K financial parsing

四组都是 100 个文件、schema 合法、确定性检查通过，但分数为 `0.639/0.629/0.631/0.595`。
base 的 financial accuracy 为 `0.732`，skills 为 `0.656`，combined 为 `0.641`；combined 的
cross-filing consistency 也从 base `0.71` 降到 `0.54`。这证明 `deliverable-contract` 检查
到了“有文件、有字段、能解析”，却没有提供“output 值是否来自正确 filing 页/表/行”的
独立 source truth。继续加强 checklist 只会重复饱和的 schema 信号。

适合的 verifier 是预先固定抽样种子，从公开 PDF 抽取少量 filing/field，返回 source 页、
表格行、单位、observed 与 expected；只有这种可重现差异才能驱动修复。

### FluSight offline forecast

base/skills/prep/combined 为 `0.776/0.717/0.717/0.686`。对应 WIS 是
`87.42/110.21/110.24/122.37`，MAE 是 `208.19/259.73/253.20/295.42`。所有组都交付
212 行合法 submission；退化发生在预测值，而不是格式。

2024-12-14 之后的真实住院 outcome 在 solve 时不可见，所以 skill 和 prep 都无法产生
真正的 outcome feedback。可验证的是 row/location/horizon/quantile 集合、非负和分位数
单调性；rolling-origin backtest 只能标成 `proxy`，不能宣称未来 WIS 通过。若任务只要求
静态未来 submission，不应为“预测质量”启动 LLM repair loop。

### Agora governance

这是 `evidence-audit` 最可信的窄正例：skills `+0.167`、prep `+0.188`，说明逐比较单元
建立 primary-evidence ledger 可能有帮助。但 combined 是 `-0.129`，析因交互约 `-0.484`。
同时 prep 报告直接判断了文档结论，越过了“只提供 prior”的职责。单次正例支持继续做
窄任务复验，不支持全局默认加载。

### Numerical PDE grading

skills `+0.130`、prep `+0.148`、combined `+0.085`。这里确有可运行的数值 artifact 和
明确比较项，contract 方法与任务匹配；但 combined 没有叠加，且只跑一次。应把它作为
`deliverable-contract` 的目标复验题，至少同臂 `k>=3`，并记录到底是哪条 assertion 改变了
最终答案，而不是仅按总分归因。

### Variant annotation

skills 与 base 同为 `0.999`；prep 和 combined 都稳定降到 `0.793`。prep 用通用 VEP
normalized-allele 语义覆盖题面明确的 submitted ALT convention，造成 3 个 AF 错误和
1 个 reportable mismatch。这是最强的 prep 反例：task-local contract 必须压过上游惯例，
外部知识没有本地锚点时应沉默。

### CRF4、Audience、SSE、Moodle、SAP

CRF4 三个 intervention 全负，skills `-0.184`；Audience 的 skills `-0.142`，但 prep 和
combined `+0.037`；SSE 的 skills `-0.333`，prep/combined 回到 base；Moodle skills
`-0.065`；SAP skills `+0.100`，combined 却 `-0.010`。这些方向翻转说明通用流程文本会
改变搜索和写作轨迹，但改变不等于新增真值信号。早期跨日期 uplift 不能代替同轮对照。

### CT 与 floor/ceiling 题

CT 四臂全 0。公开 reference 和 SSIM/MSE 本来能形成真实闭环，但 agent 始终没有枚举
359.9xx/360 度附近的离散 weighting 分支；长 prep 报告和连续参数 probe 没解决控制变量。
另有 15 道题对 skills 完全同分，多数处在 0、1 或固定 cap，导致平均效应被大量 ties
稀释。后续应在有 headroom、机制匹配的题上做重复实验，而不是再跑一次全量 `k=1`。

## 为什么是 skill 定位问题，而不只是写法问题

两个 SKILL.md 已经很短：`deliverable-contract` 约 194 词，`evidence-audit` 约 180 词。
50/50 个 skill-enabled unit 都加载了 skill；`deliverable-contract` 共加载 48 次，
`evidence-audit` 4 次。因此失败既不是文本太长，也不是没有触发。

主要问题有三层：

1. `deliverable-contract` 触发面仍过宽。普通文件/列/schema 要求本来就是强模型会做的工作，
   skill 增加的是同源提醒，不是新能力；它最容易把“形状通过”误当“内容正确”。
2. `evidence-audit` 的机制更具体，但只适用于明确的多源 verdict matrix。用于一般 prose 或
   构造型任务时会增加阅读/输出路径；目前只有 Agora 和 PE 单样本提供正向迹象。
3. 两者都是 writer-side 方法。writer 同时提出解释、执行和自检时，会把同一个错误假设
   稳定地检查成绿色；它们天然不能提供独立 outcome。

真正值得做成 skill 的内容应满足至少一项：模型原本不知道的专用 API/schema/运行时知识；
反复重写且易错的确定性脚本；稳定、边界清晰的领域工作流；可按需加载的公司/任务族参考。
“仔细检查”“确保完整”或通用 checklist 不值得占一个 skill。

### 建议的 v3 收窄（尚未前向验证）

- `deliverable-contract` 默认不触发普通文件/列要求；只在公开材料提供非平凡 validator、
  executable oracle，或跨文件机器可读 invariant 时触发。工作流缩成：运行 shipped check；
  对遗漏的显式 invariant 加最小测试；针对有精确 locator 的语义值做 source trace；区分
  `checked/failed/unverifiable`。若没有新增可执行检查，就不加载。
- `evidence-audit` 只触发显式的多源 Yes/No/Unknown、claim consistency 或逐项比较矩阵；
  在 scratch 建 requested-unit ledger，逐项记录双方 primary anchor、source precedence 和
  缺口，最终只输出任务要求的字段。一般研究、摘要和单源 prose 不触发。
- 两者都保持默认关闭，先在 PDE、Agora、PE 等匹配题上 `k>=3` 前向验证。没有稳定收益时，
  删除 `deliverable-contract`，只保留真正携带脚本/专有知识的 capability skill。

## Verify 不应通过 skill 实现

参考 [Anthropic outcome grader](https://github.com/anthropics/claude-cookbooks/blob/67ce644d33e5933f0bcc0b6eb4113df41bbf3a8f/managed_agents/CMA_verify_with_outcome_grader.ipynb)
和 [OpenAI iterative repair loop](https://github.com/openai/openai-cookbook/blob/9fa55b8cecba8c9c543d11f2cf08339a29112be7/examples/codex/Build_iterative_repair_loops_with_Codex.ipynb)，
本 harness 的反馈应分成三个隔离角色：

```text
public task/input/software
  -> fresh builder：solve 前固定 verify_spec
  -> writer：生成 output
  -> immutable hash snapshot
  -> fresh runner：只读 spec + public material + snapshot
  -> orchestrator：只回传有证据的 blocking failures
  -> writer repair（最多 2 次）
```

每条 criterion 必须有公开 `source_quote`/locator，并分类为：

| 类型 | 信号 | 可否自动阻断 |
|---|---|---|
| deterministic | schema、集合、类型、算术、不变量、执行测试 | 是 |
| public_evidence | 可重读原始文件/API/网页与精确 source trace | 有具体差异时是 |
| proxy | backtest、启发式指标、抽样覆盖 | 否，只记录 |
| unverifiable | 隐藏未来 outcome、不可访问真值、纯主观质量 | 否，也不能记 pass |

Runner 不看 writer trajectory、memory、prep、隐藏 reference、grader 或历史答案，也不能修改
snapshot。反馈只包含 criterion id、observed、expected、source evidence 和最小 repair hint；
同一失败连续两轮、只有 proxy 振荡、或 verifier 自身 error 时立即停止。这个设计才能提供
与 writer 假设相对独立的反馈信号。

## 成本与下一步

25 题主 agent 平均时长为 base `990.5s`、skills `1096.6s`、prep `1146.7s`、combined
`1065.2s`。run duration 包含 prep，但 run usage 不包含 prep agent usage；prep-only 相比
base 平均多 `156.1s`、约 `27.6k` main input tokens 和 `$0.0262`，却没有分数收益。

下一实验轴应是 `base / prep / verifier / prep+verifier`，而不是把 verifier 塞进 skill。
先用 SEC、TCGA、Variant、FluSight、CT 做机制 smoke，审计 false positive、source trace、
repair 是否收敛和 `unverifiable` 比例；稳定性判断每格至少 `k>=3`。

机器可读结果位于 [`task_prep_skills_v2/`](task_prep_skills_v2/)：`summary.json`、
`scores.csv`、`behavior.csv`、`prep_audit.csv`；PE 恢复协议记录在 `pe_recovery.json`。
