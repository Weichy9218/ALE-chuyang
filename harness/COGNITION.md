# Harness 认知与设计

当前进展入口是 `docs/harness/README.md`，本文件只保留实现必须遵守的认知和红线。
历史 general prep、早期 prompt harness 和逐题报告已归档到
`docs/archive/harness-general-prep-2026-07/`。

## 已有证据

- 提醒式 prompt、无差别方法后缀和通用长 notes 都没有跨过噪声底的净收益证据。
- 26 题四臂单次实验中 base=0.6415、旧 prep=0.6094、skills=0.6214、
  skills+旧 prep=0.6103，全部 `|t| <= 1.00`；去掉 CT 一题后三个差值全部翻正。
- 26 题中 13 题四臂完全同分，有效题配对差 sd 约 0.22。单次全量跑测不出约
  0.02 的效应；任何方法结论至少需要 `k >= 3` 和同轮噪声基线。
- 唯一明确收益仍是资源控制：过低 turn budget 会制造空输出。实验各臂必须同预算。
- CT geometry 有公开 target 和指标，可做真实 feedback。旧 skills_prep 只 assertion
  了已达标 MSE，打印但未 assertion 未达标 SSIM，是 checker 校准失败。
- CT base 的 1.0 不是复制 reference；但公开 input 与隐藏 reference 内容相同，所有
  运行都必须保留复制/混合审计。
- 2026-07-17 的旧实验只否定“旧 general notes 已证明有效”，当时没有测试当前的
  task-specific prep；下面的 v1 结果才是新架构证据。
- 2026-07-18 task-prep v1 的 26 题三臂已完成：prep=0.6438、skills=0.6115、
  combined=0.6153；历史 base=0.6415。prep 总体差 +0.0023 不可检测，去 CT 后为
  +0.0424。SSE/CRF4/Flusight/TCGA 有机制性收益，Variant 有可复现回归。
- skills 与 prep 不可假定可加：TCGA、SAP 都出现单臂提高而 combined 回落。
- skills/prep v2 的 25 个完整同轮配对任务中，prep=-0.0012、skills=-0.0161、
  combined=-0.0226；50/50 个已完成 skill-enabled unit 都实际加载至少一个 skill。
  PE 分端点恢复使操作层面达到 104/104 completed，但空 prep/未加载 skill 使该行不能用于
  因果归因；原同协议 artifact 重评分不改变总体结论。当前 skills/prep 均默认关闭。

## 当前职责

### Task-Specific Prep（当前 `task-prep-v20`，以 docs/harness/PREP.md 为准）

- `ale_run/agents/ale_claw/task_prep.py` 在 writer 前、在 writer 同一沙箱运行；当前代码
  默认开启，preset 仍逐臂显式写出开关。
- 三件事按价值排序：把题目运行时跑通并把状态留在沙箱；从题面和 `input/` 编译交付物
  合同清单（并在机械条目多时交付一个可运行的 self-check 脚本，writer 对自己的草稿运行）；
  补上题面缺失的精确外部事实或可复用工具。
- 不读、不写、不检查候选 `output/`（prep 运行时它尚不存在）；但 writer-facing 的检查
  说明和自检工具应当引用 `output/` 交付物路径。裁决候选产物是 Verifier 的角色。
- 不选定最终取值、标签或缺失值策略；题面和 `/input` 永远高于 prep 产出。
- 校验全部机械化且逐条：类型、长度、条数、artifact 路径与大小；不合格条目单独丢弃，
  不整包拒绝。无法机械判定的语义 gate 一律不做（v17 的教训）。
- 结果不缓存：prep 在沙箱留下真实运行时状态，复用缓存报告会谎称环境就绪。

### Main-Agent Skills

- skills 只供 main agent 按需加载，不进入 prep-agent。
- `deliverable-contract` 只检查公开材料中可观测的 artifact 契约；优先复用 shipped
  validator，必要时补最小临时检查，并明确区分 checked / failed / unverifiable。
- `evidence-audit` 只用于多源判断中证据覆盖是主要风险的任务；覆盖题目要求的比较单元，
  锚定 primary evidence，并区分明确否定和信息缺失。
- skills 是 writer 执行方法，不提供独立反馈，也不包含任务专属值、隐藏 schema、grader
  行为或参考答案。

### Feedback（当前 `public-verifier-v16`，以 docs/harness/VERIFIER.md 为准）

- main agent 可在解题阶段用公开材料建立局部检查，但同上下文自检不是独立 verifier。
- prep-agent 不预造 verifier；独立验证需要与 writer 分离的上下文、artifact snapshot 和
  结构化证据反馈，不能靠 skill 文本实现。prep 的 self-check 脚本是 writer 自用工具，
  没有任何权威。
- Verifier 的标准在 writer 开始前冻结；writer 可以在 DONE 前用 `verify` 工具对草稿运行
  冻结测试包（预提交自检），标准与隔离不变，只有执行时机提前。
- 有公开 oracle 时运行真实闭环；只有 schema/invariant 时承认只能部分验证；语义判断
  没有 oracle 时不能把自评伪装成确定性 PASS。来源歧义或蕴含不足的检查以 advisory 身份
  运行并附审计说明，不授予硬权限，也不悄悄丢弃。
- 指标只打印不 assertion 不算验证。checker PASS 必须与题面公开完成条件一致。
- checker 必须针对最终落盘产物；数值反馈平台化后先枚举未测的离散模式和边界，再
  继续连续参数细调。
- 独立 verifier 必须在 solve 前固定公开 spec，solve 后使用 fresh context 和 hash snapshot；
  只允许 deterministic/public-evidence failure 驱动 repair。proxy、unverifiable 和
  verifier error 不得回灌。

## 红线

- 不读取、staging 或推断隐藏 reference、evaluator、grader、历史答案或 submission。
- 不修改数据集的 task、input、software、reference、runner 或评分方式。
- 不根据逐题隐藏失分手写 task-specific skill；task-specific prep 只能从公开材料和
  primary sources 研究得到事实。
- prep 可运行只读 introspection 和 synthetic probe，但不对真实 target 优化候选答案。
- 输出必须由计算/推理产生，不得复制或混合公开 reference/expected output。
- 实验必须保留 output、task_prep artifacts、verifier spec/round/meta 和 trajectory 供审计。

## 运行

唯一控制面仍是 `harness/run/settings.yaml`，入口和 API 细节见 `harness/run/README.md`。
普通 ALE Claw 默认 task prep 关、verifier 关；`base / prep / verifier / prep_verifier`
四臂显式写开关。运行采用 `cleanup_mode: delete`。方法效应必须至少重复三次。
