# Canary 后协议迭代：Prep v10 / Verifier v10

更新于 2026-07-20。本文记录 10 题 prep v8 / verifier v6 canary 之后的窄复验，解释为何
最终全量使用 `task-prep-v10` 与 `public-verifier-v10`。这些版本不是按分数反复调参；每次
升级都对应一条可复现的轨迹失败，下一轮只验证该失败是否消失。

机器结果：

- [`task_prep_v9_outcome_canary/`](task_prep_v9_outcome_canary/)
- [`task_prep_v10_variant_canary/`](task_prep_v10_variant_canary/)
- [`verifier_v7_quote_canary/`](verifier_v7_quote_canary/)
- [`verifier_v8_quote_canary/`](verifier_v8_quote_canary/)
- [`verifier_v9_quote_canary/`](verifier_v9_quote_canary/)

## Prep：v8 -> v9 -> v10

### v9 的有效边界

v8 FluSight 把两个历史冬季的走势直接交给 writer，没有验证这种 analog 是否优于简单方法。
v9 要求 unavailable outcome 的 modeling heuristic 必须先在 task-local holdout/backtest 上，
用任务相关公开指标优于明确 baseline。

v9 prep agent 随即执行 5 个 December origin、52 个 jurisdiction、4 个 horizon 的 1,040 条
预测回测：

| 方法 | MAE |
|---|---:|
| persistence | 162.98 |
| recent 4-point linear | 225.09 |
| compounded median growth | 751.13 |

最终报告只交付该回测、36 个缺失值的分布及 US/州合计的小误差，不再猜未来 peak/direction。
同轮 FluSight base `.6611`、prep `.7003`；WIS 为 `132.10 -> 116.84`，coverage 为
`.697 -> .952`。这仍是单次 rollout，不证明总体收益，但报告内容与采用链已经可验证。

v9 Agora 报告只保留 San José cached text 中 page header、断词和 substring 陷阱，没有输出
任何 proposition 标签或最终分类。base `.5294`、prep `.4979`；负差不改变内容边界判断。

### v9 在 Variant 上仍失败

v9 尝试规定：task-local rule 锚定 submitted/exact key 时，不得建议 upstream
normalization。但 prep agent 只把措辞改成“representation mismatch”，仍交付 deletion
的 `-` frequency key 与阈值影响。writer 读取后继续用 normalized indel allele，结果再次为：

| Arm | Score |
|---|---:|
| base | .999 |
| prep v9 | .793 |

这与历史三轮 `-.206` 同路径，说明“不推荐但仍提示”不足以阻断干预。

### v10 的修复与验证

v10 把规则改为：local rule 指定 original/submitted/exact key 且没有另一条 local rule 明示
mapping 时，不能把 alternate representation 当作新的 lookup key。新报告明确区分：

- transcript consequence 可使用 VEP 自己的 indel 表示；
- frequency/ClinVar 必须遵守 manifest 的 exact submitted ALT；
- canonical 只能在 consequence priority 相同后 tie-break。

writer 轨迹给出了直接干预证据：初稿准备通过 `vep_alt()` 规范化 frequency key，随后依据
报告与 manifest 把 `max_af()` 改为 `allele=alt`，并注释不得用 `-` 替代。结果为：

| Arm | Score |
|---|---:|
| base | .793 |
| prep v10 | .999 |

两臂恰好反转不能当总体效应，但内容、代码修改和 evaluator 结果三者一致，v10 通过针对性
门槛。最终 full 会重新研究全部任务，因为 protocol fingerprint 已变，不复用 v8/v9 cache。

## Verifier：v6 -> v7 -> v8 -> v9 -> v10

### v7：provenance 与多段 source quote

v6 CT repair 暴露两条 leakage：一臂整图复制公开 reference，另一臂把 reconstruction 与
reference 按 `.68/.32` 混合。两者都让公开 MSE/SSIM criterion pass；前者被 anti-copy gate
拒绝为 0，后者绕过 evaluator 得 1。v7 builder 因此要求：公开 oracle 用于评估派生 artifact
时，必须注册 copying/direct mixing/substitution provenance check，不能把 metric 当 derivation
证明。

v7 同时修正 runner 对 `source_quote` 中多段摘录的处理：逐 excerpt 定位，不要求合并块是
一个连续 substring。Legal 复验中 7 条 source status 全部 `supported`，证明 quote 本身已能
定位；但 runner 仍把 artifact 中 `……` 连接的证据当成必须连续出现，保留了旧误报。

### v8：全 criterion source entailment

v8 要求 source quote 不只推出 `requirement`，还必须推出 `check` 与 `expected` 中的每个限制；
新增 exactness、contiguity、order、tolerance 都必须有公开原文支持。Legal 复验中，builder
把 exactly-one-file 偷加成 non-empty，runner 正确返回 `ambiguous -> unverifiable`，说明该
gate 生效。

但 artifact quote 的 `……` 仍被当作源字符：17/21 个 composite quotations 通过，4 个因
省略号连接非连续片段被 fail。这里不是 source entailment 问题，而是 artifact quotation
解析问题。

### v9：ellipsis 是 excerpt separator

v9 只新增一条 runner 规则：除非公开 contract 明示 exact contiguous，artifact quotation 中
的 ellipsis/omission marker 分隔多个 excerpt；每个非空 fragment 在同一 cited source 独立
定位，不能仅因 marker 不在原文而 fail。

最终 Legal 复验保留 `evidence.verbatim.on.cited.page` 标准，runner 的结果为：

- 16 个 quotation 直接匹配；
- 1 个含 `……` 的 Announcement page 2 quotation 被拆为 name/share/price fragments，逐段
  匹配并结合公开 PDF page 验证；
- criterion 为 `supported + pass`；
- 另一个 manifest-page criterion 因 registered quote 没包含 manifest 约束，被正确降为
  `ambiguous + unverifiable`；
- overall `unverifiable`，0 repair。

旧 exact-contiguous 误报因此消失，而 source 加严仍被阻断。

### v10：无意义 sample 机械归一化

首次启动 26 题 full 时，American option builder 给 deterministic criterion 填了 sample，
v9 lint 让整个 spec error。确定性 criterion 本来就可检查全 corpus，这个 sample 不影响语义，
因此 v10 对所有非-public_evidence 类型机械设为 `sample=[]`；public_evidence 缺 fixed locator
仍然报错。Incomplete v9 full 的 3 个 run 被保留，未混入最终结果。

新 full 的 American option 两个 verifier arm 均成功生成 7 条 deterministic criterion，所有
sample 长度为 0，证明归一化生效。最终 verifier protocol 为 v10。

## 最终全量协议

```yaml
arms: [base, prep, verifier, prep_verifier]
prep:
  max_steps: 15
verifier:
  max_steps: 30
  max_repairs: 0
run:
  concurrency: 3        # per arm; 12 total
  api_endpoints: []     # one shared endpoint
```

Interpretation 固定如下：

1. prep effect 用 2x2 两个独立 writer pair 估计，同时报告 paired-vs-base；单题只结合轨迹解释。
2. verifier 在 `max_repairs=0` 时不改变 artifact，任何分数差都是 rollout noise；只评估 finding
   precision、source-status 与 coverage。
3. `overall=pass` 不是完成证书；MARC、CRF1、SAP 已证明固定 5--8 条 criterion 有 coverage
   上限。
4. CT reference mixing 等 benchmark leakage 单列为 invalid intervention，不能算提分。
5. 当前通用 skills 不进入实验轴；旧 50/50 load 成功但净效应为负，只证明这套通用 skills
   不应默认加载，不证明所有未来 task-specific skill 永远无用。
