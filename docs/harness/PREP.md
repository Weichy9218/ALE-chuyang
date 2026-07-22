# Task-Specific Prep

协议 `task-prep-v23`，默认开启。实现在
[`task_prep.py`](../../ale_run/agents/ale_claw/task_prep.py)，交接在
[`deployer.py`](../../ale_run/agents/ale_claw/deployer.py)。本文只描述当前设计；版本演化在
[EVOLUTION.md](EVOLUTION.md)，跨版本 insight 在 [FABLE.md](FABLE.md)。

最近实测是 2026-07-21 夜的两轮 26 题实验（[results/full26_two_rounds](results/full26_two_rounds/)）：
v21 配对均差 `-0.0070`（t `-0.77`，n 24），v22 `+0.0163`（t `+1.26`，n 23）。方向在两轮之间
翻转，两轮都不显著。v23 未进实验。

## 任务需求分析

Prep 解决 writer 的输入侧缺口。26 题的失分按体量分三类：

1. 合同覆盖不全。BPMN 的 evaluator 检查 67 条 producer-consumer 约束，CRF4 是 57 行 mapping
   的词表；writer 知道要做什么，缺的是在提交前确认自己覆盖了多少条的能力。
2. 运行环境阻断。Python 版本不兼容、缺包、缓存不可写这一类，writer 在解题中途才撞上。
3. 题面缺失的外部精确取值。26 题里只有一例（Variant 的官方 severity 排序）。

六题实测（[results/prep_v18_six](results/prep_v18_six/)）进一步把需求从"能不能产出"改写成
"产出如何被消费"：报告生成率 6/6，但三题交付的 artifact 在 writer 轨迹里零调用，且清单点名
的维度会把 writer 的努力从未点名的维度上抽走（Agora 单题 -0.34）。所以当前设计的中心问题
是消费方式：状态直接生效、程序优于散文、清单声明自己的边界。

## 实现原则

- **产出只有变成 writer 提交前执行的动作才有价值。** 运行时状态经共享沙箱零损耗转移；合同
  知识的最高保真载体是 writer 可反复运行的自检脚本，散文清单排第二。
- **self_check 只做结构覆盖，不做判定。** 脚本检查存在性、字段与拼写、行数与条数、编码、
  跨文件一致性这类结构义务；不硬编码期望取值，不给对错结论。判定候选产物是 Verifier 的
  角色（prep_verifier 臂），或 writer 自己回题面复查（prep 单臂）。这条分工使两个辅助
  agent 在合并臂里不在同一功能上重复：self_check 高频、零成本、零权威地查"缺不缺"，
  `verify` 限次、有权威地查"对不对"。
- **做真实工作，不写关于工作的报告。** 装好的包、改好的缓存路径、启动的服务直接留在沙箱，
  报告只记录已验证的确切命令。
- **只做机械校验。** 语义 gate 无法机械判定，做成硬门必然退化成格式检验并误杀高价值内容。
  校验逐条丢弃并记入 `dropped`，never 整包拒绝。
- **边界是"谁在什么时候运行"。** prep 运行期从不读写候选 `output/`（彼时不存在）；它交付的
  检查和工具应当引用 `output/` 交付物路径，由 writer 运行。裁决候选产物属于 Verifier。
- **清单是部分阅读，必须声明边界。** 任何只读公开题面的清单都看不到 evaluator 的全部维度；
  条目措辞为最低义务而非优化目标，报告明示"不要用清单未点名的质量换取点名项的更严达标"。
- **不选定最终取值。** 标签、数值、缺失值策略都留给 writer。权威顺序：task prompt >
  `input/`/`software/` > writer 复查 > prep 产出 > 通用知识；冲突时 prep 产出丢弃。
- **fail-open、不缓存。** prep 失败/超时/为空不阻塞 writer；prep 留下真实状态，缓存报告会
  谎称环境就绪。

## 具体实现

| 角色 | 时间 | 任务 | 产物 |
|---|---|---|---|
| Prep | writer 前，同一沙箱 | 跑通运行时、编译合同清单与自检、补精确事实 | 沙箱状态、清单、self_check、findings、artifacts |
| Writer | 全过程 | 综合 task、input 和 Prep | 最终 artifact 和自检 |
| Verifier | output 快照后 | 判断候选 output 是否违反公开 contract | observed/expected/source verdict |

Prep 返回一个 JSON 对象，每个部分都可以为空：

```json
{
  "environment": {
    "status": "ready | partial | not_needed | blocked",
    "summary": "题目需要什么，现在是什么状态",
    "commands": ["已验证的确切命令"],
    "blocked_reason": "跑不通的部分"
  },
  "contract": [
    {"requirement": "一条可机械检查的义务",
     "locator": "task_prompt 或 input/path#locator",
     "check": "writer 对草稿运行的确切检查",
     "note": "为什么容易漏，可选"}
  ],
  "findings": [
    {"title": "", "observation": "带取值的事实或能力",
     "writer_action": "writer 怎么用",
     "sources": ["URL 或 input/path#locator 或 runtime:probe"],
     "do_not_infer": "这不授权什么，可选"}
  ],
  "artifacts": [{"path": "scratch 下的相对路径", "purpose": ""}],
  "self_check": {"command": "writer 对草稿运行的确切命令",
                 "artifact": "实现它的已声明 artifact 路径",
                 "covers": "覆盖哪些合同条目、不能判断什么"}
}
```

机械校验：类型、长度、条数、artifact 路径安全性与后缀、大小、`self_check.artifact` 必须在
已声明 artifacts 中、artifact 内容拒收 NUL。上限：清单 24 条、findings 6 条、artifact 4 个
各 64 KB。声明的 artifact 读不到时，先看命令返回码再解析字节数，两种失败分别记
`artifact:missing` 和 `artifact:unreadable`；出现任一种就把 scratch 目录里实际存在的文件
列进 `dropped`，用来区分"prep 写错了路径"和"prep 根本没写"。报告只作为文件交付，上限 48,000 字符是防爆炸的安全上限而非注意力预算；超限时
截断发生在文件尾部，且文件头部写明"本报告被截断、清单不完整"，读者不会把残缺清单当完整
清单。`environment.status`、清单条数、结构化 contract、self_check 和 dropped 全部进入
`task_prep_meta.json` 供审计。

预算与工具：30 LLM step、1800 s、每轮 tool result 60 KB；工具为 `read`、`exec`、
`web_search`（Exa 主、Firecrawl 备）、`web_fetch`，不受 writer 臂 `disabled_tools` 影响。
scratch 目录初始化单独给 180 s 并重试一次：它在 LLM 会话开始之前跑，失败会让整个 prep
机会作废（观察到的失败形态是 `llm_turns=0` 的 TimeoutError），而命令是幂等的
`rm -rf && mkdir`，重试没有副作用。

交接与消费，按保真度排序：

1. **沙箱状态**：直接生效，零损耗。
2. **self_check**：writer 拉取式消费，随时可跑、不限次数、零权威。机械条目多的清单必须
   实现成脚本并注册到 `self_check`；脚本只查结构覆盖（见实现原则），不硬编码期望取值；
   在 scratch 的合成小样上测试，打印通过/失败/不可判定三类。提示词写明脚本在空草稿或
   缺文件时也必须向 stdout 报告，缺文件是要打印的发现，不是静默退出的理由。两道机械
   关卡：artifact staging 失败时整节撤下（报告重新渲染），不宣传打不开的文件；staging 后
   harness 用空草稿跑一次预检，崩溃、超时或无输出就降级进 `dropped` 并保留文字清单
   （空草稿下报告"缺文件"是正确行为，算通过）。这只保证脚本不是坏的，不保证它判得对。

   交付本身受 `task_specific_prep_self_check` 控制，默认开。关掉时 prep 的提示词、预算和
   产出都不变，脚本照写照声明，只是 self_check 节、digest 里的命令和脚本 artifact 一起
   撤下（报告列出的文件仍可被 writer 发现，所以 artifact 必须一并撤）。这个开关的用途是
   把 self_check 通道的净效应从 prep 的整体效应里分离出来，配对跑一轮就能定论。
3. **报告文件 + digest 交接**：staging 完成后完整报告只存在于 `task_prep/PREP_REPORT.md`，
   不再内联 writer 首轮 prompt。首轮 prompt 注入一段 digest：运行时状态与已验证命令
   （这部分是真实状态的描述，必须 t=0 到达）、self_check 的**确切命令**（staged 却没被
   点名的文件 writer 不会去跑，这是 v18 SEC 零调用的直接原因）、清单与 findings 的条目数，
   以及一条明确指令"开始规划前先读 `task_prep/PREP_REPORT.md`"。文件式消费与 skills 的
   memory_get 拉取是同一形态；v8 的实测是 writer 被点名后会在第 1 至 4 次工具调用内读取
   报告文件。取消内联同时取消了 12,000 字符的注意力预算和尾部截断这一整类失败
   （v18 三题 artifact 引用被截断切掉）。staging 失败时 digest 退化为只含运行时状态，
   不宣传打不开的文件。
4. **合同对账**（仅 prep_verifier 臂）：harness 把结构化 contract 与冻结测试按引用的公开
   文件做双向差集，分歧注入 writer（见 [ARCHITECTURE.md](ARCHITECTURE.md)）。

writer 不回写采纳状态；采用链事后从 transcript 判断。

## 流程结构

```text
公开题面 + input/ + software/
  -> Prep（writer 同沙箱；read/exec/web；30 步 / 1800 s）
       1 跑通运行时，状态留在沙箱
       2 编译合同清单；机械条目多时实现为 self_check 脚本（合成小样上测试）
       3 补精确事实 / 可复用工具
  -> 一个 JSON -> 逐条机械校验（不合格丢条目，记 dropped）
  -> 收集 artifacts（缺失则重新渲染报告，撤下对应引用）
  -> stage task_prep/PREP_REPORT.md + task_prep/artifacts/
  -> writer 首轮 prompt 注入 digest：运行时状态 + self_check 命令 + 条目数
     + "先读 task_prep/PREP_REPORT.md"（prep_verifier 臂附合同对账注）
  -> writer：状态直接用；读报告文件；self_check 随时跑；依赖哪条清单就复查哪条
```

## 实测结果与下一步

两轮 26 题实测（[results/full26_two_rounds](results/full26_two_rounds/)）：v21 配对均差
`-0.0070`（t `-0.77`，n 24），v22 `+0.0163`（t `+1.26`，n 23）。方向在两轮之间翻转，
幅度都在噪声内。同一道题跨轮的 delta 可以差 0.2（Variant 从 `-0.1374` 到 `+0.0686`，
SEC 从 `+0.0244` 到 `+0.2638`），而配对均差只有 ±0.02，26 题测这个量级的效应功效不足。

机制侧的读数是正面的：报告生成率、self_check 交付率、findings 到达率在 v22 都比 v21 高，
v22 把 findings 放进 digest 之后，只存在于报告文件里的 findings 不再零到达。交付率不是
目标，交付之后是否转化为分数才是，这一点两轮都没有正面证据。

v23 修三处机制故障，不改产出设计：artifact 收集先看返回码再解析（此前文件不存在会被
误记成 `unreadable`，`artifact:missing` 分支实为死码），失败时列出 scratch 实际内容；
scratch 初始化 180 s 加一次重试；提示词写明 self-check 脚本在空草稿下必须打印。同时加
`task_specific_prep_self_check` 交付开关，用来单独测 self_check 通道。

下一轮的两个读数：`task_specific_prep_self_check=False` 与开启臂的配对差，以及 v23 的三处
修复是否把交付失败清零。实验设计上先剔除多轮 delta 恒为 0 的题（26 题里约一半），剔除
清单在看结果之前定好。

已知风险（按危害排序）：清单和脚本编码的是对题面的部分阅读，writer 会照着优化，脚本比
文字约束力更强、可能放大该效应；文件式交接后 writer 可能不读报告（v22 的实测是确实不读，
所以 findings 才要进 digest）；清单 24 条上限在 v18 有四题打满，未调整；prep 无法知道
writer 本来是否会自己发现同一事实，边际价值只能配对估计；沙箱修改无回滚。

验证状态：2026-07-22 在 pgl 测试副本（`~/ale/v21-test`，独立目录，主仓库与远端实验不受
影响）三套件 71 passed 1 skipped，改动文件 ruff clean，相邻套件的失败与主仓库基线是同一组
既有 WIP 失败，零新增。
