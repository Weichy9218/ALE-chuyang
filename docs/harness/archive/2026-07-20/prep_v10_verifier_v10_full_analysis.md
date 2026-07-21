# Prep v10 / Verifier v10：实现、Skills 判断与最终全量分析

更新于 2026-07-20。最终实验在 pgl 使用同一 `openai/gpt-5.6-sol` endpoint、26 题、
四臂各一次：`base / prep / verifier / prep_verifier`。104/104 个 unit 都有 `run.json`；
100 completed，PE screening memo 四臂都在原 evaluator 请求不可用的 `gpt-5-mini` 时得到
404，因此 PE 不记 0，也不进入 25 题配对主表。Verifier 全程 `max_repairs=0`。

机器结果在 [`results/latest/`](../../results/latest/)；协议迭代证据见
[Canary 后协议迭代](prep_verifier_protocol_iteration_analysis.md)。

## 结论

1. **Prep v10 修复了一个稳定的有害机制，但没有证明全局净增益。** 25 题 prep-only 相对
   base 为 `-0.00977`（SE `0.01796`，t=`-0.54`）；2x2 prep main effect 为 `+0.02205`
   （SE `0.02298`，t=`0.96`）。Variant 的 exact submitted-ALT 修复在 canary 和 full 两次
   都得到 `.793 -> .999`，是可信的窄机制证据；它不等于全任务 uplift。
2. **Verifier v10 是保守的 public-contract auditor，不是 outcome grader。** 52 份 spec
   全部构建成功且两臂逐题 SHA 相同；344 条 criterion 中只有 6 fail，156 unverifiable。
   它能验证 CT 是真实 FBP 重建，也会拒绝把 FluSight 的隐藏未来 WIS 说成 pass；但 CRF1
   的 0 分产物和 SAP 的 `.25` 产物仍可 overall pass。
3. **Verifier 分数不是 verifier 效果。** 52 个 verifier-on unit 均为 0 repair。verifier-only
   `+.01010`、combined `+.06396` 都是独立 writer rollout 差异。combined 的主要高杠杆是
   CT `0/0/0/1` 与 SSE `.667/.333/1/1`；去掉两题后 combined-vs-base 仅 `+.01155`
   （t=`0.67`），verifier main effect `+.00208`（t=`0.23`）。
4. **当前两个通用 skills 不应默认加载。** 它们已被重写和缩短，但 25 题 skills-only
   仍为 `-0.0161`，50/50 个 enabled unit 又都确实加载成功。`deliverable-contract` 应从
   active 方法库退役；`evidence-audit` 只保留为窄任务、`k>=3` 的实验候选。
5. **下一步优先修 verifier 隔离，而不是继续加 prompt。** American 与 Moodle 共 4 个
   runner 通过 task runtime wrapper 在原 output 下更新环境文件，被前后 hash 正确捕获为
   verifier error。这证明 fresh context、只读 snapshot 和 prompt 约束仍不等于文件系统隔离。

## 最终运行统计

| Arm | runs | completed / failed | 25 题均分 | 相对 base | 正 / 平 / 负 |
|---|---:|---:|---:|---:|---:|
| base | 26 | 25 / 1 | .60547 | - | - |
| prep | 26 | 25 / 1 | .59570 | -.00977 | 4 / 15 / 6 |
| verifier | 26 | 25 / 1 | .61556 | +.01010 | 4 / 14 / 7 |
| prep + verifier | 26 | 25 / 1 | .66943 | +.06396 | 8 / 14 / 3 |

2x2 析因估计：prep `+.02205`（t=`0.96`）、verifier `+.04191`（t=`1.45`）、交互
`+.06364`（t=`1.43`）。这些值都没有跨过本轮噪声，且 verifier 没有修改 artifact。

敏感性检查：

| 主集 | n | prep main | verifier main | interaction | combined-base |
|---|---:|---:|---:|---:|---:|
| 全部有效题 | 25 | +.02205 | +.04191 | +.06364 | +.06396 |
| 去掉 CT 高杠杆 | 24 | +.00213 | +.02283 | +.02462 | +.02496 |
| 再去掉 SSE 高杠杆 | 23 | +.00947 | +.00208 | +.01120 | +.01155 |

逐题结果：

| Task | base | prep | verifier | combined |
|---|---:|---:|---:|---:|
| American option | 1 | 1 | 1 | 1 |
| BPMN category | 0 | 0 | 0 | 0 |
| BPMN supply | .9248 | .8295 | .8395 | .8638 |
| Marketing A/B | 1 | 1 | 1 | 1 |
| Audience segmentation | .7245 | .8333 | .9042 | .8708 |
| AAPL statement | 1 | 1 | 1 | 1 |
| Employee agent | 1 | 1 | 1 | 1 |
| Legal M&A | 0 | 0 | 0 | 0 |
| Privacy audit | .5 | .5 | .5 | .5 |
| PE screening | evaluator 404 | evaluator 404 | evaluator 404 | evaluator 404 |
| SEC 10-K | .6817 | .6427 | .6036 | .7085 |
| SSE trading | .6667 | .3333 | 1 | 1 |
| Numerical PDE | .6598 | .6950 | .5568 | .6690 |
| MARC | .2 | .2 | .2 | .2 |
| Moodle | .95 | .95 | .885 | .95 |
| CRF1 | 0 | 0 | 0 | 0 |
| CRF4 | .6699 | .5933 | .6411 | .4737 |
| CT geometry | 0 | 0 | 0 | 1 |
| Epidemiology | 1 | 1 | 1 | 1 |
| FluSight | .6856 | .7393 | .6998 | .7210 |
| Bias audit | 0 | 0 | 0 | 0 |
| SAP | .34 | .24 | .25 | .25 |
| TCGA | .84 | .84 | .84 | .84 |
| Variant | .793 | .999 | .999 | .999 |
| Agora | .5007 | .4970 | .4702 | .6900 |
| Legal DR fees | 1 | 1 | 1 | 1 |

## 1. Prep v10 是怎么做的

### 源码与流程

核心实现是 [`task_prep.py`](../../ale_run/agents/ale_claw/task_prep.py)：

- 协议、最多 3 条 finding 和工具白名单在
  [`task_prep.py:31`](../../ale_run/agents/ale_claw/task_prep.py#L31)。Prep 只有 read、exec、
  web fetch/search 和 image analysis，没有 solver memory、skills 或继续 delegation。
- cache fingerprint 在
  [`task_prep.py:99`](../../ale_run/agents/ale_claw/task_prep.py#L99)，包含 protocol、task id、
  完整 prompt、model、web 可用性，以及 Linux 下 `input/`、`software/` 的内容哈希。
- 研究边界在
  [`task_prep.py:147`](../../ale_run/agents/ale_claw/task_prep.py#L147)：只找会改变方法选择的
  task-local/runtime 事实；task-local contract 压过上游惯例；不可见 outcome 的 heuristic
  必须先通过 task-local holdout/backtest；精确 endpoint 要先做小单侧扰动。
- JSON 归一化在
  [`task_prep.py:246`](../../ale_run/agents/ale_claw/task_prep.py#L246)，只接受完整字段、
  `high/medium` confidence 和 `input/`、`software/` 或 `runtime:` anchor。
- source path 存在性检查在
  [`task_prep.py:303`](../../ale_run/agents/ale_claw/task_prep.py#L303)。任一非 runtime 路径
  不存在时整份报告置空；这次 SEC 的两个 `*.pdf` 通配符因此让 3 条 raw finding 全部退出。
- fresh multi-turn prep-agent、cache lock、usage 和错误降级在
  [`task_prep.py:321`](../../ale_run/agents/ale_claw/task_prep.py#L321)。Prep 失败不会终止 solver。
- deployer 把同一字节写入 host `task_prep.md` 和 VM 的 `task_prep/PREP_REPORT.md`，只在主
  prompt 放报告路径，见
  [`deployer.py:497`](../../ale_run/agents/ale_claw/deployer.py#L497)和
  [`deployer.py:535`](../../ale_run/agents/ale_claw/deployer.py#L535)。

```text
public prompt + input/ + software/
  -> protocol/material fingerprint + cache lock
  -> fresh prep agent, local probes first
  -> decision=skip OR <=3 structured findings
  -> normalize fields + validate exact local paths
  -> PREP_REPORT.md outside output/
  -> writer reads report, rechecks sources, solves normally
```

### Full 中的行为

- 52/52 metadata 都是 `task-prep-v10`；50 completed report，2 empty，后两项都是 SEC。
- 22 次 fresh research、30 次 cache hit。fresh 平均 278.8 秒、116,206 input tokens、
  7.1 LLM turns、11.0 tool calls；不能用包含 cache hit 的 117.9 秒冒充冷启动成本。
- 22 个 fresh prep response 共 62 条 raw finding，59 条进入报告。3 条 SEC finding 不是被
  词法过滤，而是整份报告在 exact-path source validation 后被拒绝。
- 50/50 个拿到非空报告的 writer 都读取了完整报告；read call 均发生，138 个 source
  locator 中有 108 个被 writer 回查。两条没有 read 的记录正是 SEC empty report。
- 24 个有报告任务的 prep-only paired delta 仍为 `-.00855`（t=`-.46`）。报告成功交付不等于
  报告新增了正确真值。

### 最新具体题：Variant annotation

fresh v10 canary 的 prep-agent 用 123.7 秒、6 个 LLM 回合和 5 次本地 exec 扫描 50 条 VEP
snapshot，得到三个 task-local 事实：

1. transcript consequence 的 indel allele 可是 VEP normalized `-`/`C`，但 manifest 对
   frequency/ClinVar 明确要求 exact submitted ALT；两类 key 不能共用一个规范化函数。
2. 一个 multiallelic ClinVar record 的 `clin_sig` 混有其他 allele 的 label，必须用
   allele-specific mapping。
3. consequence priority 先于 canonical；canonical 只能 tie-break。

Canary writer 第 3 回合读取报告，初稿仍把 `max_af()` 写成 normalized allele；随后回看
manifest，把 frequency lookup 改为 `allele=alt`，并写下注释不以 `-` 替代。Canary 得分
`.793 -> .999`。

最终 full 复用了同一 protocol/material fingerprint 的报告；prep 和 combined writer 都在第
2 次 tool call 读取报告，并回查 3/3 source。两份最终 `pipeline.py` 都显式使用
`frequencies.get(submitted_alt)`，得分再次为 base `.793`、prep `.999`。verifier-only 和
combined 也为 `.999`，说明强 writer 有时能自行发现该规则；可声称的是“v10 不再系统性注入
错误 key，且 prep adoption 机制复现”，不能声称这条知识只有 prep 才能提供。

### Prep 的当前判断

保留 v10 代码但默认关闭。它已修复 v9 的稳定回归，并在 Variant、FluSight、CT 提供了
可解释候选信号；BPMN、SEC、SSE、CRF4、SAP 又显示负向或高方差。下一轮不应再做一次
`k=1` 全量，而应在机制匹配题上每格至少重复 3 次，并提高 skip 门槛。source validation
下一版可逐 finding 拒绝无效 anchor，避免两个坏路径拖掉一个有效 runtime finding，但必须
继续禁止 wildcard/模糊 locator。

## 2. Skills 是否修改、是否有价值

### 当前代码状态

两份 skill 确实修改过：

- [`deliverable-contract`](../../harness/skills/deliverable-contract/SKILL.md) 从约 520 词缩到
  194 词，删除“写完整 checklist/checker 并留在 output”的泛化要求，改成只核对公开可观测
  contract、区分 checked/failed/unverifiable。
- [`evidence-audit`](../../harness/skills/evidence-audit/SKILL.md) 从约 392 词缩到 180 词，
  只面向多源 consistency、claim verification 和 Yes/No/Unknown ledger。

它们只在显式 skills arm 中由
[`deployer.py:102`](../../ale_run/agents/ale_claw/deployer.py#L102)写入 main agent MemoryStore；
当前 v10 full 配置没有 `skills:` 字段，也没有把 skill 交给 prep 或 verifier。最新全量不是
skills 实验。

### 已有实验

25 题同协议 skills v2：

| Arm | 均分 | 相对 base | 正 / 平 / 负 | t |
|---|---:|---:|---:|---:|
| base | .6068 | - | - | - |
| skills | .5907 | -.0161 | 3 / 15 / 7 | -.84 |
| prep | .6056 | -.0012 | 4 / 17 / 4 | -.08 |
| skills + prep | .5842 | -.0226 | 2 / 16 / 7 | -1.71 |

50/50 个 skill-enabled unit 都加载成功；`deliverable-contract` 加载 48 次，
`evidence-audit` 4 次。失败不是 skill 没触发，而是大部分文本只重复强模型已有的 schema/
完整性习惯，没有独立 source truth 或新执行能力。Agora 的 `evidence-audit +.167` 和 PDE 的
contract `+.130` 是窄正例，但均为单次；SSE `-.333`、CRF4 `-.184`、Audience `-.142` 等
负例同样存在。

### 删除还是重写

- **`deliverable-contract`：从 active skill 集删除或移入 archive。** 继续改 prompt 的边际
  价值低。若保留名字，应完全重写为带脚本的 capability bundle，例如结构化 artifact 的
  schema/key-set/join/source-trace 检查，而不是 checklist。
- **`evidence-audit`：暂不删除，但保持默认隐藏。** 只在显式多源 verdict matrix、
  Yes/No/Unknown 或 consistency audit 上触发，先对 Agora/PE/Legal 做 `k>=3`。没有条件效应
  后再删除。
- **不要得出“无脚本的 method skill 必然无用”。** 更准确的门槛是：skill 必须带来模型
  原本没有的边际能力，或在明确触发子集上有重复的条件效应。工具/脚本/专有领域知识的
  先验成功率更高，但不是形式上的唯一条件。

## 3. Verifier v10 如何设计、有什么价值

### 源码与执行顺序

核心实现是 [`verifier.py`](../../ale_run/agents/ale_claw/verifier.py)：

1. Fresh builder 在 solver 前运行，只看 public prompt、`input/`、`software/`，见
   [`verifier.py:253`](../../ale_run/agents/ale_claw/verifier.py#L253)和
   [`deployer.py:466`](../../ale_run/agents/ale_claw/deployer.py#L466)。它最多注册 8 条固定
   criterion；全量语义 source comparison 最多预注册 5 个 locator。
2. [`lint_verify_spec()`](../../ale_run/agents/ale_claw/verifier.py#L163)校验 id、type、公开
   source、quote、sample budget 和 blocking 权限。v10 将所有非 `public_evidence` sample
   机械清为 `[]`，但 public-evidence 缺 locator 仍报错。
3. 类型是 `deterministic / public_evidence / proxy / unverifiable`；只有前两者可 blocking。
   Builder 还要为公开 oracle 注册 anti-copy/mixing/substitution provenance criterion。
4. Writer 完成后，[`snapshot_output()`](../../ale_run/agents/ale_claw/verifier.py#L525)复制
   `output/`、拒绝 symlink、去除写权限并记录树 hash；fresh runner 只应检查 snapshot。
5. Runner 必须先验证 source quote 能推出 requirement/check/expected；多 excerpt 分开定位，
   artifact 中 ellipsis 作为 excerpt separator，见
   [`verifier.py:321`](../../ale_run/agents/ale_claw/verifier.py#L321)。
6. [`normalize_verdict()`](../../ale_run/agents/ale_claw/verifier.py#L608)要求 exact criterion id、
   source status/evidence 和 verdict evidence；任何 ambiguous/contradicted/missing 由代码强制
   变成 unverifiable，并删除 repair hint。
7. Runner 后重新 hash snapshot 与 writer 原 output，见
   [`verifier.py:683`](../../ale_run/agents/ale_claw/verifier.py#L683)。只有 supported blocking
   fail 能进入 [`build_repair_prompt()`](../../ale_run/agents/ale_claw/verifier.py#L741)。本轮
   配置是 0 repair，所以只审计。
8. hidden reference 在整个 agent/verifier 流程结束后才 stage，见
   [`lifecycle.py:449`](../../ale_run/orchestration/lifecycle.py#L449)。

```text
public task
  -> fresh builder -> fixed, cached public spec
  -> writer
  -> hash + read-only snapshot
  -> fresh runner -> source status + observed/expected/evidence
  -> code normalization -> audit record
  -> (disabled here) bounded repair
  -> hidden reference -> unchanged ALE evaluator
```

### 最新具体题 A：FluSight

combined spec 注册 8 条 criterion。Runner 全量验证：唯一 `submission.csv`、8 列顺序、212
行、template key set、日期公式、636 个非负整数和 212 个 interval order，6 项均有可复现
command output并 pass。

两项没有伪装成 pass：

- “input 未修改”要求 solve 前 baseline，但 builder 没真正保存 baseline，runner 返回
  unverifiable。
- 未来四周 finalized outcome 隐藏，WIS/coverage 无 public truth，runner 返回 unverifiable。

因此 overall 是 unverifiable，而 ALE 得分仍为 `.7210`。这正是 public-contract auditor 的
正确边界：能证明 artifact 结构成立，不能证明未来预测质量。

### 最新具体题 B：CT provenance

combined writer 得到 SSIM `.96084`、MSE `3.89e-7` 和 ALE `1.0`。v6 canary 曾出现整图复制
或 32% reference mixing；v10 spec 因此注册 reconstruction provenance。Runner 从 public
sinogram 和 JSON geometry 独立重跑 LEAP FBP，重跑数组与交付数组 `max_abs_diff=0`，证明
这次是真重建而不是 reference 混合。

这说明 v10 verifier 有真实审计价值；但它发生在 writer 结束后、没有 repair，不能解释为
verifier 帮 writer 找到了参数。combined 的成功是独立 rollout，prep-only 同题仍为 0。

### Full 审计质量

52/52 builder 都选择 `verify`，没有一次 `skip`；26 题两臂 fingerprint 和 spec SHA 全相同。
344 条 criterion：

| 维度 | 数量 |
|---|---:|
| deterministic / public_evidence / unverifiable | 290 / 52 / 2 |
| source supported / ambiguous / contradicted / missing | 196 / 145 / 2 / 1 |
| verdict pass / unverifiable / fail / error | 180 / 156 / 6 / 2 |
| overall pass / unverifiable / fail / error | 5 / 38 / 4 / 5 |

6 个 fail 是 BPMN supply 两臂各 2 条真实 topology/role 缺口，以及 Legal 两臂各 1 条引文
omission 问题。与最初 full 的 34 fail、13 unverifiable 相比，v10 将 source 不足的项目大量
降为 unverifiable，明显减少误阻断，但也牺牲可操作 recall。

明显限制：

- CRF1 两个 0 分 artifact 都 overall pass；SAP `.25` 也 pass。固定 5-8 条 spec 没有覆盖
  hidden evaluator 的全部质量面。
- 145/344 source ambiguous，且 52/52 spec 全 verify，说明 builder 仍过度注册、几乎不会
  skip。source gate 在保守止损，但 builder precision 需要提高。
- American 与 Moodle 共 4 个 runner 调用 task runtime wrapper 时更新了原 output 下的
  `.agent_runtime_env` 或 `.runtime/.venv`。双 hash 捕获了副作用并返回 error，这是完整性检查的价值，
  也证明 runner 必须迁到独立容器，不能只靠 prompt。
- Bias verifier 有两个 runtime reproduction criterion error。错误没有变 pass，也没有进入
  repair，但仍消耗大量上下文。
- 平均 builder 76.5 秒/27.8k input tokens；runner 223.4 秒/95.2k input tokens。fresh builder
  实际约 153.1 秒/55.5k input tokens。没有已验证 repair uplift 时，这个成本不适合默认开启。

## 4. v10 相比最初系统优化了什么

| 问题 | 初版证据 | v10 改动 | 验证 |
|---|---|---|---|
| prep 有效 finding 被词表误删 | 79 raw 仅 26 retained | v8 起删除 lexical prescriptive filter，最多 3 条结构化 finding | v8 canary 27/27 retained；本 full 的 3 条未保留项明确是 SEC report-level path rejection |
| writer 未稳定拿到完整报告 | 早期存在截断/注入不清 | 报告同字节写 host/VM，prompt 只给路径 | 本 full 50/50 非空报告被完整读取，108/138 source 被回查 |
| outcome heuristic 没有公开验证 | FluSight 用季节走势猜方向 | modeling heuristic 必须在 task-local holdout/backtest 优于 named baseline | v9 做 1,040 点 backtest；persistence MAE 162.98 优于 linear 225.09/growth 751.13，随后 canary WIS 132.10 -> 116.84 |
| 上游惯例覆盖 task-local key | Variant 三轮稳定 `.999 -> .793` | original/submitted/exact key 无本地 mapping 时禁止 alternate lookup | v10 canary 与 full 均 `.793 -> .999`，最终代码明确 `get(submitted_alt)` |
| smooth/coarse search 漏离散 endpoint | CT 未测 359.9xx/360 单侧分支 | exact endpoint 先比较小单侧 perturbation | protocol 已实现；本 full CT 的真重建成功是候选机制信号，但 prep-only 仍 0，尚无稳定因果验证 |
| source quote 存在但不推出标准 | TCGA 15/16、CRF origin false positive | runner 对 requirement/check/expected 全字段做 entailment；非 supported 强制 unverifiable | source ambiguous 145、contradicted 2；旧 TCGA/CRF 错误不再 fail |
| 多 excerpt/ellipsis 被强制连续 | Legal 明确误报 | 多 excerpt 独立定位；ellipsis 分片 | v7-v9 Legal 窄复验将旧误报变 supported+pass；无 quote 支持的限制仍 ambiguous |
| 公开 metric 可被 reference copy/mix 利用 | CT v6 repair 复制/混合 reference | builder 注册 provenance check | 本 full CT 独立 FBP 与交付逐元素一致，合法 pass |
| deterministic criterion 带 sample 导致整 spec error | v9 American full 启动即 lint error | v10 对非-public-evidence sample 清空 | 52/52 spec 成功；American 两臂 7 条 deterministic sample 全空 |
| symlink 让 snapshot 整体失败 | 初版 American 两臂 snapshot error | 拒绝并记录 symlink，snapshot/output 前后双 hash | symlink 不再导致 cp error；双 hash反而发现 4 次原 output 副作用 |

实验结论不是“v10 提分显著”。旧 full prep paired `+.00093`，新 full `-.00977`；两轮都在
噪声内。v10 的已验证价值是：消除稳定有害路径、减少 verifier false positive、提供可审计
provenance。是否提高总体 ALE 仍未证明。

## 5. 对早期 Codex 判断的 Judge

### 值得采纳

| 早期判断 | Judge |
|---|---|
| “不是 skills 机制无用，而是当前两个通用提示 skill 价值低” | 正确。50/50 load 成功、总体负向只否定当前实现，不否定 future capability skill。 |
| 条件效应应在匹配任务上报告 | 正确。15 个 tie 和多处 floor/ceiling 会稀释窄 skill；但条件集必须 solve 前定义，不能按得分事后挑题。 |
| `deliverable-contract` 触发过宽，`evidence-audit` 应窄门控 | 正确。前者建议退役，后者只做 `k>=3` 实验。 |
| MarkItDown 不应只做一个“请使用它”的提示 skill | 正确。converter 是工具 backend，不是自动产生 locator/source truth 的方法。 |
| `document-evidence-index` 比 MarkItDown skill 更合理 | 正确。应输出 page/sheet/cell/table locator、source SHA、extractor version，并优先题目自带 extracted text。 |
| deterministic criterion 应由固定代码执行 | 正确且尚未实现，是 verifier v11 核心。当前 LLM runner 仍在临时写检查代码。 |
| source quote 应机械定位并哈希 | 正确且仅部分实现。v10 由 runner 判断 entailment，harness 仍未机械证明 quote 存在。 |
| runner 应在独立只读容器 | 完全正确，且本 full 的 American/Moodle 原 output 变化给出了新实证。 |
| 只有确定性、可复现 fail 才可自动 repair | 正确。v6 的 BPMN/SEC/CT 已证明通用 LLM repair 不安全；当前保持 0。 |
| 不做泛化医疗规范 skill | 正确。Variant 证明 task-local contract 必须压过领域惯例。 |

候选 capability 的优先级也基本合理，但要调整归属：

1. `structured-artifact-reconcile`：值得做，必须带实际 parser/check scripts；同一检查若用于
   verifier，要在独立环境重新执行，不能信 writer 生成的绿色结果。
2. `bpmn-static-analyzer`：高价值。先固定 XML/图算法，task-specific role/dataflow 规则来自
   public config；不能把某题 BPMN 语义硬编码为通用规范。
3. `document-evidence-index`：值得 prototype。MarkItDown 只作可选 backend。
4. `sec-financial-lineage`：高价值，重点是 field -> filing -> page -> table -> row -> unit/year，
   不是把 100 份 10-K 全文塞入上下文。
5. `public-oracle-loop`：适合 CT，但必须同时执行 anti-copy/mixing provenance；公开 metric
   达标本身不证明 derivation。

### 需要谨慎或已经过时

- “真正值得保留的 skill **必须**带工具/脚本/领域能力”方向对，但措辞过强。窄 method skill
  也可能有条件价值；门槛应是新增边际信息/能力或重复条件效应，而不是文件形式。
- “MarkItDown PDF 只是简单 pdfplumber/pdfminer”需要更新。当前 main 已逐页识别表格/表单，
  再回退 pdfminer；但 built-in 输出仍把 page chunks 合并，没有稳定 page marker，所以 ALE
  locator 结论不变。见 [官方 README](https://github.com/microsoft/markitdown)和
  [当前 PDF converter](https://github.com/microsoft/markitdown/blob/main/packages/markitdown/src/markitdown/converters/_pdf_converter.py)。
- DOCX 仍用 [Mammoth](https://github.com/microsoft/markitdown/blob/main/packages/markitdown/src/markitdown/converters/_docx_converter.py)，
  XLSX 仍用 [pandas/openpyxl](https://github.com/microsoft/markitdown/blob/main/packages/markitdown/src/markitdown/converters/_xlsx_converter.py)。
  官方当前明确 plugins 默认关闭、OCR plugin 依赖 LLM client、local-only 场景应调用
  `convert_local()`；因此固定版本、关闭 plugins、限制 workspace path 的建议仍正确。
- “symlink snapshot 尚未修”已经过时。v5/v10 已拒绝并记录 symlink；当前更大的问题是 runner
  可通过 task wrapper 改原 output。
- “normalize_verdict 只检查非空”已部分过时。v10 新增 source status/evidence，并由代码强制
  non-supported -> unverifiable；但 evidence 的事实仍由 LLM 产生，没有机械复算。
- “不再输出全局 pass”只完成了一半。当前有 pass/fail/unverifiable/error 四态，但 `pass`
  仍容易被误读为完成证书；API/文档应改名 `registered_contract_pass`，并始终带 coverage。
- 早期建议的“最多一次 repair”现在仍不应直接开启。先完成隔离、机械 deterministic executor
  和 `k>=3` precision/repair 收敛测试，再单独显式 opt-in。

两条外部设计参考值得保留的是 fresh role、artifact evidence、structured feedback 与有限停止，
而不是“LLM grader 天生可靠”的假设：

- [Claude outcome grader](https://github.com/anthropics/claude-cookbooks/blob/67ce644d33e5933f0bcc0b6eb4113df41bbf3a8f/managed_agents/CMA_verify_with_outcome_grader.ipynb)
- [Codex iterative repair loop](https://github.com/openai/openai-cookbook/blob/9fa55b8cecba8c9c543d11f2cf08339a29112be7/examples/codex/Build_iterative_repair_loops_with_Codex.ipynb)

## 决策与下一步

1. 冻结 v10 结果；prep、verifier、skills 继续默认关闭。
2. Verifier v11 先做执行隔离：独立容器只读挂载 public input 和 snapshot，不挂原 output，
   默认断网；runtime cache/venv 全指向独立 `/tmp`。
3. 把 deterministic criterion 编译/实现为固定代码或小 DSL；LLM 只做 bounded
   public-evidence 取证，默认 non-blocking。机械定位 source quote，并记录 public input 的
   pre/post hash。
4. 提高 builder skip 门槛，输出 `registered_contract_pass + coverage`，不再让 52/52 题都
   机械进入昂贵 runner。
5. Prep v11 只做 source-validation 粒度和 skip gate 改善，不再改 exact-key 语义；在
   Variant、FluSight、CT、BPMN、SEC 每格 `k>=3` 前向复验。
6. 退役当前 `deliverable-contract`；优先 prototype `structured-artifact-reconcile`、
   `bpmn-static-analyzer` 和带 locator 的 `document-evidence-index`，每个 capability 单独消融。

验证：pgl 定向测试 `37 passed`；相关 Python 文件 ruff 全绿。完整仓库测试为
1050 passed、3 skipped，另有 12 个与本改动无关的既有失败（旧 milestone/context/keyless
secret helper 预期），未为本工作修改。
