# 实验结论与下一轮验证

## 已完成：Prep v10 / Verifier v10 26 题全量（2026-07-20）

pgl 四臂 104/104 个 unit 均有 `run.json`；100 completed，PE 四臂因原 evaluator 请求
不可用的 `gpt-5-mini` 而 failed。25 题完整配对均分为 base `.60547`、prep `.59570`、
verifier `.61556`、combined `.66943`。Prep-only paired delta `-.00977`，2x2 prep main
effect `+.02205`（t=`.96`）；均未证明总体增益。Verifier 全程 `max_repairs=0`，其分数差
不是审计因果效果。combined 高均值主要受 CT `0/0/0/1` 与 SSE `.667/.333/1/1` 影响；
去掉两题后 verifier main effect `+.00208`、combined-vs-base `+.01155`。

最终协议来自 10 题 v8/v6 canary 与连续窄复验：

- v8/v6 原始正均值被 CT reference mixing 的非法 +1 扭曲；排除 CT 后 prep main effect
  `-0.0161`、verifier main effect `-0.0033`。
- prep v9 用公开 holdout/backtest 替代 FluSight 未验证趋势启发式，但 Variant 仍
  `.999 -> .793`；v10 让 writer 保留 exact submitted ALT，同轮 `.793 -> .999`。
- verifier v9 将 source entailment 覆盖到 requirement/check/expected，处理多 excerpt 和
  ellipsis，并为公开 oracle 注册 provenance；v10 清空非-public-evidence sample，避免无语义
  lint failure。自动 repair 因 BPMN/SEC/CT 破坏性轨迹关闭。

52/52 prep metadata 和 verifier metadata 分别为 `task-prep-v10`、`public-verifier-v10`；
0 repairs。Variant exact-key 修复在 canary 与 full 两次都复现 `.793 -> .999`。344 条
verifier criterion 为 180 pass、156 unverifiable、6 fail、2 error；source status 为
196 supported、145 ambiguous、2 contradicted、1 missing。CT combined 的 provenance
重跑证明是真 FBP，不是 reference mixing；American/Moodle 则暴露 runner 同 VM 修改原
output 的隔离问题。完整实现、逐题、skills 与早期 Codex 判断见
[最终分析](prep_v10_verifier_v10_full_analysis.md)，机器结果见
[`results/latest/`](../../results/latest/)。Canary 证据见
[10 题分析](prep_v8_verifier_v6_canary_analysis.md)和
[协议迭代](prep_verifier_protocol_iteration_analysis.md)。

## 已完成：Prep / Verifier 26 题全量审计（2026-07-19）

pgl 四臂 104/104 个 unit 均有 `run.json`；101 completed，base/prep/verifier 的 PE evaluator
因临时 `gpt-5-mini` 路由失败而 failed。主表严格使用其余 25 个完整配对任务：prep
`+0.00093`、verifier `-0.01388`、prep+verifier `-0.01360`。Verifier 两臂均为
`max_repairs=0`，所以后两项只反映 writer rollout/endpoint 差异，不是 verifier 修改效果。

50 个 verifier-on unit 中 48 个 spec 构建成功、2 个 lint fail；317 条 criterion 包含
34 fail。逐条人工复核为 30 个公开证据支持、1 个边界项、3 个明确误报，同时存在低分
artifact 被 pass 的 coverage failure。因此 skills/prep/verifier 均保持默认关闭，verifier
保留 audit-only。完整协议限制、25 题逐案、PE 路径冲突和 v5 后续修复见
[全量分析](verifier_compare_analysis.md)，机器结果见 [`verifier_compare/`](verifier_compare/)。

## 已完成：Prep / Verifier 5 题 Smoke（2026-07-19）

pgl 四臂 20/20 completed。均分为 base `0.6603`、prep `0.6756`、verifier `0.6494`、
prep+verifier `0.6144`。TCGA 暴露了公开 contract 自身矛盾导致的明确 verifier false
positive，因此自动 repair 默认改为 0；独立 spec、snapshot 和 runner 继续作为审计链路。
完整分数、judge 迭代、成本和逐题 evidence 见
[Prep / Verifier Smoke 分析](verifier_smoke_analysis.md)，机器可读结果见
[`verifier_smoke/`](verifier_smoke/)。

## 已完成：Task Prep / Skills v2（2026-07-19）

pgl 同轮四臂得到 25 个完整配对任务；PE screening memo 的原 evaluator 调用因端点不支持
`gpt-5-mini` 而共同失败，不按 0 分处理。分端点恢复后 104/104 个 unit 都有可用评分，
但 PE 恢复的 prep 报告为空、combined 也未加载 skill，所以 26 题表只用于运行完整性，
主效应仍按下面 25 题同协议结果解释。

| 臂 | 均分 | 相对 base | t |
|---|---:|---:|---:|
| base | 0.6068 | - | - |
| prep | 0.6056 | -0.0012 | -0.08 |
| skills | 0.5907 | -0.0161 | -0.84 |
| skills + prep | 0.5842 | -0.0226 | -1.71 |

50/50 个已完成 skill-enabled unit 都实际加载了至少一个 skill；prep/combined 在 25 个
任务上的 fingerprint 与报告 SHA 全部一致。因此负向结果不能归因于 skill 未触发或 prep
漂移。当前 skills 从默认实验轴移除，prep 默认关闭；详细机制、成本和逐题证据见
[v2 最终分析](task_prep_skills_v2_analysis.md)，原始表见
[`task_prep_skills_v2/`](task_prep_skills_v2/)，PE 协议例外见
[`pe_recovery.json`](task_prep_skills_v2/pe_recovery.json)。

## 已停止：CT v2 canary（2026-07-19）

prep-only 已完成，score=0，agent 用时 1,780.92 秒、95 steps、1,182,184 main input
tokens。prep 报告为 8,043 字符，main agent 读取了完整报告，但仍未检查 359.9xx 角跨度
边界；最终 MSE `3.765e-6` 达标，按 reference range 计算的 SSIM 只有 `0.5906`。

这证明删除 4,000 字符限制只能修复信息交付，不能修复先验研究方向。随后启动的
skills+prep 臂已主动终止，不再运行真题。CT 专用配置和任务清单已从当前代码删除。

## 已完成：Task-Specific Prep v1（2026-07-18）

pgl 上完成 26 题三个新臂，共 78 个 unit；全部 `completed` 且 `score_valid=true`。
按要求未重跑 base，下面的 base 是 2026-07-17 历史结果，因此是描述性比较，不是
同轮随机对照。

| 臂 | 均分 | 总分 | 相对历史 base | 去掉 CT 后平均差 |
|---|---:|---:|---:|---:|
| historical base | 0.6415 | 16.679 | - | - |
| new skills | 0.6115 | 15.900 | -0.0300 | +0.0088 |
| task-specific prep | 0.6438 | 16.740 | +0.0023 | +0.0424 |
| skills + task-specific prep | 0.6153 | 15.997 | -0.0262 | +0.0127 |

没有一个全量配对差能与 0 分开（最大 `|t|=0.76`）；prep 的 +0.0023 实质为零。
但机制证据不为零：prep 在 SSE（0.333→1.000）、CRF4（0.450→0.615）、Flusight
（0.663→0.775）、TCGA（0.840→0.985）上提供了主 agent 原本没有查清的输入/API
事实。去掉 CT 后，new prep 的描述性差比 old prep 的 +0.0066 大，但需要 `k>=3`
复验。

负面同样明确：

- CT 三个新臂全 0。真实 SSIM/MSE 闭环运行了 43–90 分钟，但都只搜连续几何参数，
  未枚举 LEAP 在 360 度附近的离散 weighting 边界；历史 base 的 359.999 才是关键。
- Variant 的 prep 和 combined 都是 0.793，skills-only 是 0.999。prep 用上游 VEP
  normalized-allele 语义重解释了 task-local manifest，造成 3 个 AF 和 1 个 ClinVar
  偏差，并触发 reportable 子表 20 分整块丢失。
- 组合不单调：TCGA 的 skills=1.000、prep=0.985，combined 却回到 0.840；SAP 的
  skills=0.379、prep=0.350，combined=0.240。
- 52 个 prep 实例中 49 completed、3 failed、0 empty、10 cache hit。42 次真实研究
  消耗 9,763,850 input tokens 和 179,478 output tokens；三次 compaction 全部因孤立
  tool result 失败，已定位并在实验后修复。

配置：`harness/run/settings_task_prep_v1.yaml`。结果：
[task_prep_v1_scores.csv](task_prep_v1_scores.csv)。完整机制分析：
[task_prep_v1_report.html](task_prep_v1_report.html)。

逐题时长、真实 LLM turns、工具调用、历史 prep 截断和 skills load turn 的复算见
[Task Prep v1 行为审计](task_prep_v1_behavior_analysis.md)；机器可读行为表在
[`task_prep_v1_behavior/per_task.csv`](task_prep_v1_behavior/per_task.csv)。

## 已完成：旧 General Prep

2026-07-17 在 pgl 完成 26 题四臂单次对照，共 104 个 unit：

| 臂 | 均分 | 相对 base |
|---|---:|---:|
| base | 0.6415 | - |
| old general prep | 0.6094 | -0.0321 |
| skills | 0.6214 | -0.0201 |
| skills + old general prep | 0.6103 | -0.0312 |

所有配对检验 `|t| <= 1.00`。去掉 CT geometry 一题后三个差值全部翻正；26 题中
13 题四臂完全同分，有效题配对差标准差约 0.22。因此该实验不能证明干预有用或有害。

它能证明的只有：旧 prep plumbing 跑通，但“一次 completion + 前五个文件的短 head +
搜索关闭 + 约千词通用 notes”没有检测到稳定收益。它没有测试当前的 task-specific、
多轮工具 research agent。

完整历史报告：

- [四臂比较](../archive/harness-general-prep-2026-07/harness-study/harness_compare_report.html)
- [skills 消融](../archive/harness-general-prep-2026-07/harness-study/skills_ablation_report.html)
- [26 题执行 forensics](../archive/harness-general-prep-2026-07/pi-cases/index.html)
- [任务与评测分析](../archive/harness-general-prep-2026-07/case_by_case/index.html)

## CT Geometry 的机制证据

CT 题有公开 reference、明确 SSIM/MSE 公式和阈值，因此能够建立真实反馈闭环。旧
`skills_prep` 运行打印了 SSIM 0.9033 和达标的 MSE，却只 assertion 了 MSE；checker
PASS 与任务完成度不一致。base 则探索到 LEAP 在接近 360 度处的离散 weighting 分支，
SSIM 约 0.994 并通过。这同时说明：feedback 能判定“尚未完成”，task-specific library
research 才可能提供“应检查离散分支”的新增先验。

`input/reference_image.npy` 与 evaluator-owned reference 内容相同，是题目公开 oracle，
不是 harness 读取隐藏目录。四臂均可见，但必须继续审计复制/混合 reference 的作弊。

## 当时的下一轮计划（已由 v1 执行）

2026-07-17 时新 task-specific prep 尚未在 pgl 运行；当时提出的最小设计是：

1. 固定同一版 skills，仅比较 task-prep off/on。
2. 每个条件至少 `k >= 3`；先做同配置 off/off 估计当轮噪声。
3. 优先跑有 headroom 且可能受工具/版本知识影响的题；不要用 CT 单题决定结论。
4. 同时记录机制指标：prep 文件覆盖、来源质量、新增事实数、主 agent 是否采用、是否
   建立真实 feedback、每个公开阈值是否有 assertion。
5. Legal/SSE 这类 closed-book 题若没有新增外部工具事实，prep 应输出空；不能为产生
   notes 而重复题目或猜标签。
6. 对 findings 做泄露审计，确认来源只来自公开 input/software 和 primary sources。
