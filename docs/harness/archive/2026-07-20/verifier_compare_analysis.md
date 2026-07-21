# Prep / Verifier 全量审计分析

更新于 2026-07-19。实验在 pgl 运行 26 个 headless task、四个 arm，每格一次：
`base`、`prep`、`verifier`、`prep+verifier`。Verifier 两臂均为 audit-only，
`max_repairs=0`；因此 verifier 没有修改任何 artifact。

## 结论

1. **当前 skills 不应进入默认实验轴。** 前一轮 25 题中，50/50 个 skill-enabled unit
   都实际加载了 skill，但 skills `-0.0161`、skills+prep `-0.0226`。这否定的是当前两条
   通用 writer-side skill 的净收益，不是否定所有面向具体工具/任务的 skill。
2. **Prep v7 达到了“短、task-local、可沉默”，但没有总体收益。** 25 题配对均值
   `+0.00093`，t=`0.079`；20 个有报告任务为 `+0.00648`，5 个 empty 任务为
   `-0.02124`，后者直接量出了单次 rollout 噪声。Agora 是可解释正例，FluSight 连续
   两轮下降。Prep 保持默认关闭，只对匹配题型做 `k>=3` 前向复验。
3. **独立 verifier 能发现真实错误，但不能作为完成证书或默认 repair gate。** 34 个
   fail criterion 中，人工复核为 30 个公开证据支持、1 个边界项、3 个明确误报；同时
   MARC、CRF4、SAP 等低分 artifact 仍被判 pass，AAPL 相同 artifact 甚至一臂 fail、一臂
   pass。自动 repair 继续默认 0。
4. **Verifier 分数差不是 verifier 效果。** audit-only 在 solve 后运行，不修改输出；
   verifier `-0.01388`、combined `-0.01360` 只是不同 writer rollout、endpoint 和运行负载
   的结果，不能解释为“检查让分数下降”。

## 协议与限制

- 主表排除 PE screening memo，严格得到 `25 x 4 = 100` 个 completed 同协议单元。
- PE 的 base/prep/verifier solver artifact 存在，但原 evaluator 临时返回
  `model_not_found`；它们只做一次 task-native post-hoc rescore。combined 原 run 因公开
  路径冲突没有在 runtime output root 留下 memo，原 evaluator 正常给 0。详见
  [`pe_recovery.json`](verifier_compare/pe_recovery.json)。
- 每格只有一次，不足以检测小效应或声称稳定性。
- 本轮 `settings_used.yaml` 将 endpoint 固定按 arm 轮转：base 与 combined 使用同一
  sub2api key，prep 使用另一 sub2api key，verifier 使用 Boyue。这把 endpoint/account
  与 arm 混杂，所以结果是 operational comparison，不是严格随机因果实验。控制面现已
  默认使用一个共享 endpoint，并对按臂轮转打印警告。

两份设计参考的共同原则被保留：独立 context、artifact 取证、结构化 handoff、有限停止；
没有照搬其“grader 一定可信”的假设：

- [Claude outcome grader](https://github.com/anthropics/claude-cookbooks/blob/67ce644d33e5933f0bcc0b6eb4113df41bbf3a8f/managed_agents/CMA_verify_with_outcome_grader.ipynb)
- [Codex iterative repair loop](https://github.com/openai/openai-cookbook/blob/9fa55b8cecba8c9c543d11f2cf08339a29112be7/examples/codex/Build_iterative_repair_loops_with_Codex.ipynb)

## 25 题主结果

| Arm | completed | 均分 | paired delta | 正 / 平 / 负 | SD / SE / t |
|---|---:|---:|---:|---:|---:|
| base | 25 | 0.61540 | - | - | - |
| prep | 25 | 0.61633 | +0.00093 | 4 / 17 / 4 | 0.05913 / 0.01183 / 0.079 |
| verifier | 25 | 0.60153 | -0.01388 | 4 / 16 / 5 | 0.06533 / 0.01307 / -1.062 |
| prep + verifier | 25 | 0.60180 | -0.01360 | 4 / 17 / 4 | 0.06875 / 0.01375 / -0.989 |

Prep 的 20 个 `completed` 报告任务中，prep-only 为 3 正 / 14 平 / 3 负；正例是 BPMN
supply `+0.0476`、SEC `+0.0366`、Agora `+0.1847`，负例是 Moodle `-0.0650`、CRF4
`-0.0096`、FluSight `-0.0648`。5 个 empty 任务仍出现 PDE `+0.0735` 和 audience
`-0.1797`，证明大幅单题 delta 也可以在没有 prep intervention 时产生。

base 与 combined 使用同一 endpoint；combined 的 Agora `+0.1629` 支持 targeted prep
的后续验证，但 SEC `-0.1070`、FluSight `-0.0627`、Variant `-0.2060` 又说明单次结果
不稳定。组合 arm 不具有单调性。

## Verifier 审计质量

50 个 verifier-on 单元中：

- 48 个 spec 构建成功，2 个被 lint 拒绝；25 题 fingerprint 全相同，23 题两臂 spec SHA
  相同，另两题正是单侧 builder error。
- 317 条实际 verdict：269 pass、34 fail、13 unverifiable、1 error。
- round overall：22 pass、18 fail、4 unverifiable、4 error，另 2 个没有 runner；0 repairs。
- 6 个 error stop：American 两臂 v4 snapshot 遇到虚拟环境 symlink；Legal 与 SAP 各一条
  builder lint error；bias 一条 runner max-steps、一条可执行环境不等价 criterion error。

对 34 条 fail 的人工 source/evidence 复核：

| 分类 | 数量 | 例子 |
|---|---:|---|
| 公开证据支持 | 30 | BPMN 拓扑/变量闭包，XOM EPS 7.84，CT SSIM，Variant AF 0.8255，Agora matrix schema |
| 边界项 | 1 | Moodle ZIP 新增目录 entry；字面改变 member set，但 immutable 文件 hash 全一致 |
| 明确误报 | 3 | Legal 强制引文逐字连续；CRF 禁止有 collected source 的派生目标；TCGA 15/16 字符矛盾 |

这说明 fail finding 的精度尚可，但不是安全 gate：

- **规则加严。** CRF1 的 spec 把“无对应 CRF 字段的 derived variable 应省略”改写成
  “origin 必须全部等于 CRF”；任务自己的 canonical reference 正好包含四条由 collected
  Ongoing 字段支持的 Derived 行。
- **公开材料冲突。** TCGA 一处写 first 15 characters，示例却是 16 字符；combined runner
  明知 490/490 都是 16 字符仍 fail。该误报在 smoke 与 full 两轮复现。
- **同 spec/同 artifact 不一致。** AAPL 四臂 regular-file 内容相同，额外有 `aapl.txt`；
  一条 runner 按“exactly one final file”判 fail，另一条自行解释为 scratch 后 pass。
- **覆盖不足。** MARC 两臂 pass 而 score=0.2；CRF4 两臂 pass 而 score=0.6627/0.6435；
  SAP combined 的 7 项全 pass 而 score=0.25。`overall=pass` 只能表示注册项未报错。
- **正确拒绝。** FluSight 把未来 WIS/coverage 标为 unverifiable；bias 在无法复现旧
  sklearn normalization 时返回 error；没有把不可执行检查伪装成 pass。

## 逐题审计

`P` 为 prep 报告状态；`V/C` 为 verifier-only / combined 的最后 overall。完整 criterion
证据见 [`verifier_criteria.csv`](verifier_compare/verifier_criteria.csv)。

| Task | P | Base / Prep / Verifier / Combined | V / C | 主要判断 |
|---|---|---:|---|---|
| American option | use | 1 / 1 / 1 / 1 | error / error | v4 因 output 内临时 venv symlink 中止；v5 已安全省略并记录链接 |
| BPMN category | use | 0 / 0 / 0 / 0 | fail / fail | gateway default、logistics anchor、dataflow 和 compliance claim 均有实证 |
| BPMN supply | use | .823 / .871 / .854 / .854 | fail / fail | topology、counter、角色输入和假 scenario path 为真实缺口 |
| Marketing AB | use | 1 / 1 / 1 / 1 | unverifiable / pass | schema/公式通过；一臂对未完整引用的要求正确拒绝 |
| Audience segmentation | skip | .904 / .725 / .725 / .725 | pass / pass | 无 prep 时仍大幅波动；注册项未覆盖全部质量 |
| AAPL statement | use | 1 / 1 / 1 / 1 | fail / pass | 相同 extra scratch file 被两条 runner 相反解释 |
| Employee agent | use | 1 / 1 / 1 / 1 | pass / pass | 公开 contract 检查一致 |
| Legal M&A | use | 0 / 0 / 0 / 0 | builder error / fail | combined 的 exact-contiguous quote 是规则加严误报 |
| Privacy audit | use | .5 / .5 / .5 / .5 | fail / unverifiable | verifier 正确找到公开规则下遗漏的 7 个 qualifying domain |
| SEC 10-K | use | .706 / .742 / .648 / .599 | fail / fail | XOM EPS 7.84 与 QA/normalized data 不一致可复算；自动改 QA 仍有传播错误风险 |
| SSE trading | skip | .667 / .667 / .667 / .667 | pass / pass | verifier 没覆盖所有任务质量 |
| PDE grading | skip | .650 / .723 / .685 / .650 | pass / pass | empty prep 下 delta 仍大，说明 rollout noise |
| MARC | skip | .2 / .2 / .2 / .2 | pass / pass | 明确 false-negative/coverage failure |
| Moodle | use | .95 / .885 / .95 / .95 | fail / pass | 目录 entry 是低严重度边界项，immutable file hash 均一致 |
| CRF1 | use | 0 / 0 / 0 / 0 | fail / pass | Derived-origin failure 是对公开 qualifier 的错误加严 |
| CRF4 | use | .622 / .612 / .663 / .644 | pass / pass | 只抽查 5 个字段，不能代表 38 行全部正确 |
| CT geometry | skip | 0 / 0 / 0 / 0 | fail / fail | 两臂 MSE 通过、SSIM 约 .9033/.9036，准确说明未完成 |
| Epidemiology | use | 1 / 1 / 1 / 1 | unverifiable / pass | quote 未枚举 23 quantile 时一臂正确拒绝；结果均为 1 |
| FluSight | use | .770 / .705 / .657 / .707 | pass / pass | 4 个结构项 pass，未来 outcome 与 provenance 均 unverifiable；prep 再次下降 |
| Bias audit | use | 0 / 0 / 0 / 0 | error / error | 旧 sklearn normalization 不可等价复现，另一臂 max steps；未伪造结论 |
| SAP | use | .25 / .25 / .24 / .25 | builder error / pass | builder 不稳定且 combined 明显 coverage false-negative |
| TCGA | use | .84 / .84 / .84 / .84 | fail / fail | 一臂发现 disabled GDC/OS/stage 代码；另一臂复现 15/16 误报 |
| Variant | use | .999 / .999 / .793 / .793 | fail / fail | 两臂均准确找到 AF=.8255 却 reportable=yes 的同一错误 |
| Agora | use | .505 / .690 / .617 / .668 | fail / unverifiable | prep 的 taxonomy/footnote research 有用；verifier 找到 matrix Boolean schema 缺口 |
| Legal DR fees | use | 1 / 1 / 1 / 1 | pass / pass | 四臂与 verifier 一致通过 |

## PE 协议例外

base/prep/verifier 的原 memo 经同一 task-native scorer 单次 post-hoc 得到
`0.86875 / 0.8875 / 0.925`。combined 原 run 为 0，不是 LLM judge 失败：staged
`task_brief.md` 要求写到 `agenthle/finance/...`，runtime task root/output pull 却是
`agenthle/business_finance/...`。Writer 在错误公开路径写出了 2,223 词完整 memo，正确
runtime output 仍为空。这应修 task material 的路径，不应把 pull 规则塞进 skill。

若把这行作为第 26 个敏感性样本，prep paired delta 仍只有 `+0.00162`；combined
`-0.04649` 被单个路径冲突主导。主结论不变。

## 成本

| Arm | mean duration | main input tokens | main cost |
|---|---:|---:|---:|
| base | 1115.6 s | 286,127 | $0.534 |
| prep | 1072.3 s | 233,182 | $0.508 |
| verifier | 1131.3 s | 229,151 | $0.469 |
| combined | 1218.0 s | 233,027 | $0.471 |

Main usage 不含独立 agent usage。50 个 prep-on unit 中 40 completed report、10 empty；
含 cache hit 的平均 prep cost proxy 为 30,289 input tokens、74.7 秒。Verifier 每个 enabled
unit 的 builder 平均 20,596 input tokens、67.4 秒；实际启动 runner 的 48 个 unit 平均
88,142 input tokens、185.7 秒。单次 writer 方差很大，所以 arm wall-time 差不能单独解释
为 verifier overhead。

## 实现后的最终决策

- skills 从默认 axes 隐藏；保留为 writer-side 方法，不承担独立 grading。
- prep 默认关闭；v7 保留 task-local research 与 `NO_TASK_SPECIFIC_PREP` gate。优先在 Agora
  一类 taxonomy/evidence task 上做 `k>=3`，而不是全量开启。
- verifier 默认关闭；开启时默认 audit-only、`max_repairs=0`。只有逐题人工确认过的
  deterministic criterion 才可显式开启 1-2 次 repair。
- 不再继续叠加 prompt 规则。Production gate 需要人写/结构化 DSL 的 deterministic checks，
  LLM runner 只负责取证和 non-blocking 语义审计。
- full run 使用 v4。实验后 v5 修复了 symlink 快照、同时哈希 snapshot 与原 output、异常
  路径也执行完整性检查，以及 builder lint 失败时保留 usage。这些修复有回归测试，但没有
  冒充本轮评分结果。

机器结果在 [`verifier_compare/`](verifier_compare/)：`summary.json`、`scores.csv`、
`behavior.csv`、`prep_audit.csv`、`verifier_audit.csv`、`verifier_criteria.csv`，以及原样
实验控制面 `settings_used.yaml`。
