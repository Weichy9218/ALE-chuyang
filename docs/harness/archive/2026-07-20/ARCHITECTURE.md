# Harness 架构与职责边界

## 五个不同角色

| 组件 | 负责 | 不负责 |
|---|---|---|
| task-specific prep-agent | 沿目标计算/数据链识别题面之外的工具、版本、变量、单位、约定和离散行为，输出新增先验 | 解题、生成交付物、抽任务 contract、构建 evaluator |
| main agent | 理解题目、实现交付物、运行反馈、根据失败继续优化 | 读取隐藏 reference/evaluator、猜评分器偏好 |
| skills | 给 main agent 提供通用执行方法 | 给 prep-agent 做调研、注入任务专属答案 |
| verifier builder/runner | solve 前冻结公开检查标准；solve 后在 fresh context 检查只读 snapshot 并返回逐项证据 | 读取 writer history/prep/skills/hidden reference，发明题面外标准 |
| evaluator | 数据集原有评分 | 向 agent 提供反馈或被 harness 修改 |

prep 与 skills 不合并。`deliverable-contract` 和 `evidence-audit` 被写入主 agent 的
MemoryStore；prep-agent 使用独立 session/registry，工具白名单只有 `read`、`exec`、
`web_search`、`web_fetch` 和 `analyze_image`，没有 `memory_get`，因此看不到 skill
正文，也不能继续 delegate。

## Task-Specific Prep

普通 ALE Claw 配置默认 `task_specific_prep: false`。实验配置显式开启或关闭，避免把尚无
净收益证据且有额外成本的机制当作默认能力。

prep-agent 是真实的多轮 agent，而不是一次 completion。当前 v10 只接受最多 3 条结构化 finding，
每条必须锚定 `input/...`、`software/...` 或实际 `runtime:` probe；只有网页来源的 finding
会被机械丢弃：

1. 从题目目标出发，追踪公开输入、脚本、实际 API 和 metric 的计算链。
2. 计算题形成变量/敏感性地图：单位、坐标、默认值、耦合关系、连续变量、离散模式和
   branch boundary。允许小规模单变量诊断，不做优化或最终参数选择。
3. 数据/文档题重点检查 schema、ID/join、时间、缺失值、来源优先级、parser 和版本约定；
   task-local 规则与上游规范冲突时，明确以 task-local 为准。original/submitted/exact key
   没有本地明示 mapping 时，不能被 alternate normalized representation 覆盖。
4. 只读真正相关的公开材料；本地不足且任务允许联网时才查 primary source，但上游规范
   只能解释本地观察，不能覆盖 task-local 规则。
5. 没有会改变 solver 决策的信息增量就输出 `decision=skip`；非法、低置信或无本地锚点的
   finding 不进入 handoff。

Unavailable future/subjective outcome 的 modeling heuristic 只有在 task-local holdout 或
backtest 上用相关公开指标优于明确 baseline 才能交付。计算题遇到合法 API endpoint/mode
边界时，先比较精确 endpoint 与小单侧扰动，避免粗网格和平滑优化漏掉离散分支。

hidden reference 在 prep/main agent 完成后的 lifecycle Phase 3 才 stage；evaluator 不在
prep 的任务 VM 中，memory/delegation 工具也被 allowlist 排除。这些由执行边界保证，
不依赖 prompt。prompt 只约束语义职责：prep 不做目标优化、最终值选择或交付物。

完整报告记录为 host artifact `task_prep.md`，同一字节写入任务 VM 的
`task_prep/PREP_REPORT.md`；主 prompt 只提供路径，不复制或压缩正文。它不进入
`output/`。`task_prep_meta.json` 记录报告字符数、研究时长、LLM turns、工具计数和
compaction。缓存键包含 prep 协议版本、task identity、完整 prompt，以及 Linux 下
`input/` 和 `software/` 每个文件的内容哈希；材料哈希失败时本次照常运行但不缓存，
避免 prompt-only stale hit。

## Independent Verifier

`ale_run/agents/ale_claw/verifier.py` 实现两阶段独立验证：

1. Builder 在 main agent 前只看公开 prompt、`input/` 和 `software/`，输出至多 8 条带
   source anchor 的固定 spec；spec 先经过机械 lint。确定性代码可全量检查，语义
   public-evidence 在整个 spec 中最多预注册 5 个明确 record/field/page locator。
   每条 criterion 还必须保存直接推出 requirement/check/expected 的公开 `source_quote`，
   不能从两个字段共现或 operational check 推导更强约束。
2. Runner 每轮使用 fresh session 检查 `output/` 的独立 snapshot；v5 不解引用 symlink，
   并在 runner 前后同时哈希 snapshot 与 writer 原始 `output/`，任一变化都记 `error`。
3. 只有 `deterministic` / `public_evidence` 的 blocking fail 进入 repair prompt；`proxy`、
   `unverifiable` 和 verifier `error` 都不会驱动修改。Runner 必填 source status/evidence，
   ambiguous/contradicted/missing 由代码强制变成 unverifiable。
4. Writer 只收到 criterion id、公开 source、observed/expected、证据和最小 repair hint。
   默认和当前全量均不自动修复；代码仅为研究兼容最多 3 次，相同失败集合连续出现即停止。
5. hidden reference 仍在整个 solver/verifier/repair 循环结束后才由 lifecycle stage，原
   evaluator 不变。

审计文件为 `verifier_spec.json`、`verifier_round_N.json` 和 `verifier_meta.json`。
当前 protocol 为 `public-verifier-v10`：多段 source quote 和 artifact ellipsis 分片核对；公开
oracle 用于派生 artifact 时注册 copying/mixing/substitution provenance check；非
public-evidence criterion 的无意义 sample 机械归一化为 `[]`。

## Writer Feedback

反馈由 main agent 在执行期建立，而不是 prep-agent 预造一个通用 evaluator。

对 CT geometry，公开闭环是：

```text
geometry -> FBP(sinogram) -> reconstruction
         -> SSIM/MSE against public input reference
         -> assert SSIM threshold AND assert MSE threshold
         -> fail: update search; pass: replay serialized geometry and verify again
```

prep 应研究 LEAP 的实际参数路径和离散行为，并可用公开 metric 做有限的单变量敏感性
诊断；它不能做参数优化或生成最终参数。v1/v2 都没有发现角度权重边界，说明“报告更长”
不等于“新增先验更好”。skills 要求 main agent 建立执行期反馈，职责不与 prep 重叠。

语义审计题不存在真正数值 oracle。`evidence-audit` 只能提高覆盖和证据锚定，不能把
主 agent 的 Yes/No/Unknown 判断伪装成确定性 PASS。

上游规范只能补充 task-local 规则，不能覆盖它。Variant v1 的回归就是反例：更符合
VEP normalized allele 的解释反而违反了题目显式 manifest。任务明确要求 offline 或
local-only 时，prep-agent 也不得调用外部研究。

## 配置

ALE Claw 默认值：

```yaml
task_specific_prep: false
task_specific_prep_max_steps: 15
verifier: false
verifier_max_steps: 30
verifier_max_repairs: 0  # audit-only default; repair is explicit opt-in
```

下一轮四臂定义为：`base`、`prep`、`verifier`、`prep_verifier`。skills v2 已确认全部
实际加载但没有总体正向信号，因此从默认实验轴隐藏，代码兼容性仍保留。实验臂显式写
开关。缓存目录可分别用 `ALE_TASK_PREP_CACHE_DIR` 和 `ALE_VERIFIER_CACHE_DIR` 覆盖。
