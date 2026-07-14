# pi-agent 的架构、工具与可优化面

本文讲清楚三件事：pi-agent 是什么、在一次 ALE 任务里它的 harness 由哪些部分组成用了哪些工具、哪里是开放的可以改来做我们自己的 harness。内容结合 pi 的源码（`/home/dataset-local/wcy/ALE-Test/pi`，npm 包 `@earendil-works/pi-coding-agent@0.80.3`）和它在 ALE 上真实运行的轨迹。

## 1. pi-agent 是什么

pi 是一个编码 agent，定位是薄而透明的执行外壳。它把一个 LLM 接上一组文件和 shell 工具，放进一个自主循环里，让模型读文件、跑命令、改文件、写文件来完成任务。它有意做得薄：不内置子 agent、不内置 MCP、不内置权限弹窗、不内置 plan mode 或 todo。它的设计文章说 core 保持小，把工作流相关的行为推到 extension、skill、prompt。

这个薄正是它适合当研究基座的原因。它不在模型和任务之间塞太多自己的意图，所以模型跑出来的行为基本是模型自己的行为，不是框架替它定的。要研究模型自己会怎么做、以及怎么用 harness 改进它，pi 这块干净画布比电池全包的框架更合适。

在 ALE 里，pi 用 headless 模式跑。`--mode json` 让它把每个事件按 JSON 行打到 stdout，`--approve` 自动批准所有工具调用不等人工确认，`--no-session` 关会话持久化，`--no-context-files` 不加载项目上下文文件。模型通过 `~/.pi/agent/models.json` 配成一个 OpenAI 兼容 provider。当前这轮实验用的模型是 gpt-5.6-sol，走 haoxiang 网关的 Responses API（pi 配 `api: openai-responses`，`clear_proxy: true` 剥掉容器里的失效代理直连网关）；deployer 配置见 `configs/agents/pi_gpt56.yaml`。pi 本身支持 35 个 provider、9 种 wire API（OpenAI Responses、Chat Completions、Anthropic Messages、Google 等），换模型只改 provider 配置即可，这也是它适合做跨模型对比的原因。

## 2. 一次任务里的 harness 全貌

先分清两个词。harness 指承载模型跑起来的整套外壳，包括主循环、上下文管理、工具接入、会话存储。scaffold 指注入给模型的引导结构，包括 system prompt、工具描述、规划或反思的提示、干预策略。pi 的特点是 harness 做得完整，scaffold 做得极薄。

一次任务从 pi 收到 prompt 到进程退出，harness 做的事按顺序是：

启动时装配。读 models.json 拿到 provider 和模型，构建 system prompt，注册七个工具，初始化上下文。

进入主循环。主循环在 `packages/agent/src/agent-loop.ts` 的 `runLoop`，结构是一个 `while (true)` 外层套一个内层，每次内层迭代流式取一条 assistant 响应，若带工具调用就执行，把结果推回上下文，发 turn_end，再检查是否该停。

每轮执行工具。工具调用打到容器的文件系统和 shell，结果作为 toolResult 消息进上下文。

上下文接近上限时压缩。compaction 机制自动摘要旧消息，实现在 `packages/agent/src/harness/compaction/`。

模型不再发工具调用时停止，进程退出。

这套流程里，主循环、工具执行、上下文压缩、会话存储都是 harness 做得完整的部分。薄的是 scaffold，下面第 4 节讲。

## 3. 用了哪些工具

pi 的内置工具在 `packages/coding-agent/src/core/tools/`，只有七个：read、bash、edit、write、grep、find、ls。全是文件和 shell 操作。没有 web 搜索、没有网页抓取、没有专用验证工具。联网靠 bash 里跑 curl 或 wget 兜底。要澄清一个容易搞错的点:pi 缺的是内置联网工具和内置子 agent 委派工具，但它并不缺视觉和记忆。`read` 工具读到图片（jpg/png/gif/webp 等）会以 image content block 的形式返回给模型，模型侧视觉输入是一等公民（受 `model.input` 是否含 image 门控）；会话以树状 jsonl 落盘、支持分支和自动压缩，`SKILL.md` 技能与 `AGENTS.md` 上下文文件构成一种持久记忆。之前把 pi 描述成"没有视觉、没有记忆"是不准确的，那说的其实是 ALE 部署包装层，不是 pi 本身。

在 ALE 的真实轨迹里，工具调用分布印证了这套工具够用。CFR 任务 135 步里 bash 用了 44 次、write 8 次、edit 8 次、read 7 次。bash 是主力，因为运行脚本、装依赖、查环境全靠它。read 和 write、edit 配合完成代码的读写改。多数 ALE CLI 任务的数据已在容器本地，所以没有 web 工具不构成瓶颈，这一点在 `ALE_qwen_run.md` 第 5 节有数据支撑。

工具本身是薄封装。每个工具就是把一个文件或 shell 操作包成模型可调用的接口，加了截断（`truncate.ts`）、输出累积（`output-accumulator.ts`）、文件改动队列（`file-mutation-queue.ts`）这类工程细节，没有内置任何任务逻辑或安全策略。

## 4. scaffold 为什么薄

### 4.1 system prompt 极薄

默认 system prompt 在 `packages/coding-agent/src/core/system-prompt.ts` 的 `buildSystemPrompt`。去掉 pi 自身文档的引用部分，实质内容只有三块：一句角色定义你是 pi 里的编码助手通过读文件执行命令编辑和写文件来帮用户；一个工具列表；两条通用准则回答简洁和清楚显示文件路径。

没有任务分解的提示，没有先规划再执行的引导，没有完成前先验证的要求，没有预算意识。Ising 任务里模型自发做了验证，CFR 任务里模型自发做了 debug，这些来自模型自身的行为倾向，不是 prompt 教的。

### 4.2 主循环没有硬护栏

`runLoop` 的停止条件只有三个：模型这条消息不含工具调用（自然停）；`shouldStopAfterTurn` 回调返回真；出现 error 或 aborted 的 stopReason。代码里没有 max steps、没有 max turns、没有 token 预算。

这直接解释了 CFR 刷到 135 步。只要模型每轮都还发工具调用、都还觉得没完，循环就不停。护栏的缺位是设计选择，pi 把何时停完全交给模型判断。对短任务没问题，对 CFR 这种模型会自我合理化的长任务就会失控。

有一个内置的安全处理值得记下。当 assistant 消息的 stopReason 是 length（输出被 token 上限截断）时，pi 不执行这条消息里的工具调用，而是把它们全标记为失败。因为截断意味着工具参数可能不完整，执行残缺的调用比不执行更危险。

### 4.3 上下文管理与会话是完整的

pi 有 compaction，上下文接近上限时自动摘要旧消息，在 `packages/agent/src/harness/compaction/`。会话存储在 `packages/agent/src/harness/session/`，用 jsonl 落盘。ALE 里我用 `--no-session` 关掉了会话持久化，因为每个任务是独立一次性的。compaction 在长任务里会触发，但 CFR 的 528 万 token 说明即便有 compaction，无步数护栏时上下文照样滚很大。

## 5. rollout 怎么看

一次 rollout 是 pi 在一个任务上从收到 prompt 到进程退出的完整过程。有三个层次可看。

原始事件流。`--mode json` 把每个事件按 JSON 行打到 stdout，deployer 存成任务目录下的 `transcript.jsonl`。事件类型有 agent_start/end（整个 rollout 起止）、turn_start/end（一轮起止）、message_start/update/end（消息生命周期）、tool_execution_start/update/end（工具执行）。看原始流最实用的是筛 message_end，每个 message_end 带完整字段：role、content（text、thinking、toolCall 等 part）、usage（各类 token 计数）、assistant 消息的 stopReason。

ALE 归一化轨迹。ALE 不直接用原始流打分，而是经 deployer 的 `parse_artifacts` 翻译成统一的 `trajectory.json`，字段是 schema_version、session_id、agent、steps、final_metrics。每个 step 有 source、message、reasoning、tool_calls、observation、metrics。pi 的 deployer 只消费 message_end 事件重建轨迹，跳过 tool_execution_ 事件避免重复。看归一化轨迹用 `view_pi_trajectory.py`，传任务输出目录，它按步打印 THINK、MSG、CALL、RSLT。

结果账本。每个任务目录有 `run.json`（status、score、termination.reason、timings、usage 汇总）和 `eval_result.json`（评分细节）。看一批任务的分布用 `summarize_pi_cli.py`。一个完整 rollout 目录含 transcript.jsonl、trajectory.json、run.json、eval_result.json、prompt.txt、stderr.log、output/。

## 6. 哪里是开放的可以改的

这是本文对搭 harness 最有用的一节。pi 虽然 scaffold 薄，但它把改造点暴露得很清楚。要做我们自己的 harness，不必 fork 或重写主循环，只要挂到下面这几个面上。改造点按从轻到重排。

### 6.1 三个循环内钩子（最关键）

pi 的 `AgentLoopConfig`（`packages/agent/src/types.ts`）暴露了三个回调，主循环在固定位置调用它们。这是 pi 留给外部注入行为的核心接口，也是我们做 harness 的主要抓手。

`shouldStopAfterTurn(context)`（types.ts:213，loop 在 agent-loop.ts:248 调用）。每轮工具执行完后调用，返回 true 就停。这是加预算护栏和终止判据校正的位置。可以在这里数步数、累计 token，超预算返回 true 强制止损；也可以接一个客观完成检查，只有达标才允许停。CFR 的 135 步失控和跑完零分两类失败，都能在这个钩子里接住。

`beforeToolCall(context, signal)`（types.ts:267，loop 在 agent-loop.ts:621 调用）。工具执行前调用，可以返回一个结果覆盖掉这次调用，等于拦截。这是加操作前置守卫的位置。比如检测到一个 edit 的目标文件本轮还没被 read 过，就拦下来，返回一条提示先读再改；比如检测到重复执行同一条失败命令，就拦下提示换思路。

`afterToolCall(context, signal)`（types.ts:281，loop 在 agent-loop.ts:722 调用）。工具执行后调用，可以部分覆盖工具结果。这是把事实注入观察的位置。比如某个脚本跑出了一个客观指标，可以在结果里附一句这个指标当前值和目标值的对比，把事实反射给模型，逼它面对差距。

这三个钩子合起来，正好覆盖搭 harness 需要的三种介入时机：动作前拦截（beforeToolCall）、动作后反射（afterToolCall）、轮末止损（shouldStopAfterTurn）。而且它们的契约都是外部注入事实或控制，不替模型生成动作，天然贴合镜子非地图的约束。

### 6.2 extension 系统（注册工具和订阅事件）

pi 有一套 extension 系统，在 `packages/coding-agent/src/core/extensions/`（loader、runner、types、wrapper）。extension 是 TypeScript 模块，能做四件事：订阅 agent 生命周期事件、注册可被 LLM 调用的工具、注册命令和快捷键和 CLI flag、通过 UI 原语与用户交互。

对搭 harness，extension 有两个用法。一是补工具，比如注册一个 search 工具或一个通用 verifier 工具，填上 pi 内置七件套没有的能力。二是订阅事件做记录和分析，比如订阅 turn_end 累积轨迹特征，供钩子里的判断逻辑用。

### 6.3 system prompt（注入通用准则）

`buildSystemPrompt` 是最轻的改造点。pi 默认 prompt 极薄，任何通用的程序性准则都可以加在这里，比如改文件前先读文件、产出后先自检、回答前先查已有信息。这类准则是一次性静态注入，不针对具体状态，成本最低但只能改变模型的默认倾向，不能在运行中相机干预。相机干预要靠 6.1 的钩子。

### 6.4 models.json（provider 和采样）

`~/.pi/agent/models.json` 控制 provider、模型、api 类型、thinking 档位、context_window、max_tokens。换模型、开关 reasoning、调上下文窗口都在这里。ALE 里我用它把模型配成 apihy 的 qwen3.5-397b，thinking 关闭。

### 6.5 一张改造点对照表

| 改造点 | 位置 | 能做什么 | 介入性质 |
|---|---|---|---|
| shouldStopAfterTurn | agent-loop.ts:248 | 预算止损、终止判据校正 | 轮末控制 |
| beforeToolCall | agent-loop.ts:621 | 操作前置守卫、拦截重复失败 | 动作前拦截 |
| afterToolCall | agent-loop.ts:722 | 把客观事实注入观察 | 动作后反射 |
| extension | core/extensions/ | 补工具、订阅事件采特征 | 能力与观测 |
| system prompt | system-prompt.ts | 注入通用程序性准则 | 静态倾向 |
| models.json | ~/.pi/agent/ | 换模型、调采样与上下文 | 基础配置 |

搭我们自己的 harness，主战场是 6.1 的三个钩子加 6.2 的 extension。它们让我们在不 fork pi、不动模型的前提下，把预算、前置守卫、事实反射、补充工具挂上去。具体要挂什么、怎么守住不泄露答案的红线，见 `next_step.md`。

## 7. 作为 ALE 研究和评测 harness 的判断

对无图形界面的代码和安全类 ALE 任务，pi 比 ale_claw 这类重型的 OpenClaw 派生框架更适合做研究和评测基座。理由有四条，都指向"把变量控住、把轨迹用好"。

第一，工具边界干净，利于归因。ALE 的代码和安全题本质是 Linux 容器里的文件加 shell 工作，pi 的七件套正好就是这个范围，没有 GUI、没有 MCP、没有浏览器。跑出来的成败基本能归到模型的推理上，而不是被框架的工具噪声干扰。ale_claw 的图形界面、MCP、子 agent 对无头代码题多是负担，还给轨迹添噪。

第二，可复现。pi 的循环把错误当值不抛异常、工具调用顺序化预检、结果按源序回、还带一个 faux provider 可以无 API 键做确定性测试，加上锁版本和 shrinkwrap。要做严谨的评测和消融，这些都是加分项。

第三，也是最关键的一条，轨迹质量高、天然适合做训练数据。pi 的会话 jsonl 完整记录每一步的工具调用、工具结果、思考块、每轮的 token 用量和成本、模型与思考档的切换，格式有文档、有版本、易解析。这正是做 SFT 和 RL 训练数据的理想来源。要研究 harness 引导模型 on-policy 产生可学习轨迹、再把轨迹内化进权重，pi 产出的这种高保真可解析轨迹比自定义图形界面框架的日志好用得多。这一点和 harness-model 协同进化的研究主线直接相关:harness 负责产出高质量轨迹，轨迹经筛选后喂给后训练，模型把能力内化。

第四，可跨模型比较。pi 的模型层支持 35 个 provider、9 种 API，同一套 harness 能评很多模型，做跨模型的 ALE 对比时不用换 harness，变量更少。

反过来，只有当任务真的需要图形界面操作（比如 cybersecurity 子领域那 4 道 Windows 桌面题）时，才轮到 ale_claw。那种情况 pi 的 sandbox 执行器根本接不上 Windows 桌面会话。两套 harness 的定位因此是互补的:pi 是无头代码和安全任务的干净研究基座，ale_claw 是需要图形界面时的重型工具。
