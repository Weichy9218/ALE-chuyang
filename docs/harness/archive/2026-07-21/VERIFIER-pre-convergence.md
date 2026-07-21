# Verifier

本文定义 Verifier 的职责和实现约束。当前代码协议为 `public-verifier-v16`，实现见
[`verifier.py`](../../ale_run/agents/ale_claw/verifier.py)、
[`verifier_runtime.py`](../../ale_run/agents/ale_claw/verifier_runtime.py) 和
[`verifier_precheck.py`](../../ale_run/agents/ale_claw/verifier_precheck.py)。v15 相对 v14
增加一条通道：Writer 可以在 DONE 之前用 `verify` 工具对当前草稿运行同一冻结测试包，见
下文"预提交自检"。v16 修信号产生率：quote 唯一时行号错误机械自动修正、定位失败给 builder
一轮机械修复、来源歧义的检查以 advisory 身份运行，见下文"v16：信号产生率"。两轮记录见
[FABLE.md](FABLE.md)。

Verifier 的核心规则是：

> 先证明题目要求什么，再证明 output 是否符合，最后把测量结果交给 Writer。Writer 必须回到
> `/input` 判断反馈，不直接服从 Verifier 的解释。

Verifier 在 Writer 提交前提供一份独立、可复现的评测报告。评测标准在看到 output 前生成并
冻结；output 产生后只更新运行结果，不更新标准。Verifier 不读取官方 evaluator、隐藏
reference、Prep、历史评分或 Writer 轨迹，不修改 output，也不替 Writer 决定修复方案。

## 从第一性原理推出的设计

Verifier 唯一能合法新增的信息，是对冻结 output 的可复现测量，且每条测量都锚定在公开来源。
它不掌握隐藏评分，不能宣布 output 最终对错，只能报告「在公开来源下，测出了什么」。这条边界
决定了下面三点。

**第一，反馈必须无损地到达 Writer。** Writer 是唯一决定 output 的 agent。一条测量再准确，若
进不了 Writer 的下一轮，就等于没测。这是 v13 的核心 bug：它用一个字段 `status` 同时决定测量
结果、结果的权威性、以及要不要再叫 Writer，导致只有硬阻断失败能进入 Writer，其余测量全烂在
内部日志。

**第二，测量、权威性、是否复核是三件不同的事，必须分开判断：**

```text
execution:    completed / error       测试有没有在真实环境里跑完
observation:  matched / differed      跑完后 output 与 expected 是否一致
authority:    hard / advisory         这个判准是不是题面明示的硬要求
```

`execution` 只回答测试本身能不能运行，跟 output 对错无关：Checker 崩溃、依赖缺失、隔离环境
起不来都是 `error`。`observation` 只在 `completed` 时有意义。`authority` 由冻结前的来源审查和
gate 决定，跟当轮 output 无关。三者独立，才能把「测出了差异」和「这条差异有没有资格挡提交」
分开。

**第三，Verifier 报告测量，Writer 做诊断。** 这与 ale_claw「让模型做主要工作」的最小化设计
一致。Checker 只输出 `{status, observed, evidence}` 三元组，不输出根因假设。第一处分歧、下游
影响由 Writer 自己沿代码和数据流追。v14 因此删掉了 v13 里可选的 `analysis` 字段和它的置信度
枚举：那是 Checker 生成的猜测，Writer 本就被要求重新推导，留着只增加 schema 面积。

## 四类顶层输出

顶层报告不给 output 贴 `pass/fail`，而是按上述维度把每个 check 归入四类，每类处置不同：

| 类别 | 定义 | 对 Writer 的含义 |
|---|---|---|
| `hard_mismatches` | authority=hard，execution=completed，observation=differed | 必须回到 `/input` 复核，然后修复或提出反证 |
| `review_items` | authority=advisory，execution=completed，observation=differed | 是先验不是判决，Writer 自行决定改不改 |
| `execution_errors` | execution=error | Verifier 自身没跑成，不是 output 的证据，只作背景 |
| `coverage_gaps` | 来源不足或题目没有公开 oracle | 说明哪些要求无法公开验证，只作背景 |

是否再叫一次 Writer，由 `needs_review` 决定，它等于「存在 `hard_mismatches` 或
`review_items`」。也就是说，只有真正跑出来的差异才触发复核。`execution_errors` 和
`coverage_gaps` 随报告一起给 Writer 看，但单独出现时不构成复核理由，避免在环境损坏或没有
oracle 的题上空转。

这条派生规则修掉了 v13 的主漏失。BPMN 四个针对拓扑、数据流、timer、cost 的 Checker 能发现
真实问题，却因为覆盖不完整被整体判成 `error`，Writer 一次都没看到。v14 里这类 Checker 只要
来源成立、能复现，就以 advisory 身份运行，差异进入 `review_items`。

## 与 Prep 的边界

Prep 和 Verifier 都可能运行脚本、解析输入、实现 metric 或启动任务软件。职责不按工具类型
区分，按检查对象和结论用途区分。

| 角色 | 发生时间 | 核心问题 | 检查对象 | 交付 |
|---|---|---|---|---|
| Prep | Writer 开始前 | 哪个非显然事实、运行障碍或能力会改变求解方法？ | 公开 input、方法和 runtime | observation、resolver、metric、runtime receipt |
| Verifier Builder | Writer 开始前 | 公开要求可以怎样被独立验证？ | 题面、`/input`、`software/` | 已定位依据、冻结测试和通过条件 |
| Verifier Executor | output snapshot 后 | 冻结 output 在真实环境中的结果是什么？ | 只读 output snapshot | 完整命令、运行过程、observed、expected、四类归属 |

归属规则如下：

1. 帮助 Writer 理解 input、选择方法或获得缺失能力的工具属于 Prep。它不给最终 output 出具
   任何硬判准。
2. 对冻结 output 执行并产生提交前测量的检查属于 Verifier。它不替 Writer 做预研。
3. 同一个 parser、metric 或任务软件可以服务两者，但必须是本轮运行前已经存在、来源明确、
   hash 固定的公共工具。
4. Verifier 不读取本轮 Prep 动态生成的 artifact。否则 Prep 对题意或实现的错误会同时污染
   求解和验收，独立校验失去意义。
5. 某个 Prep artifact 若确有通用价值，应在后续版本经单独审查后下沉为公共工具，不能在同一
   任务中直接变成 Verifier 的判准。

两条分支在 output 产生后汇合，Verifier 的报告再回到 Writer。Writer 的初始 prompt 只接收
Prep，不含冻结测试内容；v15 起 Writer 可以在草稿完成后主动调用 `verify` 工具获得对草稿的
测量（这会向 Writer 展示被测项的来源、命令和 expected，与 DONE 后复核轮展示的信息相同，
只是更早）：

```text
                         ┌─ Prep ─> blocker / capability ─> Writer ─> output ─> snapshot ─┐
公开题面、/input、software ┤                                                               ├─> Verifier Executor
                         └─ Verifier Builder ─────────────────> frozen suite ────────────┘          │
                                                                                                   v
                                      Writer <────────────────────────────── complete report
                                        │
                                        └─ 复核 /input，必要时使用 Prep capability 定位问题
                                                        │
                                                        └─ 修改 output ─> 重跑同一 frozen suite
```

Prep 在求解前降低方法和工具的不确定性；Verifier 在求解后提供 Writer 当时没有的独立运行结果。
两者都服从公开题目，不共享本轮生成的判断。

## 题目依据

Verifier 只能从以下公开来源建立判准：

1. task prompt；
2. `/input`；
3. 题目指定的 `software/`、测试命令、格式规范或公开数据；
4. 题目明确要求使用的外部标准。外部标准的版本和适用范围必须由题面直接指定，并在冻结时
   保存为本地可定位、可哈希的公开证据。

官方 evaluator、隐藏 reference、Prep、历史分数、其他任务答案和一般领域惯例不能成为判准。
题目没有规定阈值、容差、顺序、精度、范围或字段关系时，Verifier 不补充。样例值不自动推广为
普遍规则。文本、样例和 schema 冲突时，相关要求标为 `unverifiable`，不任选一边阻止提交。

每个测试必须先建立规范证明。一个 expected 依赖多个规则或公开数据文件时，必须记录完整来源集：

```text
每个 source 的 path
每个 source 的 locator
quote、结构化值或 whole-file 标记
每个 source 的 SHA-256
requirement
Verifier interpretation
expected
```

Harness 机械确认每个 source 位于允许目录，locator 指向 quote 或结构化值，并保存 source hash。
JSON 使用 JSON Pointer；UTF-8 文本和 task prompt 使用 `lines:N-M`；参与公开重算的二进制或
不透明数据使用 `file`，冻结整个文件的 hash。语义审查再判断完整来源集是否直接推出 requirement
和 expected，以及附近规则或其他公开文件是否冲突。遗漏任一规则或数据来源时不能授予硬权限。
当 expected 选择 `Yes`、`No`、`Unknown` 或其他枚举标签时，来源集还必须定义题目命题与标签的
映射。资料缺少某个数值，不足以自行决定应写 `No` 还是 `Unknown`。

## 硬权限与 advisory

Builder 生成的是候选测试，不直接拥有硬权限。一个测试只有同时满足以下条件，其 `differed` 才
进入 `hard_mismatches`，成为 Writer 必须处理的公开要求：

```text
authority = hard 当且仅当
  all_sources_located
  AND source_status == supported
  AND source_entails_expected
  AND checker_matches_requirement
  AND checker_reproducible
  AND environment_healthy
  AND execution_mode != simulation
```

未满足时，测试的处置分三种，关键区别是 expected 有没有公开锚点、Checker 能不能复现：

| 情形 | 处置 | 说明 |
|---|---|---|
| source 定位失败（missing）或被公开材料反驳（contradicted） | `coverage_gaps` | expected 没有可用锚点，不运行 |
| checker 不可复现，或隔离环境起不来 | `execution_errors` | Verifier 没跑成，不是 output 的证据 |
| 其余情形：来源已定位、checker 可复现 | 以 advisory 运行 | 差异进入 `review_items`，附审计评语 |

第三行经历了两次放宽。v14 允许部分覆盖的 checker（`checker_matches_requirement` 为假）和
simulation 以 advisory 运行。v16 把来源侧同样放开：Auditor 判 `ambiguous` 或
`source_entails_expected` 为假的测试，此前直接落入 `coverage_gaps` 不运行——v10 全量数据里
这一类占全部 344 条 check 的 42%（ambiguous 145 条），是信号损耗的最大单项——现在照常在
真实 snapshot 上执行，差异作为 advisory 交给 Writer，反馈里附上来源审计评语（"两条相邻规
则给出不同顺序"这类），让 Writer 知道 expected 是 Verifier 的读法而不是公开事实。执行的
安全代价为零（同一隔离沙箱），成本只有 Writer 的注意力，由 advisory 框架和 dispute 机制
管理。硬权限的授予条件一个字都没变。

`hard_mismatches` 为空不代表 output 整体正确：大量语义要求仍可能落在 `review_items` 和
`coverage_gaps` 里。历史上多个低分 artifact 通过了 verifier 的结构硬检查（`verifier_compare`
的 MARC、CRF4、SAP），正是因为硬检查只覆盖公开可测部分，不覆盖完整任务。

## 测试生成与冻结

Verifier Builder 在 Writer 开始前完成以下工作：

1. 从公开来源列出可执行要求和无法公开验证的要求。
2. 为每个可执行要求生成一个确定性 Python Checker，输出 `{status, observed, evidence}`。
3. 固定 sources、expected、command、script 和所有采样位置。
4. 验证 Checker 的合法 fixture 能通过、单一错误 fixture 能失败。每个 fixture 是
   `{path, encoding, content}` 文件数组；文本直接使用 UTF-8，只有二进制内容使用 base64。
5. 在 pgl 目标环境检查软件、依赖、权限和命令是否可运行。
6. 完成 source 和 Checker 审查后计算整个测试包的 SHA-256。

## v16：信号产生率

三处修正，全部只依赖机械证据，不改变任何权威判定：

1. **quote 自动重定位。** quote 是事实本体，`lines:N-M` 只是坐标，而数行号恰好是模型最易
   错的操作。定位脚本现在在引用行窗未命中、且 quote 在全文中恰好出现一次时，机械反查出
   正确行号并修正 locator（跨度仍受 50 行上限约束），`locate_evidence` 记录修正前后坐标。
   行号越界不再当场判死，同样进入重定位。quote 出现多次或根本不在文件里才算定位失败。
   JSON Pointer 来源不做重定位。
2. **一轮机械修复。** 定位仍失败的 source（quote 写错、路径写错）把纯机械证据（"quote 未
   在该文件找到"）发回一个新的 builder 会话修一次：只许修 quote/路径或把该要求降为
   unverifiable，其余字段原样保留。修复产物重新 lint、重新定位，只有失败数严格减少才被
   采用。证据里没有 Writer、Prep 或任何隐藏信息，独立性不受影响。
3. **ambiguous 来源以 advisory 运行**（见上节"硬权限与 advisory"的第三行）。

预期效果的量化目标写在 [FABLE.md](FABLE.md)：v10 数据下 156 条未运行 check 中 145 条
ambiguous 将改为运行，定位类失败中行号错误一类应降为 0。真实比例要用六题机制 canary 复测。

一个要求宁可把 check 声明的覆盖范围缩小到 Checker 真能证明的部分，也不要用覆盖不全的
Checker 去声称完整要求。声称完整却只覆盖一部分，会被 Auditor 判为部分覆盖，降为 advisory。

冻结包不能读取 Writer output。Writer 修改后仍运行完整冻结包，不能只运行之前失败的检查。

## 真实环境优先

Verifier 按以下顺序选择执行方式：

1. 题目已经提供 validator、test suite、CLI、服务或软件时，在 pgl 启动并运行真实命令。
2. 题目要求可由公开 input 重算时，使用确定性 parser、公式或一致性检查。
3. 真实软件无法启动时，记录 `execution_errors`。只有题面明确规定替代模型与真实行为等价时，
   替代实现才能获得硬权限。

Fixture 只证明 Checker 的基本方向和确定性，不替代对真实 output 和真实软件的执行。Mock、
stub 或简化模拟默认只作为 Checker 单元测试或 advisory 证据，不因为更容易运行就替代题目指定
的软件。已有公开判准但环境启动失败时归入 `execution_errors`；题目本身没有公开 oracle 时归入
`coverage_gaps`。

## 隔离执行

Writer 完成后，Harness 复制 `output/`，拒绝 symlink，移除写权限并计算 snapshot hash。每个
测试在独立进程中运行：

- 公开 `/input`、题目 `software/`、frozen checks 和 output snapshot 只读；
- 只有独立 scratch 可写；
- Writer 原 output、Prep、hidden reference 和官方 evaluator 不可访问；
- 网络默认禁用；
- 环境变量固定；
- 每项测试连续运行两次并比较规范化结果，不一致则归入 `execution_errors`。

当前 pgl 使用 Landlock 限制文件访问，使用 libseccomp 禁止网络 syscall。隔离启动失败时归入
`execution_errors`，不降级到普通进程，也不说 output 有错。隔离层允许 `socketpair` 等本地进程
通信，但拒绝创建网络 socket。pgl 已实测 `uv run` 能在该限制下启动。依赖 Docker daemon、外部
服务或网络且无法在隔离区内安全启动的软件仍归入 `execution_errors`，不用 mock 结果获得硬权限。

隔离是 v10 的直接教训：American 和 Moodle 的 runner 曾通过任务 runtime wrapper 改动原 output，
双 hash 把那几次运行记为异常。snapshot 只读加双 hash 保证验收不污染求解。

## 完整评测报告

Verifier 的产物是完整评测过程和结果。每个 check 至少包含：

```json
{
  "check": "schema.required_columns",
  "sources": [
    {
      "path": "input/schema.json",
      "locator": "/required_columns",
      "quote": "[\"id\", \"score\", \"status\"]",
      "sha256": "..."
    }
  ],
  "requirement": "final submission contains every required column",
  "command": ["python3", "required_columns.py"],
  "execution_mode": "public_recompute",
  "execution_reason": "the public CSV schema is directly parseable",
  "requested_blocking": true,
  "blocking": true,
  "status": "fail",
  "observed": "missing column: status",
  "expected": "id, score, status",
  "execution": {
    "command": ["python3", "required_columns.py"],
    "runs": [
      {"returncode": 0, "stdout": "...", "stderr": "", "duration_s": 0.12},
      {"returncode": 0, "stdout": "...", "stderr": "", "duration_s": 0.11}
    ],
    "consecutive_runs": 2,
    "reproducible": true
  },
  "evidence": ["output/submission.csv#header"]
}
```

单个 check 的 `status` 是 `pass`、`fail`、`unverifiable` 或 `error`，`blocking` 标记它有没有
硬权限。顶层的 `hard_mismatches`、`review_items`、`execution_errors`、`coverage_gaps` 和
`needs_review` 由 check 列表机械派生，不额外引入判准。报告还包含 suite hash、snapshot hash、
环境健康结果、全部 check、coverage 和未覆盖要求。不能只把失败摘要交给 Writer，同时把完整
过程留在内部日志。Writer 可以先看摘要，但必须能读取同一轮的完整报告并复现命令。

## Writer 反馈与重跑

报告回到 Writer 时，四类输出的呈现和处置不同：

- `hard_mismatches`：source-first 展开每处失败，先列来源和 hash，再列 observed、expected、
  evidence。Writer 必须回到 `/input` 复核；测试成立就修复，不成立就写
  `VERIFIER_DISPUTE <check>` 附公开反证。
- `review_items`：同样展开来源和观察，并附 Checker 的部分覆盖评语。Writer 把它当先验，自行
  决定改不改，也可以用 `VERIFIER_DISPUTE <check>` 消掉一条重复的 advisory。
- `execution_errors` 和 `coverage_gaps`：以紧凑列表附在后面，说明哪些检查没跑成、哪些要求
  无法公开验证，供 Writer 参考，不要求动作。

控制流按下面的规则循环，`max_review_rounds` 是上限：

1. 对当前 output 做只读 snapshot，跑完整冻结包，得到四类输出。
2. `needs_review` 为假（既无 hard 也无 advisory 差异）时停止，直接提交。
3. 全部可复核项都已被 Writer dispute 时停止，标记 `writer_disputed`。
4. 达到 `max_review_rounds` 时停止。
5. 否则把报告交给 Writer，Writer 复核后可改可不改。

一轮复核只有在 output 真的变化时才算一次 revision。Writer 复核后没有改动 output 时，下一轮
snapshot 的 source hash 与上一轮相同，循环立即停止，标记 `writer_no_change`，不浪费一次
重跑。`verifier_meta.json` 里 `rounds` 记复核轮数，`repairs` 只记真实 revision 数。

反馈按 sources、execution result、output conflict 排序。Verifier 不先给解决方案，也不要求
Writer 输出复杂的 accept/challenge JSON。

## 预提交自检（writer 触发）

v14 修好了"测量无损到达 Writer"，但所有测量仍然只在 DONE 之后到达：v10 全量 52 个
verifier run 的 repair 数是 0，344 条 check 里 180 条 pass 的确认信息在 DONE 后毫无用处，
step 预算用尽的 writer 即使收到硬失败也没有步数可修（`writer_step_limit`）。冻结的意义在于
"标准不随 output 变"，它并不要求"只在结束后运行"。v15 因此把执行时机提前，标准本身不变。

机制：`verifier_writer_checks > 0` 且 Verifier 开启时，Writer 的工具表多一个 `verify`
（[`verifier_precheck.py`](../../ale_run/agents/ale_claw/verifier_precheck.py)）。调用一次即
对当前 `output/` 做只读快照并运行完整冻结测试包，隔离执行、双次运行、四类归属与 DONE 后
完全一致；反馈使用 pre-submission 措辞，明确"all-pass 只覆盖公开可测部分，不是完成信号"。
初始 prompt 在套件冻结成功时告知 Writer 这个工具的存在和剩余次数。

不变量逐条核对：

- 标准冻结不变。suite hash、script hash、来源 hash 在每次执行前照常复验
  （`execute_test_suite` 的既有逻辑），预运行无法改变任何判准。
- 隔离不变。同一 Landlock/seccomp 沙箱、同一只读快照协议，快照命名空间
  `snapshot-writer<n>` 与 DONE 后的 `snapshot-<i>` 分开。
- 权威不变。工具返回的是同一份四类报告；hard/advisory 的授予逻辑在冻结时已定。
- 测试内容暴露是有意的协议变化。DONE 后复核轮本就向 Writer 展示来源、命令与 expected 并
  要求它复现冻结测试；v15 只是允许这件事更早发生。Goodhart 面仍限于公开可测部分，报告的
  `coverage_gaps` 继续声明未覆盖面。
- fail-open 不变。套件未冻结成功时工具报告不可用；单次运行失败返回错误文本，不影响求解。

预算与记录：默认 2 次，配置范围 0 至 8（`verifier_writer_checks`，presets 显式写出）。每次
运行的完整报告写入 host `verifier_writer_check_<n>.json` 和 VM `verifier/writer_check_<n>.json`，
`verifier_meta.json` 记录 `writer_checks_max`、`writer_checks_used` 和每次的 overall；
analyzer 的 behavior 表新增对应列。Writer 在主运行文本里写下的 `VERIFIER_DISPUTE <check>`
与复核轮同协议解析，进入同一个 dispute 集合。

DONE 后的复核循环完全保留：预运行不消耗 `max_review_rounds`，最终提交仍照常快照、重跑和
复核。预期的行为变化是 hard mismatch 在预算内被 Writer 自己修掉，DONE 后一轮趋于 0 差异。

## 必须避开的历史坑

以下每条都对应 [EVOLUTION.md](EVOLUTION.md) 记录的一次真实失败，v14 的设计据此约束：

- **不诱导复制 reference。** CT 的 repair 曾把 reference 整图复制进 output，或混入部分
  reference 绕过 anti-copy evaluator。Verifier 不读隐藏 reference，反馈只指向公开来源，且
  Writer 被要求自己回到 `/input` 判断，不照抄任何给定值。
- **语义先验不当硬门。** TCGA 的 15/16 字符冲突、SSE 的 `No/Unknown` 标签，都是缺乏公开
  映射的语义判断。这类要求在 v14 里落入 `review_items` 或 `coverage_gaps`，作为 advisory 交给
  Writer，不作为与「缺文件」同级的硬阻断。
- **不制造振荡。** v6 canary 开放多轮 repair 时出现来回改写和错误传播。v14 用真实 revision
  计数、output 无变化即停、`max_review_rounds` 上限约束循环。
- **结构 pass 不等于任务正确。** 硬检查只覆盖公开可测部分。`hard_mismatches` 为空只表示没有
  触发硬要求，报告同时保留 `review_items` 和 `coverage_gaps` 说明未覆盖面。
- **验收不污染求解。** snapshot 只读、双 hash、隔离执行，防止 verifier 运行改动原 output。

## 当前状态与待测

v14 相对 v13 的改动集中在三处，都在 [verifier.py](../../ale_run/agents/ale_claw/verifier.py)、
[verifier_runtime.py](../../ale_run/agents/ale_claw/verifier_runtime.py) 和
[deployer.py](../../ale_run/agents/ale_claw/deployer.py)：

1. `VerificationResult` 派生 `hard_mismatches`、`review_items`、`execution_errors`、
   `coverage_gaps` 和 `needs_review`；`build_feedback_prompt` 同时展开四类，advisory 明确标为
   先验。
2. Executor 的运行门去掉 `checker_matches_requirement`：来源成立且 Checker 可复现的部分覆盖
   检查以 advisory 运行，差异进入 `review_items`，不再被丢成 error。
3. Deployer 用 `needs_review` 驱动 Writer 复核，加入 output 无变化即停止和真实 revision 计数；
   `verifier_max_repairs` 改名 `verifier_max_review_rounds`。同时删除 Checker 的 `analysis`
   字段，Checker 只输出 `{status, observed, evidence}`。

继续排除通用测试 DSL、自动修改 output、官方 evaluator 自检得分、根据 output 增加检查和
Checker 生成的根因假设。

关于 v13 六题门的结论需要撤回。当时判定「六题门未通过、Verifier 无效、默认关闭」，并把 SSE
那次有效修复标为 false blocking。这个结论是坏的：v13 的反馈通道只放硬阻断失败进入 Writer，
实验结构上就无法暴露 Verifier 的价值，`verifier_v13_six` 因此是一个错误案例，不应作为
Verifier 无效的证据。SSE 的 repair 实际有效，问题只在权限标注，正是 v14 拆维度要解决的。

同时不能反向夸大。v14 只完成了机制修正，让所有安全可复现的测量进入 Writer 复核；v15 只完成了
时机修正，让同一测量在 Writer 还有预算时可得。两者是否提高 ALE 得分都尚未测量。历史上
verifier-only 臂的分差都来自 0 repair 下的 rollout 噪声，不能归因于 verifier；收益必须在 pgl
预定义任务上，以真实 revision 前后的官方分解重新验证，验证完成前不把设计变化解释为得分提升。
v15 首先要看的机制指标是：`verify` 调用率、调用后 output 是否变化、DONE 后一轮的
hard mismatch 是否比 v14 减少。当前 Verifier 仍默认关闭。

v15/v16 的实现验证（2026-07-21，pgl `~/ale/fable-check` 独立副本）：`test_verifier.py`
30 passed 1 skipped（重定位、修复轮、ambiguous advisory 执行、contradicted 不运行、来源
caveat 各有专门用例）、`test_verifier_precheck.py` 7 passed、`test_analyze_factorial.py`
9 passed，改动文件 Ruff passed；全量 pytest 1087 passed，失败集合与未改动的原仓库逐项一致。
v16 首先要看的机制指标追加两条：重定位命中数（`locate_evidence` 含 corrected 的来源数）、
修复轮触发率与采用率。
