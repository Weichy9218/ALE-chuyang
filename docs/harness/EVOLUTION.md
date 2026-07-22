# Harness 版本演化

本轮演化从 2026-07-17 的 general prep 和 writer-side skills 开始，到 2026-07-20 的 `task-prep-v10`、`public-verifier-v10` 和同 endpoint 四臂全量结束。每次协议升级都对应一条可复现的轨迹失败；canary 用于检查该失败是否消失，全量用于观察总体结果和新增副作用。

协议号与独立实验数量不对应。Prep v2 至 v4、v6 和 verifier 早期内部 judge 版本没有各自完整的 pgl 对照。当前材料可追溯七个 Prep 阶段、Verifier v4 至 v10 七个版本，以及相应 smoke、canary 和 full。

## 时间线

| 日期 | 阶段 | 运行 | 当时结论 |
|---|---|---|---|
| 2026-07-17 | old general prep | 26 题四臂 | general prep `-0.0321`；短 notes 和浅文件读取没有稳定收益 |
| 2026-07-18 | task-specific prep v1 | 26 题三个新臂 | Prep 能改变搜索和数据处理；报告过长、skip 失效、Variant 与 CT 暴露错误先验 |
| 2026-07-19 | skills v2 | 25 题同协议四臂 | skills `-0.0161`，50/50 load 成功；当前两个通用 skills 不应默认加载 |
| 2026-07-19 | verifier smoke | 5 题四臂 | 独立审计能找公开错误；TCGA 15/16 字符产生 false positive；repair 默认改为 0 |
| 2026-07-19 | verifier compare | 25 题四臂 | 34 fail 中 30 条有公开证据，3 条明确误报；低分 artifact 仍可 pass |
| 2026-07-20 | prep v8 / verifier v6 canary | 10 题四臂 | Prep 交付恢复；7 次 repair 产生振荡、错误传播和 CT leakage |
| 2026-07-20 | 窄协议 canary | FluSight、Variant、Legal | Prep v9/v10 与 Verifier v7/v8/v9 逐项消除已知失败 |
| 2026-07-20 | v10 full | 26 题四臂 | 0 repair；没有总体 uplift；审计 precision、provenance 和完整性证据改善 |
| 2026-07-21 | prep v17 六题 canary | 六题两臂 | 6/6 空报告；机械 gate 误杀合格报告；准入收紧到头 |
| 2026-07-21 | prep v18 / verifier v14 | 协议改写 | prep 转向运行时+合同清单并默认开启；verifier 拆维度修反馈通道；v13 六题门结论撤回 |
| 2026-07-21 | prep v18 六题配对 | 六题两臂 | 生成率 6/6 但配对 `-0.0562`；交付 artifact 零调用；Agora 清单定向优化 `-0.34`；SEC `+0.26` 与 prep 无关。消费问题成为主矛盾。见 [results/prep_v18_six](results/prep_v18_six/) |
| 2026-07-21 | v15/v19 与 v16/v20 | 代码改写（未跑配对） | 预提交 `verify` 工具；删 `output/` 字符串边界；quote 重定位与机械修复轮；ambiguous 以 advisory 运行；self_check 一等字段；机械合同对账。见 FABLE.md |
| 2026-07-21 | v21/v17 | 代码改写（v20/v16 六题同日在 pgl 启动，两组不混） | prep 报告改文件式消费 + digest；self_check 限定结构覆盖；verifier lint 逐条隔离；预检/审计移到 prep 之后（仅合并臂）；批量定位与分块 staging；dispute 门控评审后否决 |
| 2026-07-21 | v18 | 代码改写（v20/v16 六题读数已回：prep 正、verifier 6/6 构建 error） | verifier 零权威：删 Auditor、blocking 恒 false、builder 契约名聚焦、overall 改覆盖描述；六题 smoke 待跑 |
| 2026-07-21 夜 | v21/v18 与 v22/v19 | 26 题两臂 ×2，串行 | 机制全部达标（冻结 26/26 与 25/26，`verify` 全调用）；verifier `+0.0209`（t 2.57）在第二轮变成 `+0.0005`（t 0.05），未复现；prep `-0.0070` 与 `+0.0163`，方向翻转。见 [results/full26_two_rounds](results/full26_two_rounds/) |
| 2026-07-22 | v23 | 代码改写（未进实验） | prep 修三处交付故障链；加 self_check 交付开关与无测试对照臂开关；verifier 冻结在 v19 不动 |

机器结果和历史均分见 [results/run_summary.csv](results/run_summary.csv)。原分析和 run 表位于 [archive](archive/README.md)。

## 旧 General Prep

旧 Prep 只做一次 completion，读取前几个文件的短 head，搜索关闭，输出约千词通用 notes。26 题四臂均分为 base 0.6415、old prep 0.6094、skills 0.6214、combined 0.6103。所有配对检验 `|t| <= 1.00`。

该轮确认 plumbing 可运行，也显示浅层摘要没有稳定作用。它没有测试当前的多轮工具研究、runtime probe、task-local source 和缓存协议。

## Task-Specific Prep v1

v1 将 Prep 改为多轮研究代理，可读取公开文件、执行任务软件并生成完整报告。26 题三个新臂共 78 个 unit；base 使用前一天历史结果。

Prep 相对历史 base 为 `+0.0023`。SSE、CRF4、FluSight 和 TCGA 出现可解释单题变化，Variant 从 0.999 降到 0.793，CT 三个新臂都为 0。52 个 Prep 实例中 49 completed、3 failed、0 empty；42 次真实研究消耗约 9.76M input tokens。

两条问题进入后续设计：Prep 必须允许沉默并限制报告；task-local contract 必须高于 VEP 等上游惯例。CT 还显示连续参数搜索会遗漏 360 度附近的离散分支。

## Skills v2

两个 writer-side skill 在实验前被缩短：

- `deliverable-contract` 从约 520 词缩到 194 词，删除“写完整 checker 并留在 output”的要求，只保留公开 contract 核对。
- `evidence-audit` 从约 392 词缩到 180 词，限定为多源 consistency、claim verification 和 Yes/No/Unknown ledger。

25 题同协议结果为：

| Arm | 均分 | 相对 base | 正 / 平 / 负 |
|---|---:|---:|---:|
| base | 0.6068 | 0 | 0 / 25 / 0 |
| skills | 0.5907 | -0.0161 | 3 / 15 / 7 |
| prep v5 | 0.6056 | -0.0012 | 4 / 17 / 4 |
| skills + prep | 0.5842 | -0.0226 | 2 / 16 / 7 |

50/50 个 skill-enabled unit 都加载了至少一个 skill。`deliverable-contract` 大部分时间重复强 writer 已有的文件、列、schema 和 determinism 检查，没有提供独立 source truth。`evidence-audit` 在 Agora 有 `+0.167` 的窄正例，在其他任务没有重复证据。

当前决策是将 `deliverable-contract` 从 active 默认集合退役或重写为带 parser 和检查脚本的 `structured-artifact-reconcile`。`evidence-audit` 保持默认隐藏，只在预先定义的多源 verdict matrix 任务做 `k>=3`。实验否定当前两个实现的默认净收益，没有覆盖带工具、脚本、locator 或领域 source 的 capability skill。

MarkItDown 适合作为 `document-evidence-index` 的可选 converter backend。ALE 需要 page、sheet、cell、table locator、source SHA 和 extractor version；仅增加“使用 MarkItDown”的提示不会提供这些能力。SEC 的主要缺口是 financial field 到 filing/page/table/row/unit/year 的 lineage，继续重复 schema checklist 没有作用。

## Verifier Smoke 与 v4 Full

Verifier 引入两个 fresh context：builder 在 solve 前固定 spec，runner 在 solve 后检查 artifact snapshot。架构吸收了独立 artifact grader、结构化 feedback 和有限 repair loop。

5 题 smoke 能重算 SEC schema 与抽样字段、CT MSE/SSIM，也能把 FluSight 未来 outcome 标为 unverifiable。TCGA 公开规则一处写 first 15 characters，示例却是 16 字符。Runner 承认冲突后仍 fail 16 字符 artifact，形成明确 false positive。自动 repair 因此默认改为 0。

随后 25 题 `verifier_compare` 得到 317 条 verdict：269 pass、34 fail、13 unverifiable、1 error。人工复核 34 个 fail，30 个有公开证据，1 个边界项，3 个明确误报。MARC 0.2、CRF4 约 0.64 和 SAP 0.25 仍可 overall pass。

这轮还存在 endpoint 与 arm 混杂。Verifier 两臂 repair 为 0，所以分数差只反映 writer rollout 和 endpoint。后续 full 将四臂改为同一 endpoint。

## Prep v7 至 v8

Prep v7 试图删除 prescriptive 内容。它在 `claim + solver_impact` 中匹配 `must`、`should`、`use`、`map` 等词，命中后丢弃整条 finding。20 个 fresh agent 共生成 79 条 finding，最终只保留 26 条；51 条只因 `solver_impact` 中的正常方法表达被删。5 份 raw response 因过滤清空而变为 empty。

Writer 20/20 都在第 1 至 4 次工具调用读取报告，35 个保留 source 中 30 个被回查。问题发生在 handoff 前的 lexical filter。

v8 删除该词表，只保留结构、source、confidence 和 3 条上限。10 题 canary 中 27/27 条 raw finding 全部进入报告，20/20 个 writer 读取，45/54 个 source 被回查。信息损失修复后，Variant alternate key、FluSight 未回测 heuristic 和 CT endpoint 漏检仍在，说明下一阶段要控制 finding 内容。

## Verifier v5 至 v6

v4 snapshot 在 American option 的 output symlink 上失败。v5 改为拒绝并记录 symlink，保存 snapshot 与原 output 的初始 hash，并在 runner 后重新计算两者。

v6 为每条 criterion 增加 `source_status` 和 `source_evidence`。`ambiguous`、`contradicted` 和 `missing` 由代码强制转为 unverifiable。10 题 canary 中 TCGA 的 15/16 冲突和 Variant 的 manifest/count 冲突不再触发 repair。

Canary 开放一次 repair，共 7 个 transition：

| 题目 | repair 结果 | ALE 结果 |
|---|---|---:|
| BPMN 两臂 | 部分旧 fail 消失，同时新增 fail | 0.8119 / 0.8129 |
| SEC combined | 下游 QA 自洽，错误上游值继续传播 | 0.6482 |
| SAP verifier | 公开随机数复现通过，主要评分缺口仍在 | 0.25 |
| TCGA combined | 脚本变化没有改变隐藏 cap | 0.84 |
| CT verifier | 整图复制 reference，被 evaluator anti-copy 拒绝 | 0 |
| CT combined | 混入 32% reference，绕过 evaluator | 1 |

原始 10 题 combined 均值被 CT 无效 1.0 抬高。排除 CT 后 prep main 为 `-0.0161`，verifier main 为 `-0.0033`。这轮决定最终 full 关闭 repair。

## Prep v9 至 v10

v9 要求隐藏 outcome 的模型启发式先在公开 task-local holdout 或 backtest 上优于明确 baseline。FluSight agent 随后执行 1,040 点 backtest，发现 persistence MAE 162.98，优于 linear 225.09 和 recursive growth 751.13。同轮 WIS 从 132.10 降到 116.84。

v9 对 Variant 的限制仍不够。报告将 normalized deletion allele 描述为 representation mismatch，writer 继续用 `-` 做 frequency lookup，得分再次从 0.999 降到 0.793。

v10 明确规定：local rule 指定 original、submitted 或 exact key 时，没有另一条 local rule 定义 mapping，就不能把 alternate representation 当作 lookup key。Canary 与 full 两次得到 base 0.793、prep 0.999，最终 pipeline 显式调用 `frequencies.get(submitted_alt)`。

## Verifier v7 至 v10

CT repair 促使 v7 要求公开 oracle 任务注册 provenance criterion。v7 同时允许 source quote 包含多段 excerpt 并逐段定位。Legal canary 中 source quote 可定位，但 artifact 的省略号仍被当作原文字符。

v8 要求 source quote 支持 requirement、check 和 expected 的全部限制。没有 quote 支持的 non-empty 限制被正确降为 ambiguous。Artifact ellipsis false fail 仍存在。

v9 将 artifact 中的 ellipsis 或 omission marker 当作 excerpt separator。Legal 的 17 个 quotation 全部逐段匹配；无 quote 支持的 manifest criterion 继续 unverifiable。

首次 v9 full 中，American builder 为 deterministic criterion 填了无意义 sample，lint 让整份 spec error。v10 对所有非 `public_evidence` sample 机械清空，仍要求 public-evidence locator 固定。最终 52/52 spec 构建成功。

## v10 Full

最终配置使用同一 endpoint，26 题四臂，`prep.max_steps=15`、`verifier.max_steps=30`、`max_repairs=0`。104 个 unit 都有 `run.json`，100 completed；PE 四臂的 evaluator 404 单独排除。

25 题 prep-only 相对 base 为 `-0.00977`，2x2 prep main 为 `+0.02205`。Verifier-only 为 `+0.01010`，但 verifier 没有修改 artifact。Combined 为 `+0.06396`，去掉 CT 与 SSE 后为 `+0.01155`。

52 个 Prep metadata 全是 v10，50 份非空报告全部被 writer 读取。52 个 Verifier spec 全成功，344 条 criterion 中 156 条 unverifiable、6 条 fail。source gate 将 145 条 ambiguous、2 条 contradicted 和 1 条 missing 从 fail 路径移除。

American 和 Moodle 的 runner 通过任务 runtime wrapper 改动原 output，双 hash 将 4 次运行记为 error。该证据将执行隔离列为 v11 的第一优先级。

## v11：外部先验与可维护报告

v10 的 Prep 主要从本地输入和 runtime 提炼最多 3 条 finding，无法以权威 web 来源独立支持 `/input` 缺失的领域知识。v11 改为目标 1 至 3、硬上限 5 条 entry；每条必须说明 `input_gap`、具体风险、使用条件和复核方法，完整报告限制为 6500 字符。任务允许联网时优先检索官方规范、监管材料、维护者文档和原始研究。

`PREP_REPORT.md` 仍位于 task root 的 `task_prep/`，但 v11 明确将其定义为低于题面和 `/input` 的可编辑工作先验。Writer 可在后续调研中修改，宿主保存初始和最终版本及哈希。Prep 与 verifier builder 由历史串行顺序改为从同一公开任务表面并发启动，双方不能读取对方输出。Verifier 协议同时升为 v11，使旧 builder cache 不会跨越新的权威边界。

v11 首轮只比较 6 个预定义任务的 base/prep 两臂。结果完成前不把设计变化解释为得分提升。

首轮 12/12 unit 完成，均值为 `0.73019 -> 0.61277`，配对差 `-0.11741`。6 题中 2 题提高、1 题持平、3 题下降。6 份报告全部非空，共 17 条 entry，平均 5487 字符；只有 BPMN 调用 web，而且只 search、没有 fetch。Writer 读取全部报告，回查 17/29 个 source，修改 5 份。该结果说明 schema 新增 `input_gap` 不足以阻止本地 finding 填满报告，提示词鼓励 web 也不足以保证打开来源。

## v12：研究过程机械门槛

v12 将目标降为 1 至 2 条、硬上限 4 条、报告上限 5000 字符。响应必须声明网络策略。允许联网的 `use` 报告必须实际调用 `web_search` 和 `web_fetch`，至少一条 entry 引用已打开 URL，local-only entry 最多一条；禁止联网的任务如果调用或引用 web，报告被 quality gate 置空。没有外部知识达到质量门槛时应 `skip`。

协议升级改变 fingerprint，v12 不复用 v11 cache。复验继续只使用同一 6 题的 base/prep 两臂。

最终 v12 的 12/12 unit completed，均值为 `0.71844 -> 0.68647`，配对差 `-0.03196`，`t=-1.70`。4 次 use、2 次 skip，共 6 条 entry；3 个 allowed 任务全部 search+fetch，3 个 prohibited 任务全部无 web。机制符合设计，但 2 题提高、1 题持平、3 题下降，仍无总体正收益。系统在 v12 停止迭代，Prep 保持默认关闭。

## v10 相比最初系统

| 最初问题 | v10 改动 | 已有验证 | 当前价值 |
|---|---|---|---|
| Prep 只看少量文件并写通用 notes | 多轮 task-local research、runtime probe、最多 3 条结构化 finding | 50/50 非空报告被读取，108/138 source 被回查 | plumbing 与 adoption 可审计 |
| Prep 正常 finding 被词表删除 | 删除 lexical filter | v8 27/27 raw finding 保留 | 消除确定的信息损失 |
| 预测 heuristic 无公开检验 | 要求 holdout/backtest 优于 baseline | FluSight 1,040 点 backtest | 将可复现 proxy 与猜测分开 |
| 上游惯例覆盖 task-local key | exact/original/submitted key guard | Variant canary 与 full 两次 0.793 到 0.999 | 消除稳定有害路径 |
| Builder 事后看 artifact 才定标准 | solve 前固定并缓存 spec | 每题两臂 fingerprint 和 spec SHA 相同 | 避免按答案改标准 |
| Source 存在但不支持加严规则 | source_status 和全字段 entailment | 145 ambiguous、2 contradicted 自动 unverifiable | 降低 false blocking |
| 多 excerpt 与 ellipsis 被要求连续 | 分段定位 source 与 artifact quote | Legal v9 quotation supported + pass | 修复明确误报 |
| Symlink 与 verifier 写入缺少证据 | symlink receipt、snapshot 与原 output 双 hash | v10 捕获 4 次原 output 副作用 | 完整性问题可观察 |
| 公开 metric 可被 reference copy/mix 利用 | provenance criterion | v10 CT 独立 FBP 与交付数组一致 | 能区分 metric pass 与合法 derivation |
| Arm 使用不同 endpoint | v10 full 使用同一 endpoint | 104 unit 同控制面 | 减少实验混杂 |

这些优化的验证集中在机制正确性和审计质量。总体 ALE 提升仍未证明：旧 full prep 为 `+0.00093`，v10 full prep 为 `-0.00977`；两个值都接近零。Verifier full 都是 0 repair，无法用 arm 分数判断 verifier 的修复收益。

## Verifier v12：冻结脚本与隔离执行

v12 删除自然语言 criterion、事后 LLM Runner 和 `repair_hint`。Builder 现在生成普通测试脚本、结构化 source、参数数组和正反 fixtures。Harness 机械定位 quote 并保存 source hash；独立 Auditor 在 Writer 前给出 `supported / ambiguous / contradicted / missing` source audit，并检查 Checker 与 requirement 是否一致。

Writer 完成后，Executor 使用 Landlock 只读开放公开 input、题目 software、artifact snapshot、checks 和系统 runtime，仅开放独立 scratch 写入；libseccomp 禁止网络 syscall。原 output、Prep、hidden reference 和官方 evaluator 不在 allowlist。每项测试连续运行两次，结果不一致、隔离启动失败、超时或非法输出都记为 `error`，不归因于 artifact。

`verifier_max_repairs` 默认改为 1。反馈按 source、observed failure、root-cause hypothesis 排序；Writer 先复核 source，再自行判断和修改。每轮 Writer 响应后重跑完整冻结测试包。该版本先完成机制测试，修复收益和误修率仍需在 pgl 预定义任务上复验。

## Verifier v13：独立结果报告与真实执行优先

v13 明确区分 Prep 的求解前能力准备和 Verifier 的提交前验收。两者从同一公开任务表面并发启动，Verifier 不读取本轮 Prep artifact。候选测试记录 `task_software`、`public_recompute` 或 `simulation` 执行方式及选择理由；模拟测试由 Harness 机械降为 non-blocking。

Executor 保存两次运行的 command、return code、stdout、stderr 和耗时。失败不再强制生成根因，`analysis` 可以为空。每轮完整报告同时写入宿主记录和 Writer 可读路径，反馈正文只保留 source-first 摘要。该版本使用六题同期四臂实验分别测试 repair 1 和 3，结果完成前不声明收益。

首轮六题运行发现原 fixture map 容易被 Builder 解释成 `{path, content_base64}` 单文件对象，导致整包 lint 失败。协议随后改为显式的 `{path, encoding, content}` 文件数组：文本直接交付，Harness 在 staging 时编码；只有二进制内容使用 base64。Executor 同时允许 `observed` 和 `evidence` 保留非空 JSON 结构。该修改删除了无语义价值的手工传输编码，并使 Auditor 可以直接阅读文本 fixture。

pgl 的任务镜像把 `uv` 安装在 `/home/user/.local/bin`，部分题目的依赖位于
`input/runtime_env/.venv`。隔离层将这些只读路径加入 runtime allowlist，并允许 `uv` 所需的本地
`socketpair`；创建网络 socket 仍返回 `EPERM`。直接探针确认 `uv run` 可以启动。Auditor 改为
读取只读 candidate manifest 并按需打开 staged script 和 fixture，避免在调用中再次嵌入全部
文件内容。Auditor 完成后 Harness 删除容器内的 candidate suite；Writer 首次完成后才从宿主
保留的冻结 manifest 重新 staging，防止 Writer 在首次求解时枚举 `/tmp` 并针对 Checker 优化。

六题 pilot 还发现单一 source 不能证明公开重算的完整 expected。Digital 的筛选规则来自 brief
和 governance，而具体计数还依赖 Parquet；只引用 brief 就把 `449/109/104/196/4.49` 设为
blocking，缺少数据 provenance。v13 因此改用非空 `sources` 数组，机械定位并哈希每项来源；
二进制或不透明数据用 `locator=file` 冻结 whole-file hash。任一来源缺失时，该测试不能 blocking。

repair=3 的 SSE pilot 暴露了枚举标签歧义。规则只说具体费率另行规定，Auditor 却允许 Checker
强制 `conclusion=Unknown`，而 Writer 用 `No` 表示 provided rules 不给出数值。公开材料未定义
该问法的标签映射，因此这是一条 false blocking。Auditor 现要求来源直接支持命题到枚举标签的
映射，不能从缺失信息或一般语言习惯自行选择 `No` 或 `Unknown`。

六题正式门结果没有支持扩展。repair=1 的 Verifier 主效应为 `+0.00653`，但没有发生 repair；
repair=3 为 `+0.00225`，唯一 repair 正是上述 false blocking，去掉 SSE 后为 `-0.03064`。
修正后的 SSE 两臂 canary 均把语义标签映射标为 `unverifiable`，0 repair。两个 repair 设置都
没有通过预注册门，因此未启动 26 题。Analyzer 现在同时记录 repair 前后的 suite hash、snapshot
hash 和 blocking authority 变化，能够机械确认是否重跑同一冻结包。

## Prep v17：准入收紧到无法产出

v17 把准入标准改成单一决策闭环，只允许五类 focus，并要求每份报告附一次成功的执行回执。
六题机制 canary（`.logs/ale/prep_v17_selected_six`，2026-07-21）6/6 空报告，prep 臂等价于
base 臂并多花约 24.5 万 input token。失败分两类。

代码 gate 误杀两份合格报告。`missing_impact_coverage_evidence` 要求 `impact_coverage` 的
`N/N` 字面串原样出现在某条 source evidence 里，这是字符串巧合检验，BPMN 和 Digital 两份带
成功执行回执的报告都死在这一条上。`nonexternal_focus_used_web` 在 `decision == "skip"` 时
`focus` 为 null，于是"查了网页、发现补不上、诚实 skip"被记成违规。

预算掐死了唯一确证有效的机制。Variant 已经 fetch 到 Ensembl consequence 排序页面，在 6 步、
300 秒、每轮 12KB tool result 的预算内放弃并 skip。SEC 已用 3.10 绕过版本冲突，验证探针用了
不存在的 PDF 模块，也 skip。

结论是继续收紧准入没有空间。

## Prep v18：运行时准备、合同清单、精确事实

v18 换方向。Prep 在 writer 的同一沙箱里先把题目运行时跑通并留下真实状态，再从题面和
`input/` 编译交付物合同清单，最后才补精确外部事实和可复用工具。这三件事按 26 题的失分
体量排序：合同覆盖不全最大，运行环境阻断其次，外部精确取值最少。

schema 只保留能被文件系统和响应结构机械判定的字段，删除 `impact_coverage`、`confidence`、
`focus.kind`、`task_relation`、`applies_if`、`expected_signal`、`validation_command` 和
`validation_signal`。校验改为逐条丢弃并记入 `dropped`，不再整包拒绝。预算从 6 步 300 秒放宽到
30 步 1800 秒，每轮 tool result 从 12KB 放宽到 60KB，搜索不再限定 focus 类型。缓存、
`compute_task_fingerprint` 和 `validate_prep_sources` 删除，因为 prep 现在会在沙箱里留下真实
状态，复用缓存会声称环境就绪而实际什么都没做。

保留的边界是 Prep 与 Verifier 的分工：Prep 不读、不写、不检查候选 `output/`，代码对命令、
检查项、writer action 和 artifact 内容强制这一条。Prep 默认开启。

## Verifier v14：测量、权威、复核拆维度

v13 用一个 `status` 字段同时决定测量结果、权威性和是否再叫 Writer，导致只有硬阻断失败能
进入 Writer，其余测量烂在内部日志；v13 六题门"Verifier 无效"的结论因此撤回（实验结构上
无法暴露价值）。v14 拆出 execution/observation/authority 三维和四类顶层输出
（hard_mismatches、review_items、execution_errors、coverage_gaps），`needs_review` 驱动
复核；部分覆盖的 checker 以 advisory 运行；删除 Checker 的 `analysis` 字段；
`verifier_max_repairs` 改名 `verifier_max_review_rounds`，output 无变化即停。

## 2026-07-21：v15/v19 —— 反馈移到 DONE 之前，删字符串边界

动机与完整记录见 [FABLE.md](FABLE.md)。verifier-v15 新增 writer 预提交自检：`verify` 工具
（`verifier_precheck.py`）在 DONE 前对当前 `output/` 快照运行完整冻结测试包，默认 2 次，
标准、隔离、hash 复验不变，冻结包首次调用才 staged；主运行文本纳入 dispute 解析。
task-prep-v19 删除 `_targets_writer_output` 字符串检验（v18 的"代码强制"实为文本净化，
误伤 check 字段、writer_action 和自检脚本 artifact），边界执行点回到"谁在什么时候运行"。

## 2026-07-21：v16/v20 —— 信号率、self-check 一等公民、合同对账

同日第二轮，记录同在 [FABLE.md](FABLE.md)。verifier-v16 修信号产生率：quote 唯一时行号
错误机械重定位；定位失败给 builder 一轮机械修复（失败数严格减少才采用）；ambiguous 来源
的检查以 advisory 运行并附审计 caveat（v10 数据里 344 条 check 有 156 条未运行，其中
ambiguous 145 条）。task-prep-v20 把合同自检升为一等输出字段 `self_check`，解析与渲染拆分，
结构化 contract 保留；新增 `contract_crosscheck.py` 在 prep_verifier 臂机械对账两份独立
合同阅读引用的公开文件，双向差集注入 writer。清理：删除孤儿 `_cache_lock.py` 和
`VerificationResult.failures` 别名。

## 2026-07-21：v21/v17 —— 文件式交接、条目级 fail-open、冻结时序、dispute 生效条件

同日第三轮，v20/v16 六题两臂实验已在 pgl 启动，本轮改动只进本仓库，读数分开。四个设计
变化，每个对应一处结构性缺陷：

- **prep 报告改纯文件消费**（v21）。内联报告的 12,000 字符预算和尾部截断是 v18 三题
  artifact 引用丢失的直接原因，v20 用"节前置"绕开，v21 直接取消内联：完整报告只存在于
  `task_prep/PREP_REPORT.md`，首轮 prompt 注入 digest（运行时状态、self_check 命令、
  条目数、读文件指令）。报告上限放宽为 48,000 字符安全上限，超限截断在文件头部声明，
  残缺清单不再伪装成完整清单。新失败面是"writer 不读文件"，读数为 transcript 中对报告
  文件的 read 调用率。
- **self_check 限定结构覆盖**（v21）。为合并臂消除与 `verify` 的功能重复：self_check 查
  "缺不缺"（存在性、字段、拼写、行数、编码、跨文件一致），不硬编码期望取值、不判对错；
  判定是 verifier 的独占角色。prep 提示 writer 自检（digest 点名命令）是设计本意，因为
  self_check 零权威。
- **verifier lint 逐条隔离**（v17）。旧 lint 对候选套件整包拒绝，一条 schema 违规没收
  writer 的整个 `verify` 工具，与 prep"逐条丢弃、never 整包拒绝"的原则矛盾。v16 六题的
  实测把这条从原则问题变成主失因：4/6 题因单个 locator 格式错误整包 lint 失败，损失全部
  测试。v17 只在顶层结构损坏时整包失败，单条违规丢该条记 `dropped`；机械修复轮的采纳
  条件加"lint 丢弃数不增加"，防止 builder 借修复轮丢弃定位失败的测试。
- **预检与审计移到 prep 之后**（v17，仅合并臂生效）。`environment_healthy` /
  `checker_reproducible` 是环境判定，v16 在 prep 并发改造环境的同时测它们，判定的环境和
  执行的环境不一致：依赖 prep 装好的运行时的 checker 会被错误地永久降级。v17 把 staging、
  fixture 预检、审计移到 prep 完成后、prep 产物 staging 前。两个单臂的行为与 v16 相同；
  收益只覆盖 prep 能装好的运行时（BPMN 类 Docker 阻断任务救不回来），是否值得固化以
  合并臂 canary 的 `execution_errors` 读数为准。builder 的标准生成仍与 prep 并发且互不
  读取，独立性不变。
- **dispute 门控：评审后否决。** 曾设计"主文本 dispute 只对 writer 见过的差异项生效 +
  `evidence_cited` 读数"，堵"DONE 消息逐条 dispute 零成本关复核轮"的理论洞。否决理由：
  历史全部 run 实测 dispute 为 0，为从未发生的滥用加门控状态机是拿真实复杂度换假想安全；
  出现真实滥用样本再议。

同轮工程修复（不改协议语义）：来源定位与冻结后复验从逐条 RPC 改为批处理（上限情形从约
170 次往返降到个位数）；suite staging 从单条巨型 shell 命令改为分块传输（消除
`MAX_ARG_STRLEN` 128KB 的隐性上限）；执行前复验 `verifier_sandbox.py` 自身 hash（此前只
复验 checker）；反馈的内联完整报告加上限；`_parse_json_object` 统一为扫描式宽容解析
（builder 回复带前导散文不再整包失败）；agent loop 的工具分派移出事件循环线程（`verify`
一次最坏几十分钟，此前会冻结增量日志拉取和 MCP 心跳）。

## 2026-07-21：v18 —— 零权威 verifier

v20/v16 六题读数当日回来：prep 臂 6/6 报告、self_check 调用 5/5、配对为正；verifier 臂
6/6 构建 error，4/6 因单个 locator 格式错误整包 lint 失败，12 个冻结测试只执行 2 个，
dispute / repair / 复核轮全部为 0。诊断是结构性的：硬权威要求来源蕴含、checker 对齐、
来源无冲突三项语义证明，为此设 Auditor 和五项 gate，链条十步、每环都在断；而零权威的
prep self_check 被 writer 5/5 调用。结论是放弃硬权威这个目标本身。

v18 的变化：删除 Auditor（三项判定只为硬权威发许可，零权威无许可可发，构建省一个 LLM
agent）；`blocking` 冻结时恒为 false，builder 主张留档为 `requested_blocking`；
`overall` 从 pass/fail 聚合改为覆盖描述（measured / error / unverifiable），不留全绿
目标；反馈与 `verify` 工具描述全部改为参考测量措辞；builder prompt 增加契约锚定——题面
点名的文件、字段、标识符逐字进 checker，check id 以契约义务命名
（`contract.<file>.<obligation>`），宁可广覆盖不深钻单条。保留的每一环都有独立于权威的
理由：lint 逐条（结构安全）、定位与修复轮（引用真实性）、fixture 预检（坏 checker 高频
误导 writer）、冻结 hash（测量可信）、隔离双跑（不污染产物、结果确定）。

六题 smoke 的读数：冻结成功率（对照 v16 的 0/6）、每题实际执行检查数（对照 12/2）、
`verify` 调用率与调用后 output 变化、review_items 采纳率、删减读数（零权威是否仍诱发
delete-to-pass）。

## 2026-07-21 夜：两轮 26 题 —— verifier 的单轮显著结果没有复现

两组实验串行跑完，都是同样 26 题、同样两个 treatment 臂、同一套历史 base，完整数据在
[results/full26_two_rounds](results/full26_two_rounds/)。

| 臂 | 实验1（v21/v18） | 实验2（v22/v19） |
|---|---|---|
| prep | `-0.0070`（t `-0.77`，n 24） | `+0.0163`（t `+1.26`，n 23） |
| verifier | `+0.0209`（t `+2.57`，n 26） | `+0.0005`（t `+0.05`，n 25） |

机制读数全部达标，而且是历史最好：冻结成功率 26/26 与 25/26（对照 v16 六题的 0/6），
所有冻结成功的题都调用了 `verify`，零权威没有诱发 delete-to-pass。

分数上，实验1 的 verifier `+0.0209`、t `+2.57` 没有在实验2 复现。v18 到 v19 只加了信封
字段兜底和构建失败时的响应记录，两处都是 fail-open 方向，解释不了 `+0.0209` 到 `+0.0005`
的落差，所以更合理的解释是运行方差而不是协议变化。单题层面同样不稳：digital_audience 在
verifier 臂从 `+0.0925` 翻到 `-0.1247`，Variant 在 prep 臂从 `-0.1374` 翻到 `+0.0686`，
跨轮方差比配对均差大一个量级。

功效不足的直接原因是零效应题占了一半：两轮都算分的题里，delta 在两轮都恰好为 0 的
verifier 有 14/25、prep 有 11/21。这些题要么两轮满分（没有改进空间），要么两轮零分
（失败原因在 prep 和 verifier 的作用范围之外）。继续在全 26 题上重复，每轮买到的信息很少。
下一轮改用预先剔除零效应题的子集，剔除清单在看结果之前定好。

跨两轮稳定的单题效应只有两个：agora 在 verifier 臂 `+0.1597` 和 `+0.1550`，Variant 三次
出现同一个 0.9304 到 0.9990 的跳变。

## 2026-07-22：v23 —— prep 交付故障链，协议其余部分冻结

26 题的 `dropped` 字段暴露三条独立的 prep 交付故障，都不在产出设计里，而在最后一步：

- **artifact 收集把"文件不存在"记成"读不出来"。** `wc -c` 的 stdout 解析放在返回码检查
  之前，文件不存在时 stdout 为空，`int("")` 先抛异常，于是所有缺失都归进 `unreadable`，
  `artifact:missing` 分支实际是死码。审计记录因此指向了错误方向。v23 先看返回码再解析，
  并在出现任一种失败时把 scratch 里实际存在的文件列进 `dropped`。
- **scratch 初始化超时吃掉整个 prep 机会。** 它在 LLM 会话开始前跑，撞上 60 s 上限就是
  `llm_turns=0` 的失败。v23 给它单独的 180 s 并重试一次，命令是幂等的 `rm -rf && mkdir`。
- **self-check 脚本在空草稿上静默退出。** 预检要求脚本打印点什么，而脚本作者不知道有这道
  门。v23 在提示词里写明空草稿和缺文件时也必须向 stdout 报告，缺文件是要打印的发现。
  没有改成两段式预检：那需要新增 schema 字段声明合成小样的位置，而根因是契约没说清楚。

同时加两个实验开关，都不改默认行为。`task_specific_prep_self_check` 关掉时 prep 的提示词、
预算和产出都不变，只撤下 self_check 节、digest 命令和脚本 artifact，用来单独测 self_check
通道的净效应。`writer_self_review_hint` 是 verifier 的无测试对照臂：只给一句提交前对照
题面契约自查 output 的提示，用来区分"测量内容有价值"和"知道会被测量"。

verifier 冻结在 v19 不动。曾经改过三处又撤回：builder token 与冻结测试数的比值告警、
`ready_but_unexecutable` 状态、meta 里的 `frozen_tests` / `executable_checks` 字段，
理由是原始量已经落盘，这些读数属于分析脚本，不该固化进 agent 代码；`unverifiable` 上限
从 8 收到 3 方向正确但会改 builder 行为，与同轮的 self_check A/B 撞在一起会引入第二个
归因变量。归因实验出结果之前，协议不再加变量。

## 当前状态

- Prep 当前为 v23，默认开启。两轮 26 题实测见上；v23 的三处修复未进实验。
- Verifier 当前为 v19（零权威），默认关闭；启用时 writer 有预提交 `verify` 工具（默认
  2 次），DONE 后至少一轮 advisory 复核。机制达标，分数收益未证明。
- 实验臂：`harness/run/launch.py` 的 `ARMS` 有 base、prep、verifier、prep_verifier 四个
  常规臂，加 prep_nosc（prep 但撤下 self_check）和 self_review_hint（无测试的自查提示）
  两个备用臂。备用臂只在显式指定时才跑，默认不进实验。
- `deliverable-contract` 不进入默认 skill 集；prep 的 self_check 机制已经覆盖其目标场景。
- `evidence-audit` 默认隐藏，只在多源 verdict matrix 任务复验条件效应。
- 当前 v10 结果冻结在 [results/latest](results/latest/)，旧实验不再散列于 harness 顶层。
- 本仓库（batchcom ALE-chuyang）是 v23/v19 的唯一权威副本。pgl 上另有他人的实验在跑，
  同步到 pgl 主仓库前先确认没有正在运行的 run。
