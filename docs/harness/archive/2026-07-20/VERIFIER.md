# 独立 Verifier 设计

## 决策

Verifier 不应实现成 writer 会话里的 skill。skill 可以教主 agent 如何工作，也可以让它
运行公开的局部检查，但同一上下文中的自检不是独立反馈。真正的 verifier 是 harness
编排层中的另一角色：它使用新的上下文，只读冻结后的产物，并按可追溯的公开标准返回
结构化证据。

这一区分对应两份参考实现的共同结构：Anthropic outcome grader 使用独立 context 逐项
检查 artifact，并把失败 criterion 反馈给 writer；OpenAI repair loop 把 review、repair
和 execution validation 分开，用结构化 handoff 驱动下一轮。参考：

- [Claude outcome grader](https://github.com/anthropics/claude-cookbooks/blob/67ce644d33e5933f0bcc0b6eb4113df41bbf3a8f/managed_agents/CMA_verify_with_outcome_grader.ipynb)
- [Codex iterative repair loop](https://github.com/openai/openai-cookbook/blob/9fa55b8cecba8c9c543d11f2cf08339a29112be7/examples/codex/Build_iterative_repair_loops_with_Codex.ipynb)

## 角色边界

```text
public task/input/software
  -> verifier builder (fresh context, before solving)
       -> verify_spec.json
  -> optional task-specific prep (prior research only)
  -> writer/main agent
       -> output snapshot N (read-only, content hashed)
  -> verifier runner (fresh context, no writer trace or memory)
       -> deterministic evidence + criterion verdicts
  -> orchestrator
       -> only actionable failures -> writer repair
       -> output snapshot N+1 -> fresh verifier runner
```

`verifier builder` 只看公开任务材料，在 writer 开始前生成检查规格，避免针对某次答案
事后发明标准。`verifier runner` 只看同一公开材料、冻结产物和检查规格；它不看 writer
reasoning、trajectory、memory、prep 报告、隐藏 reference、grader 或历史答案。检查脚本
放在 harness 私有工作区，不进入题目要求的 output。

若 builder 由 LLM 实现，它的输出先经过机械 spec lint，而不是直接成为评分标准：每条
criterion 必须有可解析的公开 source anchor、允许的类型和明确的 observed/expected
比较方式；缺少来源、引用不存在或把 proxy 写成 deterministic 的条目直接拒绝。能由
代码执行的检查交给确定性 runner；只有需要从公开材料做语义抽取时才调用 fresh LLM，
并要求它返回页码、行号、record id 或原始值。这样把“提出标准”“取证”“裁决”和
“修复”分开，避免一个模型同时发明规则又宣布自己通过。

## Criterion 规则

每个 criterion 必须包含公开来源位置，并被分到下列一种类型：

| 类型 | 可用信号 | 是否可阻断完成 |
|---|---|---|
| `deterministic` | schema、文件/行/键集合、类型、算术、不变量、可执行测试 | 是 |
| `public_evidence` | 可重新读取的原始文件、API 记录、网页、数据库记录 | 有具体证据时是 |
| `proxy` | backtest、启发式质量指标、抽样检查 | 否；只记录，不触发自动修复 |
| `unverifiable` | 隐藏未来 outcome、主观质量、不可访问 source truth | 否，也不能记作 pass |

Builder 不得把 rubric 写得比公开 task contract 更具体，除非新增标准来自有引用的通用
领域规范。Anthropic 示例由人明确决定“必须是 10-K/10-Q 而不是新闻稿”；在 ALE 中，
LLM 自己猜出类似隐藏偏好会变成 evaluator 拟合。缺少来源的 criterion 必须降级为
`unverifiable`，不能参与 gate。

检查预算同样在 solve 前固定：确定性 schema/文件/算术检查可以全量运行；需要逐页或逐条
语义取证的 `public_evidence` 在整个 spec 中最多 5 个明确 locator，由公开 task fingerprint
seed 稳定选择。要求 runner “逐项人工核对整个 corpus”的 spec 会被 lint 拒绝，不能在
有限 runner 预算内假装完成。

公开 source anchor 还不够：每条 criterion 必须保存能直接推出 `requirement`、`check` 和
`expected` 全部限制的 `source_quote`。字段名、例子、惯例或两个字段同时出现都不能建立
新的跨字段约束；check 也不能私自增加 exactness、contiguity、order 或 tolerance。Runner
先核对 quote 与 source，并返回 `source_status=supported|ambiguous|contradicted|missing` 与
独立 `source_evidence`。代码把后三种状态强制归一化为 `unverifiable`，不得把 spec 错误
变成 writer failure。

`source_quote` 可以由多段独立 excerpt 构成，不要求整个拼接块连续出现。Artifact 内明确的
ellipsis/omission marker 同样默认分隔多个 excerpt；除非公开 contract 明示 exact contiguous，
runner 逐片段在同一 cited source 定位，不能因为省略号本身不在原文而 fail。

若公开 reference/oracle 用于评价派生、重建、校准或变换 artifact，builder 还必须注册
provenance 检查，防止 copying、direct mixing 或 substitution 绕过实际 derivation。MSE/SSIM
等 metric 通过不能单独证明产物由要求的过程生成。

## 反馈协议

Verifier 每次返回机器可读记录，而不是一段“看起来不错”的评价：

```json
{
  "snapshot_sha256": "...",
  "overall": "fail",
  "criteria": [
    {
      "id": "output.schema.required_columns",
      "status": "fail",
      "type": "deterministic",
      "source": "input/output_contract.json#/required_columns",
      "source_status": "supported",
      "source_evidence": "required_columns explicitly includes sample_id",
      "evidence": "output/cohort.csv is missing sample_id",
      "observed": ["patient_id", "file_id"],
      "expected": ["patient_id", "sample_id", "file_id"],
      "repair_hint": "Add sample_id from the public source record; do not infer it."
    }
  ]
}
```

状态只有 `pass`、`fail`、`unverifiable` 和 `error`。`pass` 必须附带运行证据或可定位的
source trace；`unverifiable` 不得折算为 pass；verifier 自身异常记为 `error`，不得给
writer 制造负反馈。`overall=pass` 只表示本次 runner 认为全部预注册 blocking criteria
通过，不表示 artifact 全面正确，也不能覆盖 spec 没注册的要求。Writer 只接收失败
criterion、证据和修复方向，不接收隐藏标准或 verifier 内部推理。

反馈信号按信息量排序：可复现的执行失败或数值差异最强；带 source trace 的语义冲突
其次；历史 backtest 等 proxy 只反馈其声明范围；无公开 outcome 时返回
`unverifiable`。Orchestrator 不把 verifier 的自由文本、置信度或笼统总分直接喂回
writer，只发送最小失败集合，防止反馈本身变成新的任务提示或答案泄露通道。

代码兼容最多 3 次循环，但默认和当前全量配置均为 0 次自动 repair。v6 canary 中 BPMN
修复引入新失败，SEC 传播错误上游抽取，SAP/TCGA 公开修复不提分，CT 更直接复制或混入
公开 reference。这个结果否定了“只要 supported deterministic fail 就可安全 repair”的
假设。每轮仍重新哈希产物并启动 fresh verifier，但 repair 只保留为显式研究开关。

## 三道题应如何处理

### SEC 10-K parsing

Schema、文件数、命名、第二遍确定性只能证明 artifact contract。语义反馈应由独立
verifier 从公开 PDF 随机抽取 filing/field，记录页码、表格行、单位和 output 值，再逐项
比较。没有 source trace 的“JSON 全绿”不能证明财务数值正确。随机种子和抽样预算应在
writer 前冻结，避免 writer 针对固定样本过拟合。

### FluSight forecast

行数、location/horizon/quantile 集合、单调性和非负性可确定验证；2024-12-14 之后的
隐藏住院 outcome 在作答时不可验证，必须标为 `unverifiable`。若任务要求交付可执行模型，
可用预注册的 rolling-origin holdout 产生 proxy feedback，但它只能说明历史泛化，不能
宣称未来预测通过。若只交付静态未来 submission，就不应为预测质量启动 LLM repair loop。

### TCGA LUAD survival

公开 GDC 是可重取的 source truth，适合独立验证。Verifier 可在隔离环境重跑代码，核对
file/sample/patient 映射、重复样本选择、KRAS gene id、assay、缺失处理、cohort schema、
生存时间和 Cox 公式，并给出 GDC record id 与输出行的 trace。这比 writer 自己断言表头
更强，也比猜隐藏 grader 字段更可迁移。

本轮还暴露了题目 evaluator 的反例：公开要求写明 `ph_test` 结构可灵活表达，两个新
run 都提交了完整 Schoenfeld 结果，却因分别使用 `variables` 和 `results` 包装而被隐藏
parser 判无变量并 cap 到 0.84；旧 skills 恰好使用直接键才得到 1.0。正确修复位置是题目
验证层规范化这些语义等价结构，或把唯一 schema 公开化；不能把隐藏 parser 接受的形状
写进 skill 或 verifier spec。

## Skills 的真实定位

`deliverable-contract` 和 `evidence-audit` 只保留 writer-side 方法：前者检查公开可观测的
artifact contract，后者追踪多源结论的证据覆盖。它们不生成 outcome rubric，不宣称
独立通过，不要求把 checker 留在 output，也不负责 writer-verifier 循环。任务不匹配时
不加载 skill 是正确行为，不是召回失败。

Prep 的职责仍是 solver 前的任务特定先验研究。它不看 writer 产物，因此也不是 verifier；
把 verifier 生成塞回 prep 会再次混合 prior、作答和评分三种职责。

## 当前实现

实现位于 `ale_run/agents/ale_claw/verifier.py`，编排入口在 ALE Claw deployer：

- `build_verify_spec()` 在 solver 前运行 fresh builder，并对 criterion type、id、公开 source
  anchor、blocking 权限和数量做 lint；当前 protocol 为 `public-verifier-v10`，protocol 进入
  fingerprint，旧 spec cache 不会跨版本复用。
- `snapshot_output()` 将最终 `output/` 复制到独立路径；v5 不解引用符号链接，在 runner
  启动前删除链接并把路径写入快照旁的只读 sidecar，随后去除写权限并记录文件数和内容
  SHA-256。Sidecar 不进入 artifact，因而不会污染 `exactly one file` 一类检查；链接不能
  逃出快照，也不会让整个审计因产物内的临时环境中止。Runner 返回后重新哈希，任何
  snapshot 变化或原始 `output/` 变化都成为 verifier `error`。
- `verify_snapshot()` 每轮启动 fresh runner，强制逐 criterion JSON verdict；总体状态由代码
  根据逐项结果重算，不信任模型自报的 overall。任何非 `supported` source status 都由代码
  变成 `unverifiable`，并删除 repair hint。
- `build_repair_prompt()` 只序列化可阻断失败，不包含 verifier reasoning、proxy 或
  unverifiable 条目。
- deployer 兼容最多 repair 三次，但默认和当前全量均为 0；相同 criterion id 集合连续失败即停止。全部过程发生在
  lifecycle stage hidden reference 之前。

Host 审计产物为 `verifier_spec.json`、`verifier_round_N.json`、`verifier_meta.json`；meta
显式记录 protocol。`harness/run/analyze_factorial.py` 另外生成 flattened criterion、source
status 和相邻 repair transition 表。
首版只支持 Linux task；不支持时记 verifier error，solver 仍正常完成。

## 实验结果

Verifier 作为独立实验轴，不并入 skills。5 题 smoke 后，26 题四臂全量 audit-only 实验
已在 pgl 完成；25 个同协议配对任务中 prep `+0.00093`、verifier `-0.01388`、combined
`-0.01360`，0 repairs。34 个 fail criterion 人工复核为 30 个公开证据支持、1 个边界项、
3 个误报；同时存在明显 coverage false-negative 和同 artifact verdict 不一致。因此 verifier
保留为默认关闭的独立审计，自动 repair 默认 0。完整逐题证据和成本见
[全量分析](verifier_compare_analysis.md)。稳定性结论仍要求匹配题型每格至少重复 3 次。

随后 10 题 v8/v6 canary 的原始 factorial 被 CT reference mixing 的非法 +1 扭曲；排除 CT
后 prep main effect `-0.0161`、verifier main effect `-0.0033`。191 条 round-level criterion
中 source status 为 178 supported、2 ambiguous、7 missing、4 contradicted。TCGA/Variant
公开冲突被正确降级，但 Legal ellipsis 和 CT provenance 继续推动协议到 v9。完整证据见
[canary 分析](prep_v8_verifier_v6_canary_analysis.md)和
[协议迭代](prep_verifier_protocol_iteration_analysis.md)。新的 prep v10 / verifier v10 26 题
四臂全量已在 pgl 完成：52/52 spec 成功、0 repairs；344 条 criterion 中 180 pass、
156 unverifiable、6 fail、2 error。CT provenance 正确验证了真实 FBP；但 American/Moodle
共 4 次 runner 通过 task runtime wrapper 改变原 output，证明下一版必须使用独立只读容器。
完整实现、逐题统计和限制见[最终分析](prep_v10_verifier_v10_full_analysis.md)。
