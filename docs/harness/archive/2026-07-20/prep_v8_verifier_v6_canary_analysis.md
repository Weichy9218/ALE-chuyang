# Prep v8 / Verifier v6 Canary 深度分析

更新于 2026-07-20。实验在 pgl 使用同一 `openai/gpt-5.6-sol` endpoint，10 题、四臂、
40/40 unit 均 `completed`。Canary 的 verifier 显式开放一次 repair，用于观察反馈闭环；
最终全量不会沿用该设置。机器表在
[`prep_v8_verifier_v6_canary/`](prep_v8_verifier_v6_canary/)，排除 CT leakage 的复算在
[`prep_v8_verifier_v6_canary_no_ct/`](prep_v8_verifier_v6_canary_no_ct/)。

## 决策

1. **Prep v8 修好了 v7 的信息丢失，但没有修好 finding 选择。** 20/20 个 prep unit
   `completed`；10 个 fresh agent 生成 27 条 finding，27/27 全部进入报告。两个独立 writer
   共 20/20 在第 1--4 次工具调用读取报告，并回查 45/54 个 source。Variant 仍把
   task-local `submitted ALT` 改写成 VEP normalized allele，稳定造成 `0.999 -> 0.793`；
   FluSight 仍交付未经 backtest 的季节轨迹启发式；CT 又漏掉精确角跨度的一侧分支。
2. **Verifier v6 的 source gate 有效降低误报。** TCGA 的“15 字符”与 16 字符示例被标为
   `contradicted -> unverifiable`；Variant 的规则推导 2 个 reportable 与公开 manifest 的 3 个
   被标为 `contradicted -> unverifiable`。Legal 的多段 quote 因旧 runner prompt 被误判
   `missing`，但同样没有触发 repair；该 quote 解析缺陷由后续 v7--v9 窄复验逐层修复。
3. **任何通用自动 repair 都不安全。** BPMN repair 解决旧失败同时引入新失败；SEC 把
   下游公式修到自洽却传播错误上游抽取；SAP 修复了随机数复现但分数仍 `.25`；TCGA 修复
   脚本失败后仍 `.84`。CT 两臂分别把公开 reference 整图复制或与 reconstruction 混合，
   verifier 因 `MSE/SSIM` 全绿而 pass；前者被 anti-copy gate 判 0，后者利用 grader 漏洞得 1。
   后者是 benchmark leakage，不是有效提分。
4. **原始正均值不可解释。** 原始 factorial 中 prep `+0.0355`、verifier `+0.0471`，但 CT
   reference mixing 单题为两个主效应各贡献 `+0.05`。排除 CT 后，prep `-0.0161`
   (`t=-0.96`)、verifier `-0.0033` (`t=-0.18`)，均无正信号。因此最终配置为 prep v10、
   verifier v10、`max_repairs=0`；verifier 只审计，不修改 artifact。后续窄复验见
   [协议迭代分析](prep_verifier_protocol_iteration_analysis.md)。

## 分数

| Task | base | prep | verifier | combined | 关键解释 |
|---|---:|---:|---:|---:|---|
| BPMN supply | .8362 | .8538 | .8119 | .8129 | prep 提供了真实分支事实；两次 repair 都 fail，并引入新失败。 |
| Legal M&A | 0 | 0 | 0 | 0 | 四臂都漏 1 个 target；source gate 阻止多段 quote 误报触发修复。 |
| SEC 10-K | .7103 | .6951 | .7103 | .6482 | combined repair 重算错误上游 extraction 后的 QA，分数继续下降。 |
| MARC | .2 | .2 | .2 | .2 | prep 信息高质量，verifier 8/8 pass；隐藏评分缺口完全未覆盖。 |
| CRF1 | 0 | 0 | 0 | 0 | verifier 8/8 pass；公开 collected-only 解释与隐藏 reference 目标不一致。 |
| CT geometry | 0 | 0 | 0 | 1 | combined 的 1 来自 32% reference mixing，属于无效 leakage。 |
| FluSight | .7175 | .7461 | .7284 | .7061 | 同一报告在两次 writer rollout 上一正一负；prep factorial effect 仅 `+.0032`。 |
| SAP | .25 | .25 | .25 | .3786 | combined 独立 writer 多通过 power curve；全 pass 仍只 `.3786`。 |
| TCGA | .84 | .84 | 1 | .84 | v6 正确降级公开矛盾；`1` 是独立 writer rollout，不是 verifier 修改。 |
| Variant | .999 | .793 | .793 | .793 | normalized-allele 路径再次稳定丢 `.206`；v6 识别公开规则/count 冲突。 |

原始与去除 CT 的 2x2 结果：

| 估计 | 原始 10 题 | 去除 CT 9 题 | 解释 |
|---|---:|---:|---|
| prep main effect | +.0355 | -.0161 | 原始值被 CT combined 的非法 +1 抬高。 |
| verifier main effect | +.0471 | -.0033 | repair 的 apparent gain 全来自 CT leakage。 |
| interaction | +.1060 | +.0067 | 去除 CT 后回到近零。 |
| prep vs base | -.0175 | -.0194 | 主要由 Variant `-.206` 驱动。 |

这些都是单次 rollout 的 10 题 canary，不用于宣称总体效应；它们用于判定机制是否安全。

## Prep 轨迹

v8 删除了 v7 的 prescriptive 词表并限制为最多 3 条。结果证明 handoff 已经可靠：

- 10 个 fresh prep 平均 154.25 秒、80,143 input tokens；另 10 个 combined unit 命中缓存。
- 10 题共 27 条 raw finding，27 条全部保留，不再发生 `must/use/map` 误删。
- 20/20 个 writer 读取报告；报告 read call 均为 1--4；source 回查 45/54。
- 所以分数问题不能再归因于 filter、cache 或 writer 未读取。

三种 finding 选择失败决定了 v9/v10 的窄改动：

1. **未经验证的 outcome heuristic。** FluSight finding 只比较两个历史冬季轨迹，没有
   rolling-origin backtest。prep writer 的 WIS 从 110.13 改善到 98.99，但 combined writer
   用同一报告得到 114.56；单次方向不稳定。v9 只允许已在公开历史 holdout/backtest 上、
   用任务相关指标优于明确 baseline 的 modeling heuristic。
2. **上游表示覆盖 task-local key。** Variant finding 建议把 submitted deletion ALT 换成
   VEP `-`，writer 随即把三个 indel AF 改写，并复现 `.793`。v9 的“不建议 substitute”仍
   被中性化措辞绕过；v10 要求 frequency/ClinVar 明确保留 manifest 的 exact submitted key。
3. **粗网格遗漏单侧离散分支。** CT base 和 prep 都扫描连续 SAD/SDD/offset，甚至粗扫
   358--362 度，却没有比较精确 endpoint 与极小单侧扰动。v9 明确要求 API 合法端点先做
   one-sided perturbation，再做 smooth/coarse search。

## Verifier 与 Repair

20 个 verifier unit 共 191 个 round-level criterion：

- source status：178 `supported`、2 `ambiguous`、7 `missing`、4 `contradicted`。
- verdict status：152 `pass`、20 `fail`、19 `unverifiable`。
- 7 次 repair transition，所有 snapshot hash 都变化。

逐类结果：

| Repair | round 0 -> round 1 | ALE 结果 | 判断 |
|---|---|---|---|
| BPMN verifier | 4 fail -> 2 fail，新增 anchors fail | .8119 | 修复振荡；source status 也不稳定。 |
| BPMN combined | 4 fail -> 4 fail，2 resolved / 2 new | .8129 | 无净闭环。 |
| SEC combined | 1 fail -> unverifiable | .6482 | 下游自洽导致错误值传播。 |
| SAP verifier | 2 fail -> pass | .25 | 公开 reproducibility 真修复，隐藏主要缺口未覆盖。 |
| TCGA combined | 1 fail -> unverifiable | .84 | 脚本修复不改变隐藏得分。 |
| CT verifier | SSIM fail -> pass | 0 | 整图复制 reference，被 anti-copy gate 拒绝。 |
| CT combined | SSIM fail -> pass | 1 | 32% reference mixing 绕过 grader，非法 apparent gain。 |

`overall=pass` 的 coverage false-negative 同样重复：MARC `.2`、CRF1 `0`、SAP `.25/.3786`
都出现全 pass。v7 因此新增 public reference/oracle provenance criterion：当任务要求派生、
重建、校准或变换 artifact 时，检查 copying、direct mixing 或 substitution，不能把 metric
通过当 derivation 证明。它仍然是 audit finding，不授权自动修复。

## 成本

| Arm | 平均成本 USD | 相对 base | 平均时长 s | 相对 base |
|---|---:|---:|---:|---:|
| base | .549 | - | 892 | - |
| prep | .718 | +31% | 1,213 | +36% |
| verifier | .781 | +42% | 1,267 | +42% |
| combined | .852 | +55% | 1,528 | +71% |

Fresh verifier builder 平均 125.58 秒、47,084 input tokens；runner 每个 artifact 都重新运行。
在没有稳定分数收益时，这些层不应默认开启。全量保留四臂是为了与历史结果同协议比较，
不是建议生产默认启用。

## 全量门槛

全量前的三项门槛均已在 pgl 闭合：

1. Prep v9 在 FluSight 先执行 1,040 点 holdout/backtest，并且 Agora 不输出分类答案。
2. Prep v9 在 Variant 仍复现 `.793`；prep v10 让 writer 从 normalized key 改回 exact
   submitted ALT，同轮 `.793 -> .999`。
3. Verifier v7--v9 最终让 Legal ellipsis quotation `supported + pass`，并把无 quote 支持的
   manifest 限制降为 `ambiguous + unverifiable`；v10 再把非-public-evidence sample 机械清空。
   所有最终复验与全量均 `max_repairs=0`。

通过后运行 26 题四臂全量，使用同一 endpoint；报告同时给出 raw、去除 evaluator/path
失败的 paired 结果，以及 verifier audit coverage，绝不把 audit-only 臂的 rollout 差异
解释为 verifier 因果效果。
