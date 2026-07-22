# Verifier

协议 `public-verifier-v19`，默认关闭，实验臂开启。实现在
[`verifier.py`](../../ale_run/agents/ale_claw/verifier.py)（Builder/Auditor/冻结/反馈）、
[`verifier_runtime.py`](../../ale_run/agents/ale_claw/verifier_runtime.py)（staging/快照/隔离执行）、
[`verifier_precheck.py`](../../ale_run/agents/ale_claw/verifier_precheck.py)（writer 的
`verify` 工具）、[`verifier_sandbox.py`](../../ale_run/agents/ale_claw/verifier_sandbox.py)
（Landlock/seccomp 进程边界）。本文只描述当前设计；版本演化在 [EVOLUTION.md](EVOLUTION.md)，
跨版本 insight 在 [FABLE.md](FABLE.md)。

最近实测是 2026-07-21 夜的两轮 26 题实验（[results/full26_two_rounds](results/full26_two_rounds/)）：
v18 配对均差 `+0.0209`（t `+2.57`，n 26），v19 `+0.0005`（t `+0.05`，n 25）。两轮之间没有
能解释这个差距的协议改动，所以 `+0.0209` 更可能是运行方差，收益未被证明。

> 先证明题目要求什么，再测量 output 是否符合，把结果交给 Writer。Writer 回到 `/input`
> 判断反馈，不直接服从 Verifier 的解释。

## 任务需求分析

分数由任务原 evaluator 在 solve 结束后用隐藏 reference 产生，writer 在提交前没有任何独立
测量，只能靠同上下文自检。需要一个测量者：不看隐藏材料、不改产物、结论可复现、锚定公开
来源。历史数据划出两条硬约束：

1. **反馈必须在 writer 还有预算时到达。** 反馈只在 DONE 后推送的协议下，52 个 run 产生
   0 次修复，180 条 pass 确认全部作废。
2. **测量必须真的发生。** 冻结的 344 条 check 里 156 条死在来源审查门上没有运行
   （ambiguous 145 条），信号损耗的最大单项不是测量质量，是测量被自己的门拦住。

## 实现原则

- **唯一合法新增信息是对冻结 output 的可复现测量，每条锚定公开来源。** Verifier 不掌握
  隐藏评分，不宣布 output 最终对错；结构 pass 不等于任务正确，报告始终声明未覆盖面。
- **零权威。** 每条结果都是参考测量，不是判决：冻结时 `blocking` 恒为 false，builder 的
  硬性主张只作为 `requested_blocking` 留档。硬权威曾要求证明来源蕴含、checker 对齐、来源
  无冲突，为此设了 Auditor 和五项 gate；v16 六题实测这条链每环都在断（6/6 构建 error、
  12 测试只跑 2），而零权威的 self_check 调用率 5/5。v18 放弃硬权威，链条只保留 advisory
  测量仍然需要的环节。总判定同步取消：`overall` 只描述覆盖（measured / error /
  unverifiable），不给可刷的全绿目标。
- **契约优先。** builder 生成检查时锚定任务的交付物契约：题面点名的文件路径、字段拼写、
  必须保留的标识符、数量、单位、顺序、编码、跨文件一致性，全部按题面原文逐字进入
  checker（paraphrase 测的是 paraphrase，不是契约）；check id 以契约义务命名
  （`contract.<file>.<obligation>`），报告读起来是契约覆盖图。宁可用简单的存在性/拼写/
  计数检查覆盖更多契约条目，不为一条义务做深验证而让其余失measure。
- **标准先于产物。** 测试在 writer 开始前生成并冻结（内容、hash、来源全部固定）；
  output 产生后只更新运行结果。冻结不要求"只在结束后运行"，执行时机对 writer 开放。
- **机械门决定跑不跑，不决定信不信。** 来源已定位、checker 过 fixture 预检、环境健康的
  检查一律执行；来源定位失败的不运行（coverage gap），预检失败的记 execution error。
  没有任何语义审查环节。
- **quote 是事实，locator 只是坐标。** quote 在文件中唯一时，错误行号由 harness 机械修正；
  仍失败的来源给 builder 一轮机械修复（证据只有"quote 未找到"一类，失败数严格减少才采用）。
- **报告测量，不做诊断。** Checker 只输出 `{status, observed, evidence}`；第一处分歧和根因
  由 Writer 沿自己的代码与数据流追。反馈 source-first，不含 repair hint。
- **Writer 是唯一决定 output 的 agent。** 每条硬失败可用 `VERIFIER_DISPUTE <check>` 附公开
  反证驳回；不诱导照抄任何给定值（防 reference 复制）；真实 revision 计数加 output 无变化
  即停，防振荡。
- **fail-open 到条目级，不到整包级。** 顶层字段缺失填默认值并记入 `dropped`，只有"没有
  任何可用测试或要求"才整包失败；单条测试的 schema 违规、超限、重复 id 只丢那一条，其余
  测试照常定位、冻结。这与 prep 的逐条丢弃是同一条原则：一条坏测试不该没收 writer 的整个
  `verify` 工具。v17 声称的逐条隔离只落到条目层，信封层还是硬拒，v18 六题里 SEC 整包失败
  就是这么来的，v19 把兜底补到信封层。整包失败时 `verify` 工具向 writer 报告失败原因，
  这是最低限度的反馈；构建失败同时记录 builder 响应的前 400 字符，用来区分 builder 真的
  产出坏 JSON 和提取器选错了对象。
- **fail-open。** 构建失败不运行测试；隔离启动失败归 error 不降级；一切 Verifier 故障都不
  影响 writer 提交。

## 具体实现

### 判准来源

只能从公开来源建立判准：task prompt、`/input`、题目指定的 `software/` 与公开数据、题面明确
要求的外部标准（版本和适用范围须题面直接指定并冻结为本地可哈希证据）。官方 evaluator、隐藏
reference、Prep、历史分数不可用。题目没规定的阈值、容差、顺序、精度不补充；样例值不推广；
文本、样例、schema 冲突的要求标 `unverifiable`。枚举标签（Yes/No/Unknown 等）必须有公开的
命题到标签映射，缺数值不能自行决定写 `No` 还是 `Unknown`。

每个测试记录完整来源集：`{path, locator, quote}` 每项加 SHA-256。JSON 用 JSON Pointer，
文本与 task prompt 用 `lines:N-M`（至多 50 行），参与重算的二进制用 `file` 冻结整文件 hash。

### 生成与冻结

构建分两个阶段，边界是 prep 的完成时刻：

```text
阶段 A（与 prep 并发；只读公开任务表面）
  Builder（fresh context，看不到 Writer/Prep）
    -> 候选套件：至多 6 个测试 + 8 条 unverifiable，每测试一个确定性 Python checker
       + 合法/错误 fixtures + 来源集 + blocking 请求
    -> lint（schema、大小、路径、fixture 差异；单条违规丢该条记 dropped，
       顶层损坏才整包失败）
    -> 机械定位每个来源（单次批处理）：quote 唯一时自动修正行号；hash 固定
    -> 定位失败 -> 一轮机械修复（新 builder 会话只见失败清单；重 lint 重定位；
       定位失败数严格减少且 lint 丢弃数不增加才采用）

阶段 B（prep 完成后、prep 报告 staging 之前；纯机械，零 LLM）
  -> stage 候选 + fixture 预检（合法过/错误挂、连续两次一致、环境探针）
  -> finalize：blocking 恒 false + 整包 SHA-256 冻结
```

Auditor 已在 v18 删除：它的三项判定（蕴含、对齐、来源状态）全部只为硬权威发放许可，
零权威下没有许可可发。留下的是 advisory 测量仍然需要的部分——脚本能启动、能区分自己的
正反 fixture、环境健康——因为一个高频误导 writer 的坏 checker 与权威无关。构建成本因此
少一个 LLM agent。

阶段 B 后移的原因是环境一致性：`environment_healthy` 和 `checker_reproducible` 是环境
判定，执行却发生在 writer 之后的沙箱里，而 prep 会在构建期间装包、改缓存、起服务。预检
若与 prep 并发（v16 及以前），依赖 prep 稍后装好的运行时的 checker 会被冻结成"不可复现"
而永久降级。移到 prep 之后，gate 在 writer 将要接手的同一环境里测量，checker 也因此可以
复用 prep 跑通的运行时。独立性不受影响：标准的内容（测试、expected、来源）全部在阶段 A
由 builder 并发生成，不读 prep；Auditor 只读公开材料、候选套件和预检回执，且在 prep 的
语义产物 staging 进 task root 之前完成，读不到它们。冻结仍然严格先于 writer 启动。

适用范围要说清楚：这个时序只可能在 prep_verifier 合并臂产生差异。verifier 单臂没有 prep
可等，prep 单臂没有 verifier，两个单臂的行为与 v16 逐字节相同。而且收益只覆盖"prep 能装
好的运行时"——v16 六题里 BPMN 的 checker 依赖 Flowable/Docker，prep 自己判定 Docker 嵌套
不可用，这类任务两阶段也救不回来。所以它是为合并臂预留的机制，收益是否真实、值不值得
固化这个时序复杂度，以合并臂 canary 的 `execution_errors` 读数为准。

冻结后每条检查的处置只由机械事实决定：

| 情形 | 处置 |
|---|---|
| 任一来源定位失败 | `coverage_gaps`，不运行 |
| checker 未过 fixture 预检或环境不健康 | `execution_errors` |
| 其余 | 运行，差异进 `review_items`（simulation 附来源说明） |

执行方式优先级：题目真实软件 > 公开重算 > simulation（报告中注明）。

### 执行与四类输出

Writer 的 `output/` 复制为只读快照（拒 symlink、去写权限、tree hash 双验）。每个测试在
Landlock/seccomp 隔离进程运行两次，结果不同归 error；只读公开 input/software/快照/checks，
只写独立 scratch，无网络；每次执行前复验 suite hash、script hash、公开来源 hash。

报告不给 output 贴 pass/fail，按维度归类，`needs_review = 存在 review_items`
（`hard_mismatches` 类别结构上保留，零权威下恒为空）：

| 类别 | 定义 | 对 Writer 的含义 |
|---|---|---|
| `review_items` | completed + differed | 参考测量不是判决，回 `/input` 自行决定 |
| `execution_errors` | execution=error | Verifier 自身没跑成，只作背景 |
| `coverage_gaps` | 来源未定位或无公开 solve 时 oracle | 声明不可公开验证的面，只作背景 |

`overall` 只描述覆盖：`measured`（至少一条检查真的执行了）、`error`（有检查但都没跑成）、
`unverifiable`（冻结时就没有可执行项）。没有可优化的全绿总判定。

### 与 Writer 的两条通道

**拉取（主通道）**：`verifier_writer_checks > 0`（默认 2，0 至 8）时 writer 有 `verify`
工具，DONE 前对当前草稿快照跑完整冻结包，返回同一份四类报告（pre-submission 措辞，声明
all-pass 不是完成信号）。冻结包首次调用才 stage 进 VM；快照命名空间 `snapshot-writer<n>`
独立；调用崩溃不计次，跑完为 error 计次；预运行不消耗复核轮数。初始 prompt 在套件冻结成功
时告知工具与次数。

**推送（兜底）**：DONE 后快照、跑完整冻结包，`needs_review` 为真且有未 dispute 项时反馈给
Writer（source-first：来源、hash、interpretation，然后命令、observed、expected、evidence），
Writer 修改后重跑完整冻结包。上限 `verifier_max_review_rounds`（默认 1）；output 无变化
即停；全部可复核项被 dispute 即停。

主运行文本里的 dispute 与复核轮同协议解析。理论上 writer 可以在 DONE 消息里逐条 dispute
关闭复核轮（它从 `verify` 报告知道全部 check 名），但历史全部 run 的实测 dispute 次数为
0；为一个从未发生的滥用加"writer 见过哪些 check"的门控状态机，是拿真实复杂度换假想安全。
这个方案评审后被否决，出现真实滥用样本再议。

每轮完整报告写 host `verifier_round_<n>.json` / `verifier_writer_check_<n>.json` 与 VM
`verifier/` 下同名文件；`verifier_meta.json` 汇总轮数、真实 revision 数、writer check 用量、
disputes、stop reason。

### 与 Prep 的边界

Builder 与 Prep 从同一公开任务表面并发启动，互不读取（防共同污染）。同一个 parser 或任务
软件可以服务两者，但必须是本轮前已存在、hash 固定的公共工具；Verifier 不读本轮 Prep 的
动态 artifact。prep_verifier 臂里 harness 机械对账两份合同阅读引用的公开文件（见
[ARCHITECTURE.md](ARCHITECTURE.md)），对账只流向 writer，不改变任何测试权限。

边界在语义不在环境：prep 留下的运行时状态（装好的包、跑通的服务）是 writer 与 executor
共同的执行环境，预检和执行都应当在其中发生（见"生成与冻结"的两阶段）；prep 的语义产物
（报告、清单、artifact）才是不可读取的对象，阶段 B 是纯机械步骤，在它们 staging 之前完成，
不读任何文本。

## 流程结构

```text
                    ┌─ Prep ──────────────┐──> 沙箱状态 / 报告文件 / self_check ──> Writer ─┐
公开题面+input+software┤                    │（机械合同对账 ⇢ Writer）                       │ output/
                    └─ Builder ─> 定位/修复 ┴─> fixture 预检 ─> frozen suite（全 advisory）──┤
                       （阶段 A，与 prep 并发）（阶段 B，prep 后，零 LLM）│                   │
                                     （solve 中）Writer ────────────────┴─ verify ─> 快照+执行 ─> 分类报告
                                     （DONE 后）快照 ─> 完整冻结包 ─> needs_review ─> 复核/修复 ─> 重跑
```

## 实测结果与下一步

两轮 26 题实测（[results/full26_two_rounds](results/full26_two_rounds/)）：

**机制全部达标。** 冻结成功率 v18 是 26/26 `build=ready`、v19 是 25/26，对照 v16 六题的
0/6，lint 逐条隔离加信封兜底解决了整包失败。所有冻结成功的题都调用了 `verify`，没有出现
冻结成功但工具零调用的情况。零权威没有诱发 delete-to-pass。

**分数收益没有被证明。** v18 的 `+0.0209`（t `+2.57`）是历史最好读数，v19 用几乎相同的
协议重跑得到 `+0.0005`（t `+0.05`）。v18 到 v19 只加了信封兜底和构建失败记录，都是
fail-open 方向，解释不了这个差距，所以更合理的解释是运行方差。单题层面
digital_audience 从 `+0.0925` 翻到 `-0.1247`，PE 从 `+0.0413` 翻到 `-0.0524`，跨轮方差
比配对均差大一个量级。两轮都算分的 25 题里有 14 题两轮 delta 都是 0，有效样本只有名义
样本的一半。

跨两轮稳定的正例只有 agora（`+0.1597` 和 `+0.1550`）和 variant（两轮都是 0.9304 到
0.9990 的同一跳变）。

**收益来源仍未分离。** 无法区分"测量内容有价值"和"writer 知道有独立测试包会检查它，
因此自己复查了 output"。config 里的 `writer_self_review_hint` 是为这个问题准备的对照臂：
不跑任何测试，只给一句提交前对照题面契约自查 output 的提示。如果它拿到接近的效果，
builder 那部分 token 买的就是一个预期，压缩空间很大。

下一步先剔除多轮 delta 恒为 0 的题再跑，剔除清单在看结果之前定好；协议本身冻结，不要在
归因实验期间再引入变量。

验证状态：2026-07-22 在 pgl 测试副本（`~/ale/v21-test`）三套件 71 passed 1 skipped（lint
逐条隔离、两阶段构建、批量定位、分块 staging、sandbox hash 复验各有用例过线），改动文件
ruff clean，相邻套件的失败与主仓库基线是同一组既有 WIP 失败，零新增。
