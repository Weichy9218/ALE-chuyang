# Harness 当前进展

更新于 2026-07-20。这里是当前设计和实验状态的入口；旧版 general prep、早期
prompt harness、逐题分析和 HTML 报告完整保存在
[`docs/archive/harness-general-prep-2026-07/`](../archive/harness-general-prep-2026-07/)。

## 当前结论

- 最终 task-prep-v10 / public-verifier-v10 的 26 题四臂全量已完成：104/104 有结果，
  PE 四臂为原 evaluator `gpt-5-mini` 404，其余 25 题配对中 prep-only `-.00977`、
  prep main `+.02205`（t=`.96`）。Verifier 0 repairs，所以分数差不是审计效果。Variant
  canary/full 两次复现 `.793 -> .999`；CT combined 的 provenance 证明是真 FBP；
  American/Moodle 又证明 runner 仍需独立容器。详情见
  [最终分析](prep_v10_verifier_v10_full_analysis.md)、
  [机器结果](../../results/latest/)、
  [canary 分析](prep_v8_verifier_v6_canary_analysis.md)与
  [协议迭代](prep_verifier_protocol_iteration_analysis.md)。

- 提醒式 prompt 和通用长 notes 没有得到跨噪声的提分证据。
- 2026-07-19 的同轮 v2 得到 25 个完整四臂配对任务：prep 相对 base `-0.0012`、
  skills `-0.0161`、skills+prep `-0.0226`。PE 原 evaluator 调用因模型不可用而共同失败；
  分端点恢复后操作层面为 104/104 completed，但恢复的 prep 报告为空，故 PE 仍不进入
  主因果分析。原同协议 artifact 重评分加入后的敏感性结论不变。
- 可机械复算的题应让主 agent 建立真实反馈闭环。CT geometry 可直接用公开
  `input/reference_image.npy`、SSIM 和 MSE 迭代，不需要模拟隐藏 evaluator。
- prep 的合理职责是补充任务特定、版本特定、且题面没有给出的先验知识；不是复述
  题意、抽 contract、生成 checklist 或替 solver 做题。
- skills 的职责是主 agent 执行期的方法：构造题运行公开自检，审计题覆盖证据。
  prep-agent 不加载这些 skills，也不构建 evaluator。
- skills v2 的 50/50 个已完成 skill-enabled unit 都实际加载至少一个 skill，但没有总体
  正向信号，当前从默认实验轴隐藏。prep 同样没有净收益证据，默认关闭。
- 独立 verifier 已实现为 solve 前固定 spec、solve 后 fresh runner 和只读 hash snapshot；
  它不使用 hidden reference 或原 evaluator。BPMN/SEC/CT canary 已证明自动 repair 可振荡、
  传播错误或利用公开 reference，因此默认和当前全量均固定 0 次。
- 5 题 verifier smoke 已完成：prep `+0.0152`，verifier `-0.0109`，combined `-0.0459`。
  TCGA 的公开 15/16 字符矛盾触发明确 false positive，因此 verifier 当前定位为独立审计，
  不是默认 repair gate。逐题证据见 [smoke 分析](verifier_smoke_analysis.md)。
- 26 题 prep/verifier 全量审计已完成。排除 PE evaluator 路由例外后的 25 题主结果为
  prep `+0.00093`、verifier `-0.01388`、combined `-0.01360`；verifier 两臂 0 repairs，
  后两项不是 artifact modification effect。34 个 fail criterion 中人工复核 30 个证据支持、
  1 个边界项、3 个误报；详见 [全量分析](verifier_compare_analysis.md) 和
  [机器结果](verifier_compare/)。
- 数据集、task、input、software、reference 和评分方式不属于 harness 修改范围。
- 同轮 v2 中 Agora、PDE 是少数正例；SEC、CRF4、FluSight 没有获益，TCGA 四臂同为
  0.84。Variant 暴露了上游语义覆盖 task-local 规则的回归，CT 暴露了连续搜索遗漏离散
  边界的问题。组合臂并不单调更强，不能把 skills 注入 prep-agent。

## 当前系统

```text
stage public input/software
  -> verifier builder (fresh context, fixed public spec)
  -> optional task-specific prep (最多 3 条本地锚定 finding)
  -> main agent
  -> immutable output snapshot
  -> fresh verifier runner -> actionable failures -> bounded writer repair
  -> stage hidden reference
  -> unchanged evaluator
```

实现位置：

- `ale_run/agents/ale_claw/task_prep.py`：task-specific prep-agent 协议、缓存和审计。
- `ale_run/agents/ale_claw/verifier.py`：spec lint、snapshot、fresh runner 和 failure handoff。
- `ale_run/agents/ale_claw/deployer.py`：编排 prep、solver、verify 和 repair。
- `harness/skills/`：历史 writer 方法，非默认实验轴。
- `harness/run/settings.yaml`：四臂实验的唯一控制面。

详细边界见 [ARCHITECTURE.md](ARCHITECTURE.md)，独立反馈设计见
[VERIFIER.md](VERIFIER.md)，现有证据见
[EXPERIMENTS.md](EXPERIMENTS.md)，研究题表见
[results/latest/tasks.txt](../../results/latest/tasks.txt)。本轮完整报告见
[Task Prep / Skills v2 最终分析](task_prep_skills_v2_analysis.md)；旧 v1 报告见
[task_prep_v1_report.html](task_prep_v1_report.html)，机器可读分数见
[task_prep_v1_scores.csv](task_prep_v1_scores.csv)，行为/资源/触发审计见
[task_prep_v1_behavior_analysis.md](task_prep_v1_behavior_analysis.md)。运行方式仍以
[`harness/run/README.md`](../../harness/run/README.md) 为准。

## 当前边界

v2、verifier smoke 和全量审计每格都只有一次，所以不能检测小效应或声称稳定性。它们
足以否定“当前 skills/prep/verifier 已证明应默认开启”。全量实验按臂轮转 endpoint，
因此只作 operational comparison；后续正式对比已改为所有 arm 共享同一 endpoint。
