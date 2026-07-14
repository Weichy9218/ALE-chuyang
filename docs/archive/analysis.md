# pi-agent 在 ALE 上的轨迹分析与 harness 定位

本文基于在 tyyun_4 上用 pi-agent（`@earendil-works/pi-coding-agent@0.80.3`）跑 ALE（agents-last-exam）的实测数据。模型是 Qwen3.5-397B-A17B，经 apihy 网关调用。目标是理解 pi 的架构、熟悉 ALE 任务形态，并为下一步搭 harness 提高模型能力定方向。

运行状态：全量 99 个 CLI 任务已跑完。其中 96 个是真实尝试（模型实际消耗 token），平均分约 0.29；另有 13 个曾被网关 402 配额中断，已重跑，其中 3 个因本机资源不足（需 16 CPU、60 GB）无法运行、已排除。最终逐题结果与详细分析见 `ALE_qwen_run.md`。下面两个轨迹分析取自已完成任务。

## 目录

1. 运行现状与数据
2. 成功轨迹逐步分析：量子 Ising 链后测量态
3. 失败轨迹逐步分析：CFR 博弈均衡求解
4. 怎么看 pi-agent 的 rollout
5. pi 的 harness 与 scaffold 对应到代码
6. 三方架构对比：pi、Claude Agent SDK、self_harness_agent
7. ALE 长程任务需要 harness 发挥什么功能
8. 下一步搭 harness 的建议

## 1. 运行现状与数据

实验配置：experiment `local_docker_pi_qwen35_cli`，99 个 CLI 任务（`ale_cli.txt` 与 `docker_support.txt` 的交集），concurrency=4，每任务 wall_time 7200 秒，cleanup_mode=delete。每个任务起一个 `agentslastexam/ale-ubuntu22-docker` 容器，pi 在容器内跑，用容器自带的 node 与 python。

96 个真实尝试的分布（近似分档，精确分布见 `ALE_qwen_run.md`）：

| 类别 | 数量 | 含义 |
|---|---|---|
| score=1.0 | 10 | 完全做对 |
| 0<score<1 | 34 | 部分正确 |
| score=0 且 completed | 约 32 | 流程跑完但答案错 |
| timeout | 19 | 跑满 7200 秒被杀 |
| failed | 2 | 进程报错退出 |

平均分约 0.29。参照系是同一套 ALE、OpenHands harness、Qwen3.5-9B 的全量结果，平均分约 0.06。换成 397B 大模型加 pi harness 后，平均分是前者的四到五倍。这个差主要来自模型规模，不能全记到 harness 头上，但至少说明 pi 这套接入没有明显拖后腿。

对判断瓶颈更有用的是失败构成。真实零分任务里，只有极少数的描述含联网或下载类关键词，且多是进程报错而非缺工具。所以“pi 缺搜索工具导致失败”这个担心，数据不支持。真正拖分的是两件事：一是任务本身太难，模型算错；二是长任务超时。下面两个轨迹分别对应“做对”和“做错但跑完”这两种典型。

## 2. 成功轨迹逐步分析：量子 Ising 链后测量态

### 2.1 任务是什么

任务 `computing_math/ising_post_measurement_1`。给定一条临界的一维量子 Ising 链加一条 ancilla 链，N=10，耦合参数 u=0.1。要求算四样东西并存成 numpy 文件：临界基态 `critical_state.npy`、后测量概率 `post_probs.npy`、一号格点的约化密度矩阵 `rdm_site1.npy`、单体关联函数 `correlators.npz`。

物理上，基态要用虚时演化（imaginary time evolution，ITE）求，dt=0.0002，K=50000 步迭代。评分是数值容差检验，比如基态与精确对角化结果的保真度要达标，概率要归一，密度矩阵要厄米且迹为一。这是一个纯计算任务，输入文件已在本地，不需要联网，软件栈是 Python、NumPy、SciPy。

### 2.2 agent 怎么解的

pi 跑了 46 步，reward=1.0，输入 24 万 token，输出 1 万 token。分四个阶段。

第一阶段，读规格（步 3 到 9）。agent 一上来同时读 `task_specification.md` 和 `config.json`，拿到 N、u、dt、K 这些参数，再读 `pyproject.toml` 和 `requirements.txt` 确认依赖是 numpy==2.2.6、scipy==1.15.3，并 `ls` 输入目录确认没有 staged 的 ancilla 文件。这一步一次读多个文件，没有浪费。

第二阶段，写解题脚本（步 10 到 13）。agent 建好 output 目录，一次性写出 12591 字节的 `solve.py`，涵盖虚时演化求基态、逐个测量结果算后测量态、算约化密度矩阵和关联函数。

第三阶段，也是这个任务真正的卡点，是环境问题（步 14 到 32）。第一次运行报 `ModuleNotFoundError: No module named 'scipy'`。接下来八步都在找对的 Python 解释器：

- 步 16 `pip install`，报缓存目录不可写，且提示包其实已装。
- 步 18 `import scipy` 仍然 ModuleNotFound。
- 步 20 再 `pip3 install`，同样缓存不可写。
- 步 22 打印 `sys.path`，发现当前 python3 是 3.14 版本。
- 步 24 `python3 -m pip` 报 no module named pip。
- 步 26 `uv pip install` 报缓存目录 permission denied。
- 步 28 到 30 确认默认 python3 指向 `/opt/cua-server/.venv/bin/python3`，是 3.14 版，里面没装 scipy。
- 步 30 试 `/usr/bin/python3`，发现系统 Python 是 3.10.12，且 numpy 2.2.6 已装。

症结是：容器里默认的 `python3` 是 cua-server 用的 3.14 虚拟环境，没有科学计算包；系统 `/usr/bin/python3` 是 3.10，包齐全。步 32 改用 `/usr/bin/python3 solve.py`，脚本跑通。

第四阶段，验证（步 34 到 46）。agent 没有算完就交，而是连做多项独立检查：加载输出看形状和归一性；自己另写一段精确对角化代码，算出基态与 ITE 结果的保真度是 0.99999990，态的不保真度约 1e-7，远低于 1e-4 的容差；检查若干测量结果的密度矩阵是否厄米、迹是否为一、本征值是否合法；检查关联函数是否落在 [-1,1]；最后 `ls` 确认四个文件都在。步 46 给出总结。

### 2.3 这个成功说明什么

模型的物理和数值能力足够，一次就写对了 ITE 加精确对角化的完整解法，还自己造了一个独立的验证器。真正花步数的是环境摸索，八步试错才定位到 Python 解释器问题。

这里有一个可以被 harness 消化的点。容器里“默认 python3 是 3.14 无科学包、系统 python3 是 3.10 有包”这个事实，对所有 Python 计算类任务都成立。成功任务花八步试出来，别的任务可能试不出来就放弃或超时。如果 harness 在任务开始时把这条环境事实直接告诉模型，或提供一个已配好依赖的运行入口，这八步就能省掉。这不是给答案，是给环境事实，属于 harness 该管的范围。

## 3. 失败轨迹逐步分析：CFR 博弈均衡求解

### 3.1 任务是什么

任务 `computing_math/cfr_game_theory_equilibrium`。实现三层递进的两人零和博弈均衡求解器，合并成一个 `results.json`。三层是：

- Tier 1：矩阵博弈，求均衡值、行列混合策略、支撑集。
- Tier 2：Kuhn poker，用 CFR 迭代，报最终可利用度（exploitability）、平均策略、博弈值、信息集数量。
- Tier 3：4-rank Leduc poker，用 MCCFR，报可利用度、完整平均策略表、信息集数量、精确博弈参数。

评分有硬门槛：`results.json` 缺失、JSON 解析失败、或 Tier 1 的公开 minimax 与支撑一致性检验不过，任一触发直接零分。三层各有可利用度目标，Tier 3 目标是 0.05。难点在 CFR 和 MCCFR 要真收敛到低可利用度，不只是把代码写出来。

### 3.2 agent 怎么解的

pi 跑了 135 步，reward=0.0，输入 528 万 token，输出 10 万 token。这是所有任务里 token 消耗最高的一个，也是步数最多的之一。工具调用构成是 bash 44 次、write 8 次、edit 8 次、read 7 次，报错结果 14 次。

前段（步 9 到 40 左右）是环境准备和三层求解器的初版实现，agent 读规格、bootstrap 运行时、写 `solver.py`。

中段是长时间 debug。轨迹里能看到 agent 反复运行 solver、看输出、发现某处不对、edit 修改、再运行。一个典型循环发生在步 113 到 122：agent 发现 `regret_matching` 函数在所有 regret 为零时返回固定的两元素数组 `[0.5, 0.5]`，而实际策略维度可能是 3，导致形状不匹配。它加调试打印定位，改对函数，再删掉调试打印，再运行。单是这一个 shape bug 就绕了差不多十步。

后段（步 124 到 135）是收尾。solver 终于完整跑通，产出格式正确、含三层全部字段的 `results.json`。但 agent 自己在步 125 的思考里写道，Tier 3 的可利用度是 1.17，远高于 0.05 的目标。它在步 127、129、131 反复确认输出结构正确、可利用度偏高，然后在步 135 判定任务完成并给出总结。

### 3.3 卡点在哪，为什么零分

卡点不是不会写，是写出来的 MCCFR 没收敛。Tier 3 可利用度 1.17 对目标 0.05 差了二十多倍，意味着求出的策略远不是均衡。这通常是迭代次数不够，或采样、平均策略累积、遍历方式有实现问题。

更值得注意的是 agent 的收尾判断。它明确知道可利用度不达标，却因为“输出格式正确、结构完整”就认定任务完成。这是一次自我合理化：把“我产出了一个文件”当成“我解决了问题”。ALE 的评分不看格式看数值，格式对但数值错，实质是零。

从这条轨迹能读出三个问题：

第一，模型能实现算法框架，但让迭代类算法真正收敛到指标要求，超出了它一次成型的能力，它也没有靠自己把可利用度压下去。

第二，没有有效的止损。135 步、528 万 token 里，很大一部分花在一个 shape bug 的反复试探上。上下文越滚越长，每一步的输入 token 都在累积，528 万这个数就是这么堆出来的。

第三，也是对搭 harness 最有启发的一点，是终止判据错位。agent 用“文件写出来了”作为完成信号，而任务的真实完成信号是“可利用度达标”。模型手里有可利用度这个数，也知道它不达标，但没有一个机制强制它在不达标时继续迭代而不是收工。

### 3.4 为什么能刷到 135 步

这一点直接对应 pi 的架构，放到第 5 节讲。简短说：pi 的主循环没有步数上限，也没有 token 预算，它靠模型自己不再发起工具调用来停。模型只要一直觉得“我还能再修一下”，循环就一直转。cfr 这个任务里，模型陷在 debug 循环里始终认为下一步能修好，于是转到 135 步才因为自认完成而停。

## 4. 怎么看 pi-agent 的 rollout

一次 rollout 就是 pi 在一个任务上从收到 prompt 到进程退出的完整过程。看 rollout 有三个层次。

### 4.1 原始事件流

pi 用 `--mode json` 启动时，把每个事件按 JSON 行打到 stdout。deployer 把这条流存成任务目录下的 `transcript.jsonl`。事件类型定义在 `packages/coding-agent/src/core/agent-session.ts` 和 `packages/agent/src/types.ts`，主要有：

- `agent_start` / `agent_end`：整个 rollout 的起止。
- `turn_start` / `turn_end`：一轮的起止。一轮是“模型发一条 assistant 消息加执行它的工具调用”。
- `message_start` / `message_update` / `message_end`：消息的生命周期。`message_update` 携带流式增量，`message_end` 携带完整消息。
- `tool_execution_start` / `tool_execution_update` / `tool_execution_end`：工具执行的起止和结果。

看原始流最实用的是筛 `message_end`。每个 `message_end` 的 message 带完整字段：role（user、assistant、toolResult）、content（text、thinking、toolCall 等 part）、usage（input、output、cacheRead、reasoning、cost 等 token 计数）。assistant 消息还带 stopReason，能看出是正常停、还是被 length 截断、还是 error。

### 4.2 ALE 归一化的轨迹

ALE 不直接用 pi 的原始流打分，而是经过 deployer 的 `parse_artifacts` 把它翻译成统一的 `trajectory.json`。这个格式跨所有 harness 一致，字段是 schema_version、session_id、agent、steps、final_metrics。每个 step 有 source（user、agent、environment、system）、message、reasoning、tool_calls、observation、metrics。

pi 的 deployer 只消费 `message_end` 事件来重建轨迹，跳过 `tool_execution_*` 以避免工具调用和结果被记两遍。assistant 的 thinking part 进 reasoning 字段，text 进 message，toolCall 进 tool_calls，usage 进 metrics。toolResult 消息进 observation。这段逻辑在 `ale_run/agents/pi/deployer.py` 的 `_consume_event` 系列方法里。

看归一化轨迹用 `view_pi_trajectory.py`，传任务输出目录即可，它按步打印 THINK、MSG、CALL、RSLT 四类行。第 2、3 节的逐步分析就是这么读出来的。

### 4.3 结果与账本

每个任务目录还有 `run.json` 和 `eval_result.json`。`run.json` 记 status、score、termination.reason、timings.duration_s、usage 汇总（总步数、总输入输出 token、总时长）。`eval_result.json` 记评分细节。要快速看一批任务的分布和归因，用 `summarize_pi_cli.py`，它扫所有 run.json，输出满分、部分分、超时、零分四类清单，并对零分任务标出哪些含联网关键词。

一个 rollout 目录的完整结构是：`transcript.jsonl`（pi 原始流）、`trajectory.json`（归一化轨迹）、`run.json`（结果账本）、`eval_result.json`（评分）、`prompt.txt`（任务描述）、`stderr.log`、`output/`（agent 产出的文件）。

## 5. pi 的 harness 与 scaffold 对应到代码

先分清两个词。harness 指承载模型跑起来的整套外壳，包括循环、上下文管理、工具接入、会话存储。scaffold 指注入给模型的引导结构，包括 system prompt、工具描述、规划或反思的提示、干预策略。pi 的特点是 harness 做得完整，scaffold 做得极薄。

### 5.1 主循环没有硬护栏

pi 的核心循环在 `packages/agent/src/agent-loop.ts` 的 `runLoop`。它的结构是一个 `while (true)` 外层套一个 `while (hasMoreToolCalls || pendingMessages.length > 0)` 内层。每次内层迭代：流式取一条 assistant 响应，若带工具调用就执行，把结果推回上下文，发 turn_end，然后检查是否该停。

停止条件只有这几个：模型这条消息不含工具调用（自然停）；`shouldStopAfterTurn` 回调返回真；出现 error 或 aborted 的 stopReason。代码里没有 max steps、没有 max turns、没有 token 预算。

这直接解释了第 3 节 cfr 刷到 135 步的现象。只要模型每轮都还发工具调用、都还觉得没完，循环就不停。护栏的缺位不是 bug，是 pi 的设计选择，它把“何时停”完全交给模型判断。对短任务这没问题，对 cfr 这种模型会自我合理化的长任务，就会失控。

有一个细节值得注意。当 assistant 消息的 stopReason 是 length（输出被 token 上限截断）时，pi 不执行这条消息里的工具调用，而是把它们全部标记为失败。因为截断意味着工具参数可能不完整，执行残缺的调用比不执行更危险。这是 pi 少数几个内置的安全处理之一。

### 5.2 system prompt 极薄

pi 的默认 system prompt 在 `packages/coding-agent/src/core/system-prompt.ts` 的 `buildSystemPrompt`。去掉 pi 自身文档的引用部分，实质内容只有三块：一句角色定义“你是 pi 里的编码助手，通过读文件、执行命令、编辑和写文件来帮用户”；一个可用工具列表；两条通用准则“回答简洁”和“清楚显示文件路径”。

没有任务分解的提示，没有“先规划再执行”的引导，没有“完成前先验证”的要求，没有预算意识。第 2 节 Ising 任务里模型自发做了验证，第 3 节 cfr 任务里模型自发做了 debug，这些都来自模型自身的行为倾向，不是 pi 的 prompt 教的。

这是 pi 的明确哲学。它的 README 和设计文章说，core 保持小，把工作流相关的行为推到 extension、skill、prompt template。它有意不内置 MCP、子 agent、权限弹窗、plan mode、todo、后台 bash。pi 提供的是一块干净的画布，scaffold 要你自己加。

### 5.3 工具是薄封装

pi 的内置工具在 `packages/coding-agent/src/core/tools/`，只有七个：read、bash、edit、write、grep、find、ls，全是文件和 shell 操作。没有 web 搜索、没有网页抓取、没有专用的验证工具。联网能力靠 bash 里跑 curl 或 wget 兜底。第 1 节说的“缺搜索工具影响有限”就是因为多数 ALE CLI 任务的数据已在本地，bash 足够。

### 5.4 上下文管理与会话

pi 有 compaction 机制，在 `packages/agent/src/harness/compaction/`，上下文接近上限时会自动摘要旧消息。会话存储在 `packages/agent/src/harness/session/`，用 jsonl 落盘。这两块属于 harness 做得完整的部分。在 ALE 里我用 `--no-session` 关掉了会话持久化，因为每个任务是独立一次性的。compaction 在长任务里会触发，第 3 节 cfr 的 528 万 token 说明即便有 compaction，无步数护栏时上下文照样能滚很大。

## 6. 三方架构对比：pi、Claude Agent SDK、self_harness_agent

把 pi 放到两个参照物之间看，架构差异就清楚了。一个参照是 Claude Agent SDK，代表“电池全包”的路线。另一个是 `self_harness_agent`（在 `/home/dataset-local/wcy/self_harness_agent`），代表“harness 作为元认知调节器”的研究路线。

### 6.1 三者的定位

pi 的定位是薄而透明的编码 harness。循环、工具、上下文、会话都完整，但 scaffold 极薄，行为决策交给模型。它给你一块干净画布，适合当研究基座，因为它不在模型和任务之间塞太多自己的意图。

Claude Agent SDK 的定位是开箱即用的生产级 agent 框架。它内置的东西 pi 有意不做：子 agent、权限系统、丰富的内置工具、compaction 策略、hook 机制、todo 与 plan mode 这类工作流脚手架。它的 scaffold 厚，目标是让你少写代码就能得到行为稳健的 agent。代价是它的很多行为是框架替模型定的，你要研究“模型自己会怎么做”时，这些内置行为是干扰变量。

self_harness_agent 的定位既不是产品也不是通用框架，是一个研究元认知的干净试验台。它的科学问题写在 README 里：harness 作为元认知调节器，能否把模型的自我觉察和自我校正能力引出来，并通过 on-policy 训练固化进权重，最终让模型不依赖 harness 也能自己纠正自己。它的载体是 sokoban 这类能暴露“失败循环”和“步预算”的小游戏。

### 6.2 循环与预算的对比

pi 的循环无步数上限、无 token 预算，靠模型自停。

self_harness_agent 的循环有硬预算。它的 `agent_loop.py` 有 `max_steps=50`，还有 `ctx_char_budget=40000` 的上下文字符上限和 `keep_recent_turns` 的滚动窗口。它明确管着“最多走多少步、上下文最多多大”。这正是 pi 缺的那层护栏。把第 3 节 cfr 的 135 步放到 self_harness_agent 的框架里，50 步就会被截断，不会滚到 528 万 token。

Claude Agent SDK 通常也有 max turns 一类的配置上限，属于生产框架的标准配置。

### 6.3 scaffold 与干预的对比

这是三者差异最大的地方。

pi 的 scaffold 是静态的。system prompt 一次性给定，之后每一轮不注入任何针对当前状态的引导。模型转圈也好、自我合理化也好，pi 不插话。

self_harness_agent 的 scaffold 是相机而动的。它的 `harness/base.py` 定义了 `StepSignals` 和 `AssistDecision` 两个结构。`StepSignals` 记录关于刚发生的事的纯事实：上一个动作有没有改变状态、当前状态是不是访问过的（转圈信号）、连续多少步没进展、上一次输出多长（啰嗦信号）。`AssistDecision` 是 harness 每一轮的干预决定，可以在当前 user 轮附加一句 hint。

关键约束是这句 hint 只能是事实，不能是建议。base.py 的注释写得很明确：harness 可以引导、暴露、解析、记录、提供工具，但不能替模型选最终动作，不能推荐或排序动作。有一个 leak_audit 会扫描所有注入文本里有没有“最优”“最佳”“推荐”这类词，防止 harness 偷偷给答案。它管这个叫“镜子非地图”：h3 这档只反射关于智能体自己状态和历史的事实，比如“你在原地转圈”“还剩 N 步”，绝不给最优动作。觉察必须落在模型自己的 token 里。

这套设计对应到 ALE 的 cfr 失败，就是一个直接可借的思路。cfr 的问题是模型在可利用度不达标时收工。一个 self_harness 式的 harness 可以在每一轮检查“你报的可利用度是 1.17，目标是 0.05”，把这个事实反射回去，逼模型面对差距继续迭代，而不替它写收敛算法。这是事实反射，不是给解。

Claude Agent SDK 的 scaffold 是厚而通用的，它给的是 plan、todo、子 agent 这类工作流结构，不是针对某个任务的相机干预。它的厚是为了通用好用，不是为了研究模型的元认知边界。

### 6.4 一句话对比

pi 把决策权最大程度交给模型，harness 只提供干净的执行环境。self_harness_agent 保留一层只反射事实、不给答案的相机干预，用来研究并训练模型的自我校正。Claude Agent SDK 用厚 scaffold 把常见工作流固化进框架，换取开箱即用。要做“搭 harness 提高模型能力”的研究，pi 是好的基座，self_harness_agent 是好的方法论参照，Claude Agent SDK 是不该直接拿来当试验台的反例，因为它的内置行为会污染你想观察的模型行为。

## 7. ALE 长程任务需要 harness 发挥什么功能

把两个轨迹和三方对比合起来，能给 ALE 这类长程任务的 harness 定出几个具体功能。这些功能的共同点是补 pi 缺的那层，同时守住 self_harness 的那条红线：给事实和结构，不给答案。

### 7.1 预算与止损

cfr 花 135 步、528 万 token 拿零分，Ising 花 46 步拿满分。长程任务需要 harness 管步数和 token 预算，在预算耗尽前强制收敛或止损。pi 完全没有这层。这是最容易加、收益最直接的一项。self_harness 的 `max_steps` 和 `ctx_char_budget` 是现成参照。

### 7.2 终止判据校正

cfr 的核心失败是模型用“文件写出来了”当完成信号，而真实信号是“可利用度达标”。长程任务的完成往往有可检验的客观条件（数值达标、测试通过、输出契约满足）。harness 可以在每一轮或收尾时，把“当前是否满足客观完成条件”这个事实反射给模型，阻止它在不达标时收工。注意这是反射条件是否满足，不是告诉它怎么满足。

### 7.3 环境事实前置

Ising 花八步试出“该用 /usr/bin/python3 而不是默认 python3”。这类环境事实对整类任务成立，却要每个任务各自试。harness 可以在任务开始时把稳定的环境事实注入 prompt，或提供配好依赖的运行入口，省掉重复试探。ALE 的任务卡本身就带 software 字段和 runtime 入口脚本，harness 可以把这些结构化地喂给模型。

### 7.4 失败循环打断

cfr 在一个 shape bug 上绕了十步，Ising 在环境问题上绕了八步。self_harness 的 `no_progress_steps` 和 `repeat_state` 信号就是为这个设计的。harness 可以检测“连续 N 步没有实质进展”或“在重复同一类失败”，然后反射这个事实，提示模型换思路，而不替它换。

### 7.5 验证器接入

Ising 的成功很大程度靠模型自发写了一个独立验证器。这个行为不是每个任务、每个模型都会有。harness 可以把“产出后先自检”变成结构性要求，或提供通用的验证钩子，让模型在交付前必须过一遍自己的检查。

这五项里，7.1 预算止损和 7.2 终止判据校正对 ALE 的分数影响最直接，因为超时和“做完但没做对”是当前失败的两大来源。7.3 到 7.5 是提高单任务解题质量的辅助。

## 8. 下一步搭 harness 的建议

结合前面的分析，给一条可执行的路线。

第一步，等全量跑完，用 `summarize_pi_cli.py` 拿到 99 个任务的完整分布和失败归因。区分三类失败：超时、做完但零分、进程报错。这决定 harness 先补哪一项。

第二步，先加最省事、收益最直接的预算护栏。在 pi 外面包一层步数和 token 预算，或用 pi 的 `shouldStopAfterTurn` 回调实现。目标是把 cfr 这类失控 rollout 提前止损，把省下的预算留给别的任务。这一步不改模型行为，只防浪费。

第三步，做终止判据校正。针对有客观完成条件的任务，在 harness 里接一个轻量检查，每轮或收尾时把“是否达标”反射给模型。这一步要守住 self_harness 的红线：反射条件满足与否，不给达标方法。这是最可能真正提分的一项，因为它直接打在“做完但没做对”这个最大失败类别上。

第四步，如果要往训练走，参照 self_harness_agent 的方法论。它的目标不是让 harness 永久扶着模型，而是通过 on-policy 训练把自我校正内化进权重，最终去掉 harness 模型也能自己纠错。pi 提供干净的 rollout 采集环境，self_harness 提供“镜子非地图”的干预设计和 AER、STR、SCR 这套元认知指标。两者可以结合：用 pi 在 ALE 上采相机干预的轨迹，用 self_harness 的指标衡量模型的自我觉察和自我校正有没有被引出来。

一个贯穿始终的原则：harness 的功能是给事实、给结构、给预算，不是给答案。ALE 的评分看的是模型自己算对没有，harness 替模型做的越多，越测不出模型真实能力，也越训不出能独立解题的模型。pi 的薄正好适合守这条原则，缺的那层护栏和相机干预，按上面四步逐步补。
