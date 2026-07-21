# Prep / Verifier Smoke 分析

更新于 2026-07-19。实验在 pgl 上运行 5 道有明确历史问题的任务，每个 task/arm 一次：
SEC 10-K、TCGA LUAD、Variant annotation、FluSight 和 CT geometry。单次 rollout 只用于
判断机制和安全边界，不用于声称稳定提升。

## 结论

Verifier 的独立架构有价值，但当前 LLM builder/runner 不应默认驱动自动修复。它能可靠
重算公开 schema、公式、源文件样本和 CT 的 SSIM/MSE，也能把不可见的未来 outcome 标成
`unverifiable`；同时，TCGA 暴露了明确 false positive：runner 在证据中承认“first 15
characters”和 16 字符示例互相矛盾，仍把 16 字符 artifact 判为 fail。最终配置因此使用
`verifier_max_repairs=0`，保留独立审计，repair 只作为逐题验证后的显式 opt-in。

Prep v7 的 smoke 均分高于 base，但增益全部由 TCGA 一题贡献，FluSight 明显下降，不能据此
默认开启。Variant 的 v5 回归已消失，CT prep 正确选择沉默。

| 臂 | 均分 | 相对 base | 正 / 平 / 负 |
|---|---:|---:|---:|
| base | 0.6603 | - | - |
| prep | 0.6756 | +0.0152 | 1 / 2 / 2 |
| verifier | 0.6494 | -0.0109 | 0 / 3 / 2 |
| prep + verifier | 0.6144 | -0.0459 | 0 / 3 / 2 |

这里的 verifier 两臂是审计模式，runner 不修改 artifact。它们与 base 的得分差主要是单次
solver rollout 波动，不能解释成 verifier 的因果效果。真正可比较的是 verifier 的 finding
是否有公开证据、是否误报、是否正确拒绝不可验证目标以及资源成本。

## 逐题结果

| 题目 | Base | Prep | Verifier | Prep + verifier | 主要观察 |
|---|---:|---:|---:|---:|---|
| SEC 10-K | 0.6973 | 0.6971 | 0.6919 | 0.6319 | 公开 PDF 抽样能发现 XOM EPS；shape 通过不代表财务值正确 |
| TCGA | 0.8400 | 1.0000 | 0.8400 | 0.8400 | prep 单次正例；15/16 字符矛盾产生 verifier false positive |
| Variant | 0.9990 | 0.9990 | 0.9990 | 0.9990 | prep 回归消失；一条 builder lint 失败，另一条完整通过 |
| FluSight | 0.7653 | 0.6817 | 0.7160 | 0.6011 | 结构可验证，未来 WIS/MAE 不可验证 |
| CT geometry | 0.0000 | 0.0000 | 0.0000 | 0.0000 | verifier 准确报告 SSIM 约 0.9033，不能补出缺失搜索分支 |

### SEC 10-K

预注册 spec 对 100 个 extraction、schema、manifest metadata、数值类型、QA 公式和 run-2
一致性做全量确定性检查，并固定 5 个 PDF/field locator。早期 repair 试验曾正确修复 XOM
2024 basic EPS 和两条 JNJ pretax/operating-income 误映射，修复后公开抽样通过，但得分从
同轮 base `0.6973` 变为 `0.6868`，没有收益。

最终 audit-only combined 又发现 XOM EPS 缺失和 QA 与当前 normalized extraction 不一致。
后者说明仅按派生数据重写 QA 可能把上游 extraction 错误继续传播；即使 finding 可复算，
也不等于适合自动 repair。

### TCGA LUAD

Prep 的三个本地事实确有信息增量：GDC 同一样本存在重复文件、病例可能有多 diagnosis、
以及输出 contract 的 15/16 字符矛盾。prep-only 从 `0.84` 到 `1.0`，但 combined 回到
`0.84`，单次结果不能证明稳定因果。

同一个 verifier spec 在两臂的 fingerprint 和 SHA 完全一致。verifier-only 对 stage mapping
引用不完整返回 `unverifiable`，这是正确拒绝；combined 则一边指出 15/16 字符冲突，一边
fail 16 字符 artifact。这是直接 false positive，也是自动 repair 默认关闭的决定性证据。
两条 artifact 最终都为 `0.84`，公开检查无法看到隐藏 PH-test wrapper cap。

### Variant Annotation

Prep v7 只保留 task-local JSONL 事实，没有再用上游 normalized-allele 惯例覆盖 manifest，
两条 prep-on 路径均为 `0.999`。verifier-only builder 因 `public_evidence` criterion 没有固定
sample 被 lint 拒绝，solver fail-open；combined 的独立 builder 生成合法 7 项 spec，并从
公开 JSONL 全量重算 AF、ClinVar、reportability 和 reportable subset，全部通过。

这说明检查本身有效，但 LLM builder 的单次稳定性还不够：相同 task fingerprint 的一个
builder 失败、另一个成功，不能把 builder 成功假定为必然。

### FluSight

Verifier 正确检查唯一 `submission.csv`、212 行、精确 template key set、非负整数和区间
单调性；offline provenance 和未来 outcome quality 均为非 blocking `unverifiable`。两条
结构都 pass，但分数不同且都未超过 base。未来 finalized admissions 在 solve 时不可见，
任何把 WIS/MAE 反馈给 repair loop 的实现都只能是泄漏或猜测。

Prep 的季节分支、三个州的缺失分布和 North Dakota 零边界都有本地证据，但单次得分下降；
这些事实没有形成更好的预测策略。

### CT Geometry

Spec 直接重算公开 `reference_image.npy` 的 shape、MSE 和 SSIM。两条 verifier 路径的 MSE
约 `1.05e-6`，满足 `<=4e-6`；SSIM 分别约 `0.90330` 和 `0.90329`，低于 `0.95`，与任务
0 分完全一致。Prep v7 输出 empty，避免再用不完整先验锚定 writer。

Verifier 只能准确说明“尚未完成”。Writer 已经反复计算同一指标，失败原因仍是没有探索
359.9xx/360 度附近的离散 weighting 分支；再次回传阈值不增加新信息。

## Judge 迭代

1. 初版 SEC spec 要求逐字段检查整个 100-file corpus，超出 runner 的诚实覆盖能力；改为
   全量确定性检查加全 spec 最多 5 个固定 public-evidence locator。
2. 第二版出现从字段共现推导 fiscal-year 关系的 false positive；加入逐 criterion
   `source_quote`、500 字符上限和“引用必须直接推出 requirement”。一次超长 quote 被 lint
   拒绝，促使上限进入 builder 输出协议。
3. v4 在 SEC 得到可复现的真实局部错误，但 TCGA 仍对公开材料自身的矛盾产生 false
   positive。继续叠 prompt 规则不能建立可靠 gate，因此停止调 prompt，默认 repair 改为 0。

失败样本均保留在 pgl 的 `.logs/ale/verifier_smoke` 归档目录中，没有被覆盖。

## 资源和审计完整性

- 20/20 个最终单元 completed 且有有效分数。
- 10 个 verifier-on 单元中，9 个运行 runner，1 个 Variant builder 被 lint 拒绝；0 次 repair。
- 5 题中 4 题的 verifier/combined spec fingerprint 和 SHA 一致；Variant 因第一条 builder
  失败而没有可比较 spec。
- 平均时长：base `790.2s`、prep `942.5s`、verifier `943.9s`、combined `1025.1s`。
- verifier 相对 base 平均增加约 `153.7s`；combined 相对 prep 增加约 `82.7s`。

架构分别参考 [Claude outcome grader](https://github.com/anthropics/claude-cookbooks/blob/67ce644d33e5933f0bcc0b6eb4113df41bbf3a8f/managed_agents/CMA_verify_with_outcome_grader.ipynb)
的独立 artifact grader，以及 [Codex iterative repair loop](https://github.com/openai/openai-cookbook/blob/9fa55b8cecba8c9c543d11f2cf08339a29112be7/examples/codex/Build_iterative_repair_loops_with_Codex.ipynb)
的 review/repair/validation 分离和有限停止条件。本实现保留两者的角色隔离，但根据 smoke
证据把自动 repair 降为 opt-in。

机器可读结果在 [`verifier_smoke/`](verifier_smoke/)：`summary.json`、`scores.csv`、
`behavior.csv`、`prep_audit.csv`、`verifier_audit.csv` 和逐项证据
`verifier_criteria.csv`。
