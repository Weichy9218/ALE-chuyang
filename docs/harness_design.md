# pi 上的 harness 干预原型:设计、消融与不泄露论证

本文交付一套挂在 pi 上、只给事实和控制、不给答案的 harness 干预原型。三个 extension 已经写好并在本机用 mock 网关跑通冒烟测试。文档讲清楚每个干预挂在哪、注入什么、怎么消融、为什么不越不泄露红线。

代码在 `harness/extensions/` 三个文件,冒烟测试在 `harness/smoke/`。

结论先说:三类干预(轮末止损、动作前守卫、动作后事实反射)都落地成了可跑的 pi extension,三个冒烟场景全过。每个干预都能用环境变量独立开关做消融,每条注入都过了 strip 测试。

## 1. 挂点确认:pi 到底怎么接干预

`pi-agent.md` 第 6 节说 pi 暴露三个循环钩子。读源码确认了它们的真实接法,和文档一致,但有一个关键落地细节文档没提到,直接影响原型怎么写。

### 1.1 三个底层钩子确实存在

pi 的 `AgentLoopConfig`(`packages/agent/src/types.ts`)有三个回调:`shouldStopAfterTurn`(types.ts:213,loop 在 agent-loop.ts:248 调)、`beforeToolCall`(types.ts:267,loop 在 621 调)、`afterToolCall`(types.ts:281,loop 在 722 调)。行号与文档一致。

### 1.2 但外部注入走的是 extension 事件,不是直接设这三个回调

关键细节:`agent-session.ts` 的 `_installAgentToolHooks`(:419)已经把 `beforeToolCall`/`afterToolCall` 占用了,内部转发给 extension 的 `tool_call`/`tool_result` 事件。所以我们不该去覆盖这三个底层回调(会和 pi 自己的转发打架),而应该写 extension、订阅事件。对应关系是:

| 想要的介入 | 底层钩子 | extension 事件 | 干预手段 |
|---|---|---|---|
| 动作前拦截 | beforeToolCall | `on("tool_call")` 返回 `{block:true, reason}` | 拦下这次调用,reason 作为错误结果回给模型 |
| 动作后反射 | afterToolCall | `on("tool_result")` 返回 `{content}` | 在工具结果末尾追加事实文本 |
| 轮末控制 | shouldStopAfterTurn | `on("turn_end")` + `sendUserMessage`/`sendMessage` | 反射用量、注入 steer/followUp、触发终止 |

extension 通过 `--extensions <dir>` 或放进 `PI_CODING_AGENT_DIR/extensions/` 被自动发现(loader.ts:604 的 discoverExtensionsInDir)。ALE 的 pi deployer 写 models.json 到 `~/.pi/agent/`,extensions 放同目录下 `extensions/` 即可被 json 模式加载。

### 1.3 一个 json 模式下必须绕过的坑:硬止损停不掉循环

`shouldStopAfterTurn` 若被 extension 间接实现,没有直接返回 true 的入口。extension 侧能拿到的终止手段是 `ctx.abort()` 和 `ctx.shutdown()`。但实测(冒烟 loop 场景)这两个在 json 模式下都停不掉循环:

- `ctx.abort()` 只打断"进行中的流",而 turn_end 时刻流已结束,abort 无效。
- `ctx.shutdown()` 依赖 `_extensionShutdownHandler`,只有 interactive 和 rpc 模式绑定它(rpc-mode.ts、interactive-mode.ts),json/print 模式下是静默空操作。

所以硬止损做了分层(budget-guard.ts):
1. 到达预算,`tool_call` 事件一律 block(附预算事实),同时 steer 一条"预算耗尽,立即收工"。真实模型一两轮内自然停,拿到干净的 agent_end。
2. 超限后再跑 `PI_BUDGET_GRACE_TURNS` 轮还不停(病态循环),`process.exit(0)` 兜底,退出前把事实写进会话和 stderr。

冒烟 loop 场景验证:mock 模型被设成"永远发 bash",预算 3 轮,结果第 3 轮后工具调用被封锁、宽限后兜底退出,assistant 轮数停在 5(远小于失控的 60+)。这条坑很重要——不知道的话,以为设了预算就有护栏,实际长任务照样烧满墙钟。

## 2. 三个干预原型

### 2.1 budget-guard:预算护栏(轮末控制 + token 记账)

挂 `turn_end`(数轮数、反射用量、判止损)、`message_end`(累计 token)、`tool_call`(耗尽后封锁)。

注入两类内容:
- 预算事实:`已用 N/M 轮,上下文占 X%,累计 K token`。软提醒在到达阈值(默认上限的 80%)时给一次,之后每若干轮再给。
- 控制信号:到上限后拒绝新工具调用,并要求立即总结收工。

治的失败:CFR 那类 135 步、528 万 token 的失控。pi 主循环无 max_steps、无 token 预算,这是补的第一层护栏。25 题对跑里 pi 的 5 个超时(clustered_cyclic、particle_filter、humanoid_wbc、mpc_control、sumo)都是这个洞造成的,gpt_claw 靠 max_turns=30 兜住了。

消融开关:`PI_GUARD_BUDGET=off` 整体关;`PI_BUDGET_MAX_TURNS`、`PI_BUDGET_WARN_FRAC`、`PI_BUDGET_MAX_TOTAL_TOKENS`、`PI_BUDGET_GRACE_TURNS` 调各阈值。

### 2.2 action-guard:动作前守卫(动作前拦截 + 状态记账)

挂 `tool_call`(拦截)、`tool_result`(记已读文件、记命令失败连击)。两条规则:

- 改前先读:edit/write 一个磁盘上已存在、但本会话从未 read 过的文件时,拦一次。返回事实"这个文件存在且本会话没读过,本次未执行,重发即放行"。不告诉文件里是什么。
- 重复失败:同一条 bash 命令连续失败达阈值(默认 2 次)、又要原样执行时,拦一次。返回事实"这条命令已连续失败 N 次,本次未执行,重发即放行"。不告诉怎么改。

关键设计:拦截是**一次性**的。同一目标只拦一次,模型重发同一动作即放行。这保证守卫最多给任何动作加一步延迟,绝不会把 agent 锁死。这一点很重要,否则一个判断失误就可能让 agent 卡死。

治的失败:盲改覆盖(改没看过的配置/数据文件容易破坏结构);CFR 在一个 shape bug 上反复重跑同一失败命令绕十步。

消融开关:`PI_GUARD_ACTION=off` 整体关;`PI_GUARD_READ_BEFORE=off`、`PI_GUARD_REPEAT_FAIL=off` 分别关两条规则;`PI_GUARD_REPEAT_N` 调失败阈值。

### 2.3 fact-mirror:事实反射(动作后反射 + 收工时机反射)

三面镜子:

- 失败连击:同一 bash 命令连续失败达阈值时,在工具结果末尾追加一行"这条命令已连续失败 N 次"(afterToolCall 反射面)。
- 声明文件存在性:agent 准备收工(assistant 消息不含工具调用)时,检查任务描述里提到的文件路径当前是否存在,把"仍不存在的路径清单"反射回去。只查存在性,不查内容。
- 指标对照(默认关,需配置):从 agent 自己产出的结果文件读一个数值,与任务公开规格声明的阈值并排反射:"当前值 1.17,任务声明目标 <= 0.05,当前不满足"。阈值必须来自 agent 本就可见的任务规格,不许来自评测器或参考答案。不说怎么达标。

治的失败:CFR 的核心失败——模型明知可利用度 1.17 不达标(目标 0.05),却因为"文件写出来了"就收工。指标对照镜子直接把这个差距怼到它眼前,逼它面对。声明文件存在性镜子治"漏产出物就收工"。

反射有次数上限(`PI_MIRROR_MAX_NUDGES`,默认 2),防止反射本身造成无限循环。

消融开关:`PI_GUARD_MIRROR=off` 整体关;`PI_MIRROR_FILES=off` 关文件镜子;`PI_MIRROR_METRIC_SPEC` 设了才开指标镜子(值是 JSON,声明看哪个文件的哪个字段、比什么阈值)。

指标镜子的配置举例:
```
PI_MIRROR_METRIC_SPEC=[{"file":"results.json","path":"tier3.exploitability","op":"<=","target":0.05,"label":"tier3 exploitability"}]
```
`target` 只能从任务公开规格(task_specification)里抄,这是不泄露的前提,见第 4 节。

## 3. 消融方案

要证明是 harness 起作用、不是题目本身,消融必须做到"同题、同模型、只差 harness 开关"。

### 3.1 开关矩阵

所有干预都由环境变量控制,ale_run 侧通过 pi 配置的 `extra_envs` 下发(config.py 的 extra_envs 字段直接进 pi 子进程环境)。基线到全开是一条可拆的链:

| 配置 | 环境变量 | 目的 |
|---|---|---|
| 基线(无 harness) | 全 `=off`,或不装 extensions | 拿模型裸表现 |
| 只加止损 | `PI_GUARD_ACTION=off PI_GUARD_MIRROR=off` | 单看预算护栏对超时题的作用 |
| 只加守卫 | `PI_GUARD_BUDGET=off PI_GUARD_MIRROR=off` | 单看动作前拦截 |
| 只加反射 | `PI_GUARD_BUDGET=off PI_GUARD_ACTION=off` | 单看事实反射 |
| 全开 | 全默认 | 看叠加效果 |

### 3.2 消融跑法

选题:A3 调试/修复类(task_selection.html 的分组),因为基线低、头顶空间大,harness 钩子提升空间最大。CFR、particle_filter、mpc_control 这些已知失败题是最直接的验证靶子。

跑法:每个配置在同一批题上各跑一遍(最好每题重复 3 到 5 次压方差,因为单题跑间抖动能到 0.34),比三个指标:
- 平均分,分开看超时数和"跑完零分"数有没有降。
- 平均步数和平均 token,看止损有没有省下预算。
- 每条干预的触发次数(extension 已经把注入写进会话,可从 transcript 里数 `[harness ...]` 出现次数)。

止损的目标是把超时题从 timeout(0 分)变成 completed(至少不浪费预算),反射的目标是把"跑完零分"变成正分。这两类正好是 25 题对跑里 pi 的两大失败来源,是最可能真正提分的地方。

### 3.3 冒烟测试(已跑,证明触发路径通)

`harness/smoke/` 用一个 stdlib 的 mock OpenAI 网关脚本化驱动 pi,不烧真实网关额度,验证三条干预的触发路径。三个场景当前全过:

- guard:未读先改被拦 → 读 → 改放行 → 同一命令连败 → 重复执行被拦 → 失败连击被镜子追加 → 提前收工被反射缺文件 → 补产出后收工。5 项断言全过。
- loop:mock 模型永远发命令,验证预算耗尽后工具封锁 + 宽限兜底退出。3 项断言全过。
- metric:产出 metric=1.17 的结果文件后想收工,验证指标对照事实(1.17 vs <=0.05)被反射且恰好一次。2 项断言全过。

跑法:`bash harness/smoke/run_smoke.sh {guard|loop|metric}`。它随机端口起 mock 网关、用真实 pi CLI(json 模式)跑一遍、再用 `check_smoke.py` 断言 transcript。这套是回归测试,改 extension 后重跑确认没坏。

冒烟只证明"干预在真实 pi 循环里被正确触发",不证明"干预在真实任务上提分"。提分要靠 3.2 的消融在真实网关和真实题上跑。

## 4. 不泄露论证

红线:harness 注入的所有信息,必须是 agent 自己能观察到的事实或环境/预算事实,不能是任务答案的任何部分。逐条过 strip 测试(删掉注入,模型是否仍能靠自己产出正确行为,只是慢一点)。

| 干预 | 注入的是 | strip 测试 | 判定 |
|---|---|---|---|
| 预算用量 | 已用轮数/token、上下文占用 | 删掉,模型仍能解题,只是长任务可能失控超时 | 过。用量是模型自身资源的事实 |
| 预算硬止损 | 控制信号(拒绝工具、要求收工) | 这是控制不是内容,不涉及答案 | 过。护栏,非解法 |
| 改前先读 | "这文件存在且没读过" | 删掉,模型仍会自己想到先读,只是有时忘 | 过。纪律前置,非内容 |
| 重复失败拦截 | "这命令连败 N 次" | 删掉,模型仍会自己换命令 | 过。行为事实,换什么由模型定 |
| 失败连击反射 | "连败 N 次" | 同上 | 过 |
| 缺文件反射 | "任务提到的路径 X 当前不存在" | 删掉,模型自己 ls 也能发现 | 过。存在性事实,是否需要由模型判 |
| 指标对照反射 | "当前值 X,任务声明目标 op T,不满足" | 删掉,模型自己算指标、自己读任务规格也能得出 | 过,但有前提 |

指标对照是最接近边界的一条,前提必须守住:阈值只能来自 agent 本就可见的任务规格(task_specification 里公开写的目标,如 CFR 明写"Tier 3 exploitability 目标 0.05"),数值只能来自 agent 自己产出的结果文件。这两个 agent 都能自己拿到,harness 只是把"现值 vs 目标"这个对比拎到眼前。绝不能:阈值来自评测器内部标准、数值来自参考答案、或者提示怎么把指标压下去。配置项 `PI_MIRROR_METRIC_SPEC` 的 target 字段是人填的,填的时候要对着任务公开规格填,这一步需要人守。

自动兜底:所有注入文本都带 `[harness ...]` 前缀,可被扫描审计(对应 MetaX 的 leak_audit)。数据抽取脚本(data_construction.md 第 4.3 节)会把带注入的消息标记出来,`--strip-harness` 能剥掉,用于验证"没有 harness 也做对"。这就是 harness 侧和数据侧共用的红线检查。

一个 MetaX 提出、这里同样存在的开放问题:指标镜子"在不达标时打断"这个时机选择,本身是否含了对任务的隐性理解。判据仍是 strip 测试——注入的是"现值 vs 公开目标"这个事实对比,不是"该怎么达标"。只要 target 严格来自公开规格,这条就在事实一侧。这个边界要在实践里盯着。

## 5. 待办

- 三个 extension 是 TypeScript,pi 用 jiti 直接加载 .ts,不需要预编译。但要在 ALE 的容器里跑,得确认容器内 pi 能 resolve `@earendil-works/pi-coding-agent` 类型(装 pi 时带的),已确认 loader 用 virtualModules 提供这些,extension 里的 `import type` 只在类型层、运行时不解析,安全。
- 消融还没在真实网关跑。下一步在本机 Docker 上对 A3 的几道题跑基线对全开,先看止损能不能把 5 个超时题救回来。这一步要用真实网关,注意额度。
- 指标镜子的 `PI_MIRROR_METRIC_SPEC` 目前每题手配。可以做一个从 task_specification 自动抽阈值的辅助脚本,但抽取逻辑本身要过审(不能把评测标准当成公开规格抽进来)。
- budget-guard 的 `process.exit(0)` 兜底是 json 模式的无奈之举。更干净的做法是给 pi 提 PR,让 json 模式也绑定 shutdown handler,或让 extension 能直接返回 `shouldStopAfterTurn=true`。在那之前 exit 兜底是可靠的。
