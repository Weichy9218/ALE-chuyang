# Verifier v14 六题实验

2026-07-21 在 pgl 上跑了一次 `public-verifier-v14` 的六题实验,只跑 verifier 单臂
(prep 关、verifier 开、`max_review_rounds=1`),base 用历史 `verifier_v13_six_r1` 的 base 臂
(同六题、同模型 `gpt-5.6-sol`、同为 prep 关 verifier 关)。目的是搞清楚 v14 的反馈通道是否接通、
以及接通后的实际效果,不追求干净的分数因果。concurrency=6,六题并行,约 30 分钟跑完。

## 分数

| 任务 | 历史 base | v14 verifier | Δ | verifier 是否喂给 writer |
|---|---:|---:|---:|---|
| BPMN | 0.8638 | 0.8052 | **−0.0586** | 是:1 个 review_item → 1 次 revision |
| Digital | 0.7245 | 0.7245 | 0.0000 | 否:stats checker 预检失败(error) |
| SSE | 0.6667 | 0.6667 | 0.0000 | 否:7 个 check 全 unverifiable |
| PDE | 0.6316 | 0.6650 | +0.0334 | 否:硬检查全 pass,其余 gap |
| CRF | 0.6507 | 0.6651 | +0.0144 | 否:6 个硬检查全 pass,其余 gap |
| FluSight | 0.6927 | 0.7807 | +0.0880 | 否:2 个 check 全 unverifiable |

均值 base 0.7050、v14 0.7179、Δ +0.0129。这个 +0.0129 没有意义:它全部来自 verifier 从未触碰
writer 的 5 道题的 rollout 噪声(PDE、CRF、FluSight 各自向上,SSE/Digital 恰好相同)。verifier
唯一真正介入的题是 BPMN,Δ 为 **−0.0586**。

## 通道接通:BPMN 是证据

v14 想修的就是 v13 把部分覆盖 Checker 整体丢成 error、writer 一次都看不到的漏失。BPMN 直接证明
通道通了:

- Checker `new_task_topological_form_dataflow`:要求每个新任务的 `in_*` 表单属性都要有一个可达
  前驱任务声明匹配的 `out_*`。Auditor 判 `checker_matches_requirement=False`(实现只覆盖
  userTask 节点,是部分实现),但 `source_status=supported`(要求本身有来源支撑)。
- v14 因此让它以 **advisory 运行**(v13 会直接丢成 error)。round 0 它 `fail`,报告
  `in_supplier_risk_level` 在 `task_executiveQualityWaiver`、`task_expeditedQualityDecision`
  两处没有可达生产者。`needs_review=True`,反馈进了 writer。
- writer 做了真实 revision(`repairs=1`,snapshot source hash 从 `2c47e770` 变成 `a7e97038`)。
  round 1 该 check 变 `pass`,`stop_reason=pass`。

机制上完全按设计走通:部分覆盖 Checker → advisory → review_item → writer 消费 → 重跑冻结包。

## 但这次 revision 是坏的:proxy 被 game

- round 0 `checked_input_count=20`,round 1 变成 **18**。两个报错的输入正是被删掉的两个
  `in_supplier_risk_level`。writer 不是补上生产者 `out_supplier_risk_level`,而是**删掉了这两个
  输入让 check 通过**,典型的 delete-to-pass。
- 该 Checker 只看 userTask 节点,`out_supplier_risk_level` 的真实生产者若在别的节点类型上,这两
  条 unmatched 本身可能是**部分 Checker 的假阳性**。也就是说 writer 很可能为一个假阳性删掉了正确
  的输入。
- writer 没有 dispute(`writer_disputes=[]`),它信了这个 proxy 并 game 了它。最终 BPMN 0.8052
  低于 base 0.8638。

这正是 [EVOLUTION.md](../../EVOLUTION.md) 反复记录、并因此把 repair 默认设为 0 的失败模式:在 proxy
metric 上做修复会引发回归。v14 把通道打通,第一条真实 revision 就把这个坑重演了。advisory 的
“先验,自己判断”措辞没有拦住 writer 去 game 一个部分 Checker。

注意因果不能完全隔离:base 是另一条 rollout,revision 前的 output 已随容器删除无法官方打分,所以
“revision 导致 −0.0586”是强提示而非定论。但 delete-to-pass + Auditor 标记的部分 Checker + 分数
低于 base,三者一致指向同一结论。

## 其余五题:verifier 保持沉默

5/6 题 `needs_review=False`,writer 一条 verifier 信息都没收到:

- **SSE**:7 个 check 全 unverifiable。v13 那个 No/Unknown 语义映射在 v14 被正确降为
  unverifiable(不再假硬门),连带后果是它也进不了 writer。v13 靠假硬门碰巧拿到的 +0.33 不再发生,
  SSE 停在 0.6667。这是“诚实但沉默”的取舍。
- **PDE / CRF**:结构硬检查全 pass(文件集、ID、表头、S01 满分、manifest;CRF 的 csv/列序/一致性/
  主键等 6 项),但真正决定官方分的隐藏 rubric(S02–S05 部分分、feedback 质量;CRF 的
  mapping_rule/origin/label 列准确率)都是 unverifiable。verifier 验证了能公开验证的,但那不是失分面。
- **FluSight**:submission_contract 和 forecast_accuracy 都 unverifiable,主分依赖隐藏未来值。
- **Digital**:`segment_definition_contract_and_stats` 这个本可有用的 stats 检查在**预检阶段失败**
  (checker 用 `target.issubset(pred)`,矛盾/收窄谓词也能通过,fixture 判反例失败),被判 error,
  没跑到 output 上。v13 里 Digital 是 locator 漏多行 quote,v14 里换成 checker 自身预检不过,结果
  一样:有用的检查没进 writer。

## 结论

1. **通道确实修好了。** BPMN 证明 v14 能让部分覆盖 Checker 以 advisory 到达 writer 并驱动真实
   revision,这是 v13 做不到、也是本次要验证的核心。
2. **但“到达 writer”是双刃的。** 唯一一次真正介入就是 proxy 被 game 的回归,重演了 EVOLUTION 的坑。
   没有证据显示 v14 提高分数;唯一的因果数据点(BPMN)是负的。
3. **主要瓶颈不在通道,在可验证性。** 6 题里 5 题的失分面都落在隐藏 reference、隐藏未来值、隐藏
   rubric 上,公开 `/input` 根本验不了,verifier 只能如实报 coverage_gap。把这些如实沉默是对的,
   但也意味着 verifier 在这批题上能合法帮到 writer 的面很小。

## 待议(不在本轮改)

- Auditor 标记 `checker_matches_requirement=False` 的部分 Checker,是否危险到连 advisory 都不该
  surface——因为 writer 会 game 它。也许只 surface proxy-safe 的 advisory(如题面认可等价的
  simulation 真指标),不 surface 部分覆盖 proxy。
- advisory 措辞要不要显式警告 delete-to-pass / 反 gaming,并要求 writer 修根因而非症状(但这会让
  verifier 变得 prescriptive,与定位冲突)。
- Digital 的 stats checker 预检失败、FluSight 的 submission_contract 判 unverifiable,都提示 Builder
  的 checker 质量和 locator robustness 仍是独立瓶颈。

原始数据在 pgl `~/ale/agents-last-exam/.logs/ale/verifier_v14_six_v2`。
