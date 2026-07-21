# Prep v12 六题 Base/Prep 对照

本实验冻结 `task-prep-v12`，只运行 6 个预注册任务的 `base` 与 `prep` 两臂。两臂使用 `openai/gpt-5.6-sol`、medium thinking、同一 endpoint 和相同 writer 配置；verifier 与 writer skills 均关闭。每臂并发 3，总计 12 个 unit，12/12 completed。

## 分数

| Task | Base | Prep | Delta | Prep 状态 |
|---|---:|---:|---:|---|
| BPMN supply disruption | 0.84620 | 0.84950 | +0.00330 | use，2 entries |
| Digital marketing segmentation | 0.76200 | 0.69120 | -0.07080 | use，1 entry |
| SSE northbound reporting | 0.66667 | 0.66667 | 0 | skip |
| PDE homework grading | 0.70497 | 0.64982 | -0.05515 | skip |
| CRF SDTM mapping 4 | 0.60290 | 0.62440 | +0.02150 | use，2 entries |
| FluSight offline forecast | 0.72788 | 0.63725 | -0.09063 | use，1 entry |

Base 均分为 `0.71844`，Prep 为 `0.68647`，配对均值差为 `-0.03196`，标准差 `0.04607`，`t=-1.70`，`n=6`。6 题中 2 题提高、1 题持平、3 题下降。这组单次配对没有证明 Prep 有总体正收益。

机器结果见 [scores.csv](scores.csv)、[behavior.csv](behavior.csv)、[prep_findings.csv](prep_findings.csv)、[prep_writer.csv](prep_writer.csv) 和 [summary.json](summary.json)。每题的初始报告、最终报告和 metadata 位于 [reports](reports/)。

## Prep 行为

6 次 Prep 中 4 次 `use`、2 次 `skip`，共保留 6 条 entry：3 条 `local_conflict`、2 条 `failure_mode`、1 条 `runtime_behavior`。4 份非空初始报告平均 3588 字符，最终平均 3904 字符；2 份被 writer 修改。

网络策略按任务执行：

| Task | Network policy | Search | Fetch | 结果 |
|---|---|---:|---:|---|
| BPMN | allowed | 9 | 2 | use |
| Digital marketing | allowed | 3 | 1 | use |
| PDE homework | allowed | 2 | 2 | skip |
| SSE | prohibited | 0 | 0 | skip |
| CRF SDTM | prohibited | 0 | 0 | use local evidence |
| FluSight | prohibited | 0 | 0 | use local evidence |

所有非空报告都通过 v12 research gate，没有报告因 gate 违规被拒绝。允许联网的任务都实际 search 和 fetch；禁止联网的任务没有 web 调用。该机制解决了 v11“只鼓励、不保证打开网页”的问题。

Writer 读取了全部 4 份非空报告，但 analyzer 只观察到 5/11 个 source 被后续工具调用回查。BPMN 和 FluSight 报告未修改；Digital 与 CRF 报告增加了复核记录。可编辑文件和初始/最终哈希记录有效，但“被修改”不等于“修改正确”。

Prep research 平均用时 126.10 秒，平均输入 122,440 tokens、输出 3,097 tokens。即使最终 `skip`，SSE 和 PDE 仍分别消耗约 48.8 秒/66.9k 输入 tokens、85.5 秒/65.4k 输入 tokens。当前 `TaskPrepResult` 不记录 dollar cost，run 的 `cost_usd` 只反映主 writer，不能用于计算 Prep 的完整增量成本。

## 逐题分析

### BPMN

报告保留两条 Flowable 相关知识：exclusive gateway 对重叠条件按 XML 顺序取首个 true flow；boundary timer 依赖 async executor。Writer 在第 2 次工具调用读取报告，只回查 1/3 个 source，未修改报告。Prep 产物包含独立 joint-waiver tasks、inclusive gateway 和分层成本路由；分数只提高 `0.0033`，不能证明这些额外 runtime 语义带来净收益。

### Digital Marketing

唯一 entry 正确指出 `AUD-005` 引用了 Parquet 和 data dictionary 中不存在的 `has_cart_abandonment`，并引用 pandas `UndefinedVariableError` 文档。问题在于 `solver_use` 从“字段不可计算”跨到了“输出 NA”这一未由任务合同定义的处理决策。Prep 输出把 AUD-005 的三个数值字段写成 `NA`，base 写成 `0/0.0/0`；Prep 分数低 `0.0708`。这是“事实正确但行动建议越过 `/input` 权威”的明确失败。

### SSE

任务显式 closed-book。Prep v12 返回 `skip`，不再把本地法规解释作为额外先验注入；两臂同为 `0.6667`。v11 同题曾因报告放大语言许可的不确定性得到 0，v12 去掉了这条有害路径。

### PDE Homework

Prep 在完成 search 和 fetch 后判断外部资料不会增加公开 rubric 之外的知识，返回 `skip`。两臂仍相差 `-0.05515`；两份 grades.csv 相同，主要差异是 Prep writer 多给 S03 一个 error tag。因为没有报告注入，该差异是独立 writer rollout 方差，不能归因于 Prep 内容。

### CRF SDTM

任务禁止外部 web。两条 local conflict 分别区分 ADaM `supp_define.xml` 与 SDTM define，并保留两个不同 CRF 问题到同一 AE.AECONTRT target 的 composite-key 映射。Writer 回查 2/4 个 source 并修改报告。Prep CSV 为 39 行，base 为 41 行；Prep 使用更细的 `Record Qualifier`、`Synonym Qualifier` 等角色，分数提高 `0.0215`。提升较小，仍不足以把该报告升级为通用规则。

### FluSight

任务明确要求只用 staged local files。报告只保留 36 个 interior missing observations 这一事实。Writer 回查 2/2 个 source但未修改报告。两臂 211 个 point forecast 全部不同；Prep 的 jurisdiction 平均区间宽度约 530，base 约 771，Prep 分数低 `0.09063`。一条真实缺失值事实不足以决定模型和区间校准，单次结果也不能分离报告影响与 forecast rollout 方差。

## 结论

v12 达到了机制目标：Prep/Verifier 独立、报告低于 `/input`、报告可维护、联网规则可执行、内容从 v11 的 17 条降到 6 条、closed-book 题可 skip。但它没有达到效果目标：六题均分仍低于 base。

当前缺陷是：

1. 真实且权威的证据仍可能导出任务未授权的 handling policy，Digital 的 `NA` 是具体反例。
2. Writer source 回查率只有 5/11；handoff 要求没有形成稳定行为。
3. Prep 研究成本高，skip 只阻止内容注入，不退还研究成本。
4. 一次 rollout 的方差足以改变单题方向；PDE skip 题仍出现 0.055 的 arm 差。
5. Prep 不承担 coverage；完整输入覆盖仍必须由 writer、verifier contract checks 和原 evaluator 分别负责。

因此 Prep v12 应继续默认关闭。该实验支持保留研究能力和审计产物，不支持默认给所有任务启用 Prep。

## Skills 积累

不应让每次 Prep 自动修改全局 skill。任务报告可以进入 candidate pool，但升级为 skill 前需要跨任务复现、明确适用条件、反例、权威来源、版本和 canary。当前候选包括 Flowable gateway/timer 检查流程、CDISC value-level metadata 导航和 forecast missingness/backtest 流程；本轮 BPMN 近乎持平、FluSight下降，因此都还不能升级为默认 skill。

较稳妥的两层结构是：当前 episode 维护 `PREP_REPORT.md`；离线流程聚类多题候选，人工或自动测试审核后发布 versioned skill。Skill 保存研究方法和检查流程，不保存实例答案，也不能高于 `/input`。
