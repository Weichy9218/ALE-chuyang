# Prep / Verifier 轨迹复盘与优化决策

更新于 2026-07-20。本文只分析 2026-07-19 的 pgl 四臂全量运行，先冻结原因判断，
再实现 v8 prep 和 v6 verifier。逐条机器审计在
[`verifier_trajectory/`](verifier_trajectory/)；原分数结论见
[`verifier_compare_analysis.md`](verifier_compare_analysis.md)。

后续状态：v8/v6 canary 证实 source gate 有效，但暴露 Variant key substitution、未经回测的
forecast heuristic、CT reference leakage 和 Legal ellipsis 误报。逐项窄修复后的最终协议为
prep v10 / verifier v10，自动 repair 关闭。参见
[canary 分析](prep_v8_verifier_v6_canary_analysis.md)与
[协议迭代分析](prep_verifier_protocol_iteration_analysis.md)。

## 结论

1. **当前通用 skills 没有净收益，不应恢复为默认轴。** 上一轮 50/50 个
   skill-enabled unit 确实加载了 skill，但 skills `-0.0161`、skills+prep
   `-0.0226`。ALE 官方复盘也显示，在固定强模型时，精简 ALE-Claw 与更重的产品层处于
   同一准确率区间；额外 memory、skills、preferences 和 delegation 很少改变是否完成
   交付，而会增加上下文与决策成本。
2. **Prep 的主要缺陷不是 writer 没读，而是 v7 在 handoff 前丢掉了大部分有效信息。**
   20 个实际启动研究代理的任务全部返回 `decision=use`，共 79 条 finding；归一化只保留
   26 条，53 条被删除。51 条只是 `solver_impact` 中出现 `must/should/use` 等正常方法表达，
   6 条 claim 命中同一词表，二者有 4 条重合。5 个 raw response 最终变成 empty，全部是
   过滤器清空，不是研究代理主动判断无需 prep。
3. **保留下来的报告完成了传递。** 25 个主任务中有 20 份报告；writer 20/20 都在第
   1--4 次 tool call 读取完整报告。35 个保留 source 中，30 个随后被 writer 再次打开或
   执行。问题不是召回或读取，而是筛选精度与研究结论的干预方向。
4. **Verifier 能找真错，但 audit-only 不能提分。** 两个 verifier arm 的
   `max_repairs=0`，所以分数差全是独立 writer rollout、endpoint 和负载差异。48/50 个
   spec 成功，317 条 verdict 中有 34 条 fail；人工复核为 30 条公开证据支持、1 条边界项、
   3 条误报。它适合作为 finding 生成器，尚不能把 `overall=pass` 当完成证书。
5. **下一版只做两个窄改动。** Prep 最多交付 3 条、删除词表过滤、加强“非显然且改变方法”
   的准入；verifier runner 必须单独声明 source 对 requirement 是 supported、ambiguous、
   contradicted 还是 missing，后三者由代码强制降级为 `unverifiable`。自动 repair 只在
   实验配置中开 1 次，默认生产配置仍关闭。

## Prep 信息流

轨迹链条为：

```text
public task/input/software
  -> fresh prep agent raw JSON
  -> v7 lexical normalizer
  -> task_prep/PREP_REPORT.md
  -> writer reads report
  -> writer reopens local evidence
  -> output artifact
```

[`prep_findings.csv`](verifier_trajectory/prep_findings.csv) 逐条保存 raw finding、是否进入报告、
命中的 claim/impact 词和过滤原因；[`prep_writer.csv`](verifier_trajectory/prep_writer.csv)
保存报告读取位置和 source 回查数。

### v7 过滤器为何错误

v7 把下面的词在 `claim + solver_impact` 中任意出现都视作“prescriptive”，然后丢弃整条：

```text
must should use choose select prefer treat interpret map translate
override reinterpret adopt
```

但 `solver_impact` 本来就要求解释方法如何变化，因此情态动词是正常语法，不是越权信号。
实际被删的高价值例子包括：

- MARC：949 location 不能推出 carrier；`001` 与 `035$a` 的 OCLC 标识不可混用；环境没有
  `pymarc`，应走已提供的 ElementTree helper。
- BPMN supply：第三次失败后立即退出、`>25%` 路径冲突、high-risk timeout 仍要经过
  expedited decision、组织数据只有 `executive` group 而没有 executive role id。
- Moodle：完整 roster 中的特殊状态和 locked rows 超出 visible cases，helper 的精确枚举值、
  manual override/late penalty 顺序及两位小数后定 letter grade 都改变分支。
- SAP：安装版 `gsDesign` 默认不是任务要求的 spending function，`gsCP()` 是否显式传
  `theta` 会让 conditional power 落在 0.20 阈值两侧。

这些 finding 有本地 source 和具体 evidence；仅因 impact 写了 “must” 删除，既不提高安全性，
也不控制任务答案泄漏。正确边界应由内容协议约束：不得输出最终分类、最终参数或完整交付，
只能描述 runtime probe、跨文件冲突、非平凡聚合/边界或文件布局陷阱。

### 分数与行为不能混为因果

25 个主任务 prep paired delta 为 `+0.00093`，SE=`0.01183`，t=`0.079`。20 个有报告任务
均值 `+0.00648`，5 个 empty 任务均值 `-0.02124`。单次 delta 必须结合轨迹判断：

| Task | delta | 轨迹判断 |
|---|---:|---|
| Agora | +0.1847 | 报告指出 San Jose enforcement 和 Anthropic FLOPs footnote；writer 先读报告，再逐份读 taxonomy/documents，输出标签与证据显著变化。存在真实干预链，但部分 finding 已接近分类提示，后续必须守住“事实而非答案”边界。 |
| BPMN supply | +0.0476 | 报告锁定 `>25%` 必须先经 Finance 再进 executive；writer 回查 scenario/rules 并在 25 calls 完成，base 用 51 calls、额外尝试多轮 Docker/拓扑修补。这里最像 prep 节省搜索并改善结构。 |
| SEC 10-K | +0.0366 | 报告只说明 `pdftotext -layout` 快且可用；base 第 5 call 已独立使用同一路径。两臂均批量解析 PDF，不能把分差归因于报告。 |
| Moodle | -0.0650 | 12/13 个输出文件逐字相同；唯一不同的 MBZ 内，两个 CSV 仅 LF/CRLF 不同，两个 JSON 仅末尾换行不同。报告中的 drop-lowest 事实没有直接造成该差值。 |
| CRF4 | -0.0096 | 两臂都是 40 行；报告确实引导 SUPPAE/date-origin 查证，但 35 个共同 key 的说明文字不同。微小分差不能区分信息收益与生成差异。 |
| FluSight | -0.0648 | 两臂都用 seasonal analog；prep 报告强调 rising/falling branch 后，writer 用 52 周 analog，并把 horizon 上界放宽到 point 的 2.6--4.8 倍，base 为 1.62--2.10。这里存在“局部事实诱导过强启发式”的真实风险。 |
| Audience / PDE | -0.1797 / +0.0735 | 两份均为 empty，说明同量级单题变化可以完全来自独立 rollout。 |

Prep 主 arm 的独立研究累计消耗 1,514,431 input tokens、约 3,737 秒，却只带来无法与
噪声区分的总体变化。优化目标因此不是扩大研究，而是减少报告条数、拒绝隐藏 outcome
启发式、保留真正改变离散分支或 runtime 路径的证据。

## Verifier 信息流

```text
public task/input/software
  -> fresh builder + fixed spec
  -> writer output
  -> immutable snapshot + hash receipt
  -> fresh runner per-criterion evidence
  -> code recomputes overall
  -> optional bounded writer repair
```

本轮最后一步被配置为 0 次，因此 verifier 没有修改 artifact。`verifier -0.01388` 和
combined `-0.01360` 不是 verifier 效果。

### 真阳性、误报和漏报

真阳性包括 BPMN gateway/topology/dataflow、SEC XOM EPS/QA propagation、CT SSIM 约
0.903、Variant `AF=.8255` 却 `reportable=yes`、Agora matrix Boolean/schema 缺口，说明
fresh-context artifact checking 有价值。

三类误报都发生在“source 存在，但 requirement 被加严或材料自相矛盾”处：

- Legal 把“original Chinese text + page marker”升级成“必须是单段连续 exact substring”。
- CRF1 的公开规则只要求删掉“没有对应 CRF field”的 derived/protocol variable；runner
  却要求所有 row 的 `origin=CRF`，误删由 collected Ongoing 支持的 Derived target。
- TCGA 同一句一边写 first 15 characters，一边给出 16 字符示例
  `TCGA-05-4245-01A`；runner 明知 490/490 都是 16 字符仍按 15 fail。

因此仅要求 runner 在自由文本里“先验证 quote”不够。下一版把 source entailment 变成必填
枚举和独立 evidence；代码而非模型决定 ambiguous/contradicted/missing 不能触发 repair。

漏报则来自固定 5--8 条 criterion 的覆盖上限：MARC score `.2`、CRF4 `.64--.66`、SAP
`.25` 仍可能全 pass。增加更多 LLM criteria 只会同步扩大成本和误报面，不能把 pass 变成
证书。v6 优先提高 fail precision，并只对检测到的、高置信公开失败做一次 repair。

## ALE 约束与提分方向

ALE 官方仓库说明每个 task 是 instruction + input + hidden reference，hidden reference 只在
agent 完成后 staging，再由 deterministic grader 对 output 给 `[0,1]` 分；统一 trajectory
保留完整 tool/action/observation，适合做本次这种 outcome 后轨迹审计。参见
[ALE repository](https://github.com/rdi-berkeley/agents-last-exam#how-ale-works)。

官方 ALE-Claw 复盘的结论与本地消融一致：固定模型时 harness sweep 只有约 5--6 个百分点，
模型 sweep 为 18 个百分点；精简 ALE-Claw 相对 OpenClaw 用少 44% input tokens、41% cost、
60% wall time，均分仍在同一范围。额外 tool/product layer 多数改变路径而非结果。参见
[Does the Harness Matter?](https://agents-last-exam.org/blogs/harness-matters)。

所以本轮可迁移的提分优先级是：

1. 修复确定的 harness 信息损失和路径 bug，而不是恢复通用 skills。
2. Prep 只传递非显然、可回查、改变离散控制流或 runtime 方法的少量事实。
3. Verifier 只把公开 source 明确支持的失败交给 writer，并让 writer 重新执行公开检查。
4. 对含隐藏未来 outcome 的预测任务，不用 prep/verifier 猜 outcome；最多检查 schema、
   provenance 和公开 backtest proxy，且 proxy 不触发 repair。
5. 使用同一 endpoint、同一设置；先跑真阳性/误报/漏报 canary，再跑全量，避免把 endpoint
   或独立 rollout 方差误当 harness 提升。

## 实施与验收门槛

- Prep v8：最多 3 条；无词表删除；缺字段、非法 source、非法 confidence 仍拒绝；prompt
  明确 hidden outcome heuristic 和最终答案不得进入报告。
- Verifier v6：runner 每条返回 `source_status`、`source_evidence`；只有 `supported` 保留原
  pass/fail/error，其他状态一律归一化为 `unverifiable`；repair prompt 带上 quote 与 source
  evidence 供 writer 独立复核。
- Canary 至少覆盖：BPMN supply / Variant / CT（真阳性），Legal / CRF1 / TCGA（误报），
  MARC / SAP（coverage false-negative），FluSight（不可验证 outcome）。
- Canary 实际出现破坏性和 leakage repair，因此全量只在 `max_repairs=0` 下运行；repair
  round 仅保留为负面机制证据。
