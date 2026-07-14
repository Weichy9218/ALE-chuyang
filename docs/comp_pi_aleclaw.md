# pi 与 ale_claw 对比

两个 agent 都在 `ale_run/agents/` 下，都实现同一份 ALE 部署接口 `BaseAgentDeployer`：`install()` 安装依赖，`launch(prompt)` 跑任务，`parse_artifacts()` 把运行记录翻译成 ATIF 轨迹。相同之处到此为止。pi 是一层约 700 行的薄包装，真正的 agent 逻辑在一个外部 Node CLI 里；ale_claw 是仓库内自带的完整 Python agent 框架，60 多个文件，从 OpenClaw 改写而来。

## 一句话概括

pi 把整个 agent 智能（主循环、工具、提示词、模型调用）交给外部的 `@earendil-works/pi-coding-agent` Node CLI，自己只负责装好、拉起、把它的输出转成轨迹，运行在任务容器内部，只操作本地文件系统，没有图形界面能力。ale_claw 自己实现主循环、工具注册表、记忆、上下文压缩、消息规范化、子 agent 委派，并通过 Cua SDK 控制一台远程桌面虚拟机做计算机操作，直接用 litellm 调模型，支持多模型分工和分场景的思考档位。

## 核心运行模型

| 方面 | pi | ale_claw |
|---|---|---|
| 谁在跑主循环 | 外部进程。pi 的 Node CLI 拥有整个 agent 循环 | 进程内 Python。`OpenClawComputerAgent.run()` 就是循环，在 `launch()` 里驱动 |
| ALE 的角色 | 启动 `pi --mode json`，等待，解析它输出的 NDJSON | 自己搭好记忆、会话、工具、agent，逐步迭代一个异步生成器 |
| 模型客户端 | pi 自带的 Node LLM 客户端，靠 `models.json` 配置 provider | Python 的 litellm，外加一个给 `openrouter/.*` 注册的 `unified_loop` 适配器 |
| 运行基底 | 任务容器的本地文件系统，仅限 Linux。pi 内置的 `read`/`bash`/`edit`/`write`/`grep`/`find`/`ls` 直接操作文件 | 通过 Cua SDK 连一台远程桌面虚拟机（`RemoteDesktopSession`）或 MCP 桥，做完整的图形界面操作 |

## 部署与执行

pi 的 `PiDeployer`（`pi/deployer.py`）默认且只支持 `sandbox` 执行器，跑在任务容器内部，工作目录是 `work_dir`。`install()` 用 npm 全局装 `@earendil-works/pi-coding-agent@0.80.3` 到 `~/.local`，解析出 `pi` 启动脚本，再写一份 `~/.pi/agent/models.json`（权限 600）描述一个 OpenAI 兼容 provider。`launch()` 拼好命令行参数，用 `subprocess.Popen` 启动，关键点是 `stdin=DEVNULL`，因为 pi 在 `--mode json` 下会阻塞等 stdin。它把 stdout 流式写进 `transcript.jsonl`，stderr 写进 `stderr.log`，记下 `pi.pid`，每 2 秒轮询一次进程状态；遇到墙钟预算耗尽的 `CancelledError` 时先 terminate 再 kill，给一段宽限期。环境处理上会剥掉代理变量，设 `PI_OFFLINE`、`PI_TELEMETRY=0` 等。

ale_claw 的 `AleClawDeployer`（`ale_claw/deployer.py`）默认 `local` 执行器，支持 `local` 和 `docker`，跑在宿主机或容器里，再通过 RPC/MCP 连到评测虚拟机。`install()` 不起子进程，只做导入自检并断言 `OPENROUTER_API_KEY`/`ANTHROPIC_API_KEY`/`OPENAI_API_KEY` 至少有一个在环境里，然后建工作目录。`launch()` 是一段十步左右的编排：开远程桌面会话，按需拉起 MCP 桥，搭好记忆库、会话管理、子 agent 注册表，解析模型和上下文窗口，构造思考配置，预建计算机操作句柄，调 `build_tools(...)`，拼系统提示词，构造 agent，按需回放历史，最后用一个 `AsyncExitStack` 管理 MCP 的关闭，驱动异步生成器主循环。它没有子进程要回收，取消信号直接传导。

## 主循环与结束条件

pi 这边不透明。何时结束、如何重试、如何分派工具，都在 Node CLI 内部，ALE 只看到事件流。

ale_claw 的 `OpenClawComputerAgent.run`（`agent_loop.py`，约 1100 行）是手写的 `while True:` 循环，包含这些机制：靠 DONE 信号结束（`has_done_signal`），而不是 Cua 默认的「助手不再发工具调用就停」，外层再加 `max_steps` 上限；反应式加主动式的上下文压缩（`_compact_in_place`）；调 API 前的记忆刷写（`_maybe_flush_memory`）；子 agent 完成结果的排空（`_drain_completions`）；对流中途被 provider 截断的工具调用做修补（`_sanitize_truncated_function_calls`）；在 OpenRouter/Vertex 上避免助手尾部纯文本导致路由错误的补白（`_maybe_nudge_bare_text`）。截图默认关闭，只有显式的 `screenshot` 动作才回传图像。

## 工具集

pi 依赖 pi 自带的内置工具：`read`、`bash`、`edit`、`write`、`grep`、`find`、`ls`。没有图形界面工具，没有联网，没有视觉，没有记忆，没有委派。配置只能通过 `--exclude-tools` 做减法。

ale_claw 的 `build_tools`（`tools/tools.py`）给出一套带类型的工具面：`computer`（图形界面）、`analyze_image`（视觉模型看图）、`read`/`write`/`edit`（多后端文件系统，通过 `FilesystemRegistry` 支持 `target='vm'|'host'`）、`exec`（shell）、`web_search`/`web_fetch`、`memory_search`/`memory_get`，以及委派工具 `delegate_general`/`delegate_gui`/`subagents`。`web_search` 默认关闭，需要 `BRAVE_API_KEY`。

## 提示词

pi 不做提示词组装，任务提示直接作为命令行最后一个位置参数传进去，并且传 `--no-context-files`，避免目录里散落的 `AGENTS.md`/`CLAUDE.md` 混进 pi 的系统提示，保证运行可复现。

ale_claw 有一个模块化的 `PromptBuilder().build(...)`（`prompt.py`），把工具说明和上下文文件组合进系统提示，某个工具被禁用时它对应的说明文字也跟着消失。它注入自带的 `harness/AGENTS.md`（记忆规则、DONE 约定、通用行为）和 `TASK_MEMORY.md` 引导，压缩后还会重新注入上下文文件。引导有字符上限（单文件 12k，总量 60k）。

## 模型交互与配置

pi 的 `PiConfig`（`pi/config.py`）默认模型 `qwen3.5-397b-a17b`，provider `apihy`，`base_url` 指向 `https://zgc.apihy.com/v1`，API key 随序列化配置一起走，最终写进 `models.json`。还有 `api` 类型（`openai-completions` 或 `openai-responses`）、`reasoning` 开关、`thinking` 档位、`context_window`、`max_tokens`、`disabled_tools`、`clear_proxy` 等。没有墙钟超时的配置项。

ale_claw 的 `AleClawConfig`（`ale_claw/config.py`）默认模型 `openrouter/anthropic/claude-sonnet-4.6`（litellm 格式），支持多个模型角色：`summary_model`、`gui_model`、`auxiliary_model`。有传输层开关 `substrate_transport`（`mcp`/`session`）和 `gui_transport`。思考档位分五处独立配置：`thinking_level`、`flush_thinking_level`、`compaction_thinking_level`、`vision_thinking_level`、`gui_thinking_level`。还有 `image_retention_mode`、`max_history_turns`，以及互斥的 `disable_main_computer`/`disable_delegate_gui`（在 `__post_init__` 里校验）。API key 一律从 shell 环境读，不进配置。

## 轨迹解析

pi 的 `parse_artifacts` 读 `transcript.jsonl` 这份 NDJSON，以 pi 的 `message_end` 事件为准，把 `thinking`/`text`/`toolCall` 内容块和 `usage`（输入、输出、缓存读取、成本）映射成 ATIF 步骤，并刻意跳过 `tool_execution_*` 事件避免重复计数。

ale_claw 交给仓库内专门的翻译器 `parse_transcripts_into`（`transcript_to_trajectory.py`），读的是它自己的会话管理写出的 `openclaw_sessions/<task_id>/transcript.jsonl`。

## 依赖与打包

pi 只用 Python 标准库，真正的依赖是运行时用 npm 装的那个外部包，没有 `pyproject.toml`。

ale_claw 有 `pyproject.toml`（`ale-ale-claw`），依赖 `cua-agent[qwen]==0.7.38`、`cua-computer`、`cua-core`、`litellm>=1.80`、`Pillow`、`soundfile`、`torchvision`，要求 Python 3.12 到 3.13。

## 各自独有的部分

只有 ale_claw 有的：磁盘持久化的记忆子系统（`memory/`）加刷写策略；上下文压缩流水线（`context/`）加消息规范化与清洗层（`canonical/`）；子 agent 委派（通用加图形界面，含注册表和异步完成队列）；基于 Cua 虚拟机的图形界面操作、截图、看图、图像保留适配；用于把文件/shell/图形工具路由到 MCP 的桥运行时；多模型分工加分调用点的思考配置；自带的 `unified_loop` 模型适配器、缓存策略、轨迹保存适配器；README、AGENTS.md、AUDIT.md 等文档。

只有 pi 有的：跑在 sandbox 容器内部而不是驱动远程虚拟机；npm/Node 安装路径和 `models.json` 的 provider 引导；为穿过容器 NAT 联网而剥代理变量的逻辑；子进程生命周期管理（`stdin=DEVNULL` 这个坑、pid 文件、terminate/kill 宽限）；API key 可以随序列化配置传递。

## 该用哪个

任务只需要在 Linux 容器里读写文件、跑命令，且想复用一个成熟的第三方编码 CLI，选 pi，接入成本低。任务需要图形界面操作、长时程、记忆、上下文压缩、子 agent 协作，或要在多模型之间精细分工，选 ale_claw。

要在文档里引用的关键文件：`pi/deployer.py`、`pi/config.py`；`ale_claw/deployer.py`、`ale_claw/config.py`、`ale_claw/README.md`、`ale_claw/harness/agent_loop.py`、`ale_claw/harness/tools/tools.py`、`ale_claw/harness/prompt.py`、`ale_claw/harness/AGENTS.md`、`ale_claw/pyproject.toml`。
