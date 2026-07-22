# ALE Harness 系统设计

当前系统由实验控制面、ALE 生命周期、ALE-Claw writer、可选 Prep、可选 writer skills、可选 Verifier 和任务原 evaluator 组成。各模块有独立职责；最终 `[0,1]` 分数只由任务原 evaluator 在 hidden reference staging 后产生。

## 总体数据流

```text
harness/run/settings*.yaml
  -> launch.py 生成 arm agent config 和 experiment config
  -> ale_run orchestration 为每个 task/arm 创建 sandbox
  -> stage public task prompt + input/ + software/
  -> AleClawDeployer.launch()
       -> optional verifier candidate build (builder + relocation + one mechanical
          locate-repair round) and task-specific prep independently in parallel
       -> after prep: optional verifier fixture preflight and suite freeze
          (mechanical, no LLM; environment gates measured in the post-prep
          sandbox, before any prep artifact is staged; all checks advisory)
       -> atomically stage supplemental task_prep/PREP_REPORT.md + optional artifacts/
       -> inject a prep digest (runtime state, self-check command, item counts,
          read-the-report instruction) into the initial writer prompt
       -> mechanical contract cross-check note (prep_verifier arm only)
       -> optional writer skills in MemoryStore
       -> ALE-Claw writer produces output/
            (optionally running the frozen suite on its own draft via `verify`)
       -> optional verifier snapshot + Landlock/seccomp executor
       -> optional writer review and bounded repair
  -> gather origin_log and pull output/
  -> stage hidden reference
  -> task-native evaluator
  -> run.json + eval_result.json + trajectory.json
  -> analyze_factorial.py 生成 scores、behavior、prep 和 verifier 审计表
```

## 模块职责

| 模块 | 输入 | 输出 | 不能承担的职责 |
|---|---|---|---|
| `harness/run/launch.py` | settings、arm 列表、task 清单 | 生成的 agent 和 experiment YAML | 解题、判分 |
| ALE lifecycle | task card、sandbox、agent config | 完整 unit 运行、artifact、trajectory、eval | 修改任务 contract |
| ALE-Claw writer | 公开题面、工具、可选 Prep/skills | `output/` deliverable | 访问 solve 后才 staging 的 hidden reference |
| Skills | writer memory 中的可选方法文本或能力 | writer 自行调用的方法 | 独立验证、隐藏评分 |
| Task-Specific Prep | 公开题面、`input/`、`software/`、runtime、web 来源 | 可用的运行时状态、合同清单、可复查的事实与工具 | 生成最终答案、检查候选 output |
| Verifier builder | 公开题面和公开文件 | 候选脚本、source set、执行方式和 fixtures | 查看 writer 产物或本轮 Prep 后增加检查 |
| Verifier auditor（v18 已删除） | — | —（三项语义判定只为硬权威服务，零权威下无许可可发） | — |
| Verifier executor | frozen suite、公开文件、artifact snapshot | 完整执行记录、verdict、可选分析和 coverage | 临时决定检查方法、修改产物、替代原 evaluator |
| Task evaluator | writer output、solve 后 staging 的 reference | `[0,1]` score 和分项 | 向 writer 提供 solve 时反馈 |
| Analyzer | 多个 run artifact | 配对分数、成本、adoption 和 verifier audit | 修复运行结果 |

## 实验控制面

入口是 [`harness/run/launch.py`](../../harness/run/launch.py)。`ARMS` 在 [`launch.py:31`](../../harness/run/launch.py#L31) 固定为：

| Arm | Skills | Prep | Verifier |
|---|---:|---:|---:|
| base | off | off | off |
| prep | off | on | off |
| verifier | off | off | on |
| prep_verifier | off | on | on |

Skills 在代码中仍兼容，但当前四臂故意不加载。skills v2 已显示当前两个通用 skill 没有正向净效应。

`launch.py` 读取一个浅层 settings YAML，为每个 arm 调用 [`presets.py:39`](../../harness/run/presets.py#L39) 生成显式配置。每个 preset 都写出 `task_specific_prep`、Prep step 上限、`verifier`、Verifier step 上限和 repair 上限，避免默认值变化污染历史实验。

当前 Verifier 配置为：

```yaml
arms: [base, prep, verifier, prep_verifier]

prep:
  max_steps: 15

verifier:
  max_steps: 30
  max_repairs: 1
  writer_checks: 2

run:
  tasks: docs/harness/results/latest/tasks.txt
  concurrency: 3
  api_endpoints: []
```

`api_endpoints: []` 表示四臂使用同一默认 endpoint。旧 `verifier_compare` 曾按 arm 轮转 endpoint；`launch.py` 现在会对这种配置打印混杂警告，见 [`launch.py:202`](../../harness/run/launch.py#L202)。

## ALE 生命周期

每个 task/arm 是一个 `RunUnit`。[`run_one_unit()`](../../ale_run/orchestration/lifecycle.py#L135) 负责：

1. 解析 agent 和 config，创建 `RunWriter`。
2. 获取 concurrency semaphore，加载 task card，选择 environment provider。
3. provision sandbox，stage 公开 task data，创建 executor。
4. 调用 deployer `install()` 和 `launch(prompt)`。
5. 停止增量日志拉取，gather 完整 origin log。
6. 将 VM `output/` 拉到 host run directory。
7. staging hidden reference。
8. 调用 task-native evaluator。
9. 生成 trajectory、run status、score 和 error metadata。

Output 在 hidden reference staging 前已经完成并拉取，见 [`lifecycle.py:443`](../../ale_run/orchestration/lifecycle.py#L443)；reference 从 [`lifecycle.py:449`](../../ale_run/orchestration/lifecycle.py#L449) 才进入环境。Agent status 为 failed 时跳过 evaluator并保留 `score=null`，避免基础设施错误被误记为 0，见 [`lifecycle.py:471`](../../ale_run/orchestration/lifecycle.py#L471)。

PE screening memo 的 404 因此在 v10 主表中保持 failed/null，没有当作任务 0 分。

## ALE-Claw Writer

[`AleClawDeployer.launch()`](../../ale_run/agents/ale_claw/deployer.py#L198) 建立 RemoteDesktopSession、MCP 工具桥、MemoryStore、SessionManager、SubagentRegistry、模型配置和 OpenClaw agent。

当前 headless 实验关闭 web search、computer 和 image analysis；主 agent 使用 read、write、edit、exec 等非 GUI 工具。`workspace_root=None`，见 [`deployer.py:303`](../../ale_run/agents/ale_claw/deployer.py#L303)，因此主 agent 对 VM 路径是 permissive access。

Writer 的系统 prompt 包含 ALE-Claw `AGENTS.md` 和 MemoryStore bootstrap。它按工具调用迭代，收到 DONE 或达到 step budget 后结束。SessionManager 保存 transcript；`parse_artifacts()` 将其转为统一 trajectory。

## Skills

Skills 由 [`presets.py:25`](../../harness/run/presets.py#L25) 从 `harness/skills/*/SKILL.md` 读取。只有生成 preset 时 `with_skills=true` 才会把正文放入 `skill_sources`。

Deployer 将每个 skill 写为 `method-<name>.md`，并在 `TASK_MEMORY.md` 放名称、description 和加载路径，见 [`deployer.py:102`](../../ale_run/agents/ale_claw/deployer.py#L102)。Writer 需要调用 `memory_get` 才读取完整正文。

Prep 和 Verifier 都使用 `memory_store=None`，不接收这些 skills。Skills 只影响 writer 的方法选择；它们没有 fresh context、artifact snapshot 或独立 verdict，不能称为 verifier。

当前两项为 `deliverable-contract` 和 `evidence-audit`。25 题 skills v2 中 50/50 个 enabled unit 加载成功，skills 相对 base 为 `-0.0161`。当前四臂全部 `with_skills=false`。

## Task-Specific Prep

Prep 源码为 [`task_prep.py`](../../ale_run/agents/ale_claw/task_prep.py)，详细说明见 [PREP.md](PREP.md)。它在 writer 前、在 writer 的同一沙箱里运行，结果不缓存。

v21 的 Fresh Prep agent 做三件事：把题目需要的运行时跑通并把状态留在沙箱里；从题面和
`input/` 编译交付物合同清单，机械条目多时同时交付一个可运行的 self-check 脚本并注册在
`self_check` 字段（digest 给 writer 一条确切命令）。self-check 只查结构覆盖——存在性、
字段、拼写、行数、编码、跨文件一致——不硬编码期望取值、不判对错，判定是 Verifier 的角色；
第三件事是补上题面缺失的精确外部事实或可复用工具。所有输出部分都可以为空。结构化合同条目
保留在 `TaskPrepResult.contract`，供 prep_verifier 臂做机械合同对账：harness 按引用的公开
文件对齐 prep 清单与冻结测试的 sources，双向差集写入 `contract_crosscheck.json` 并注入
writer 初始 prompt（只比文件覆盖，不判对错，不改权限）。
上限是合同清单 24 条、findings 6 条、artifact 4 个各 64 KB；报告作为文件交付，48,000 字符
是安全上限，超限截断时文件头部写明。代码只做机械校验：类型、长度、条数、artifact 路径与
后缀；不合格的条目逐条丢弃并记入 `dropped`，不整包拒绝。v18 的 `output/` 字符串检验已在
v19 删除：prep 运行期从不执行针对候选产物的检查（彼时 `output/` 尚不存在），但它交付的
检查说明和工具应当引用交付物路径。工具为 `read`、`exec`、`web_search`、`web_fetch`，搜索
不限定用途。
完整 bundle 写到 VM 的 `task_prep/`；writer 初始 prompt 只注入 digest（运行时状态与已验证
命令、self-check 命令、条目数、"先读 `task_prep/PREP_REPORT.md`"），不再内联全文。题面和
`/input` 始终高于 bundle；staging 失败时 digest 退化为只含运行时状态，不宣传打不开的文件。

Prep 状态为 `completed`、`empty` 或 `failed`。后两种都 fail-open，writer 继续执行。报告不写入 `output/`，避免污染任务 deliverable。

## Independent Verifier

Verifier 源码为 [`verifier.py`](../../ale_run/agents/ale_claw/verifier.py)，详细说明见 [VERIFIER.md](VERIFIER.md)。构建分两阶段。阶段 A 与 Prep 并发、互不读取输出：Builder 生成测试脚本、结构化 source set 和合法/错误 fixtures；lint 逐条隔离，单条 schema 违规丢该条记 `dropped`，只有顶层结构损坏才整包失败；Harness 机械定位每个 source 并保存 hash（quote 在文件中唯一时，错误的行号坐标被机械修正而不判死），仍定位失败的 source 触发一轮机械修复（新 builder 会话只收到"quote 未找到"类证据，修复产物重新 lint 和定位，定位失败数严格减少且 lint 丢弃不增加才采用）。阶段 B 在 Prep 完成后、Prep 产物 staging 之前执行，纯机械零 LLM：Executor 在隔离环境预检 fixtures（环境判定因此发生在 writer 将要接手的同一沙箱里），随后直接冻结。v18 为零权威协议：`blocking` 冻结时恒为 false（builder 的主张留档为 `requested_blocking`），每条结果都是 advisory 测量；Auditor 与硬权限 gate 一并删除。builder 生成检查时锚定任务契约——题面点名的文件、字段、标识符逐字进 checker，check id 以契约义务命名。

Writer 完成后，代码复制只读 artifact snapshot。Executor 不使用 LLM 临时设计检查，只在 Landlock/seccomp 隔离进程中运行冻结命令。每项测试连续运行两次；两次规范化结果不同则返回 `error`。Landlock 只允许读取系统 runtime、公开 input/software、snapshot 和 checks，只允许写独立 scratch；seccomp 禁止网络 syscall。Fixtures、Writer 原 output、Prep、hidden reference 和官方 evaluator 不可访问。

Verifier 的状态流为：

```text
disabled
  or builder error
  or frozen suite (all advisory)
       (during solve: writer may run it on its own draft via `verify`,
        default 2 runs, same isolation, standard unchanged)
       -> measured / error / unverifiable   (coverage description, no verdict)
       -> review items -> writer reviews evidence, decides, may repair
               -> new snapshot
               -> rerun the complete frozen suite
```

`max_repairs` 默认为 1，允许范围为 1 至 3。advisory review item 会反馈给 Writer。反馈先给 source locator、原文、hash 和解释，再给命令、observed、expected、evidence，不包含 `repair_hint`。Writer 先复核 source 并复现测试，再自行决定改不改；用公开反证 `VERIFIER_DISPUTE` 可静音单条；每轮都重跑完整冻结测试包。主运行文本与复核轮的 dispute 同协议解析（dispute 门控方案因实测零 dispute 被否决，见 VERIFIER.md）。

writer 预提交自检：`verifier_writer_checks`（默认 2，0 关闭）为 Writer 提供 `verify`
工具，对当前 `output/` 快照运行同一冻结测试包并返回同一份四类报告，措辞为 pre-submission。
标准、隔离、hash 复验都与 DONE 后一致；预运行不消耗复核轮数。信号产生率由三个机制保证：
quote 自动重定位、定位失败一轮机械修复、ambiguous 来源以 advisory 运行。详见
[VERIFIER.md](VERIFIER.md) 的"与 Writer 的两条通道"和"生成与冻结"。

## Artifact 与日志

每个 unit 的 host run directory 保存标准 ALE artifact：

- `run.json`：agent、task、status、usage、score 和 evaluator 状态；
- `eval_result.json`：任务原 evaluator 输出；
- `trajectory.json`：统一 tool/action/observation 轨迹；
- `output/`：从 VM 拉取的 writer deliverable；
- `origin_log/`：deployer 产生的原始 session 与附加记录。

ALE-Claw 的 origin log 还包括：

- `task_prep.md`、`task_prep_bundle/`、`task_prep_meta.json`、`task-prep-runs.jsonl`；
- `verifier_suite.json`、`verifier_round_<n>.json`、`verifier_meta.json`、`verifier-runs.jsonl`；
- main transcript、system prompt report、memory 和 subagent registry。

[`analyze_factorial.py`](../../harness/run/analyze_factorial.py) 选择每个 task/arm 最新的 `run.json`，生成 `scores.csv`、`behavior.csv`、Prep adoption、`verifier_checks.csv`、`verifier_repairs.csv` 和 `summary.json`。Repair 表记录前后 snapshot hash、suite hash、failure 集和 blocking authority 变化。当前机器表位于 [results/latest](results/latest/)。

## 信任边界

| 边界 | 当前保证 | 当前缺口 |
|---|---|---|
| Hidden reference | solve 和 verifier 完成后才 staging | 依赖 lifecycle 顺序，需持续回归测试 |
| Prep context | fresh session、无 skills、无 writer history；报告不在 input/ | 与 writer 共享 VM，prompt 只读要求没有独立挂载 |
| Verifier builder | solve 前生成脚本、结构化 source 和 fixtures | 候选质量依赖模型，不能直接获得 blocking 权限 |
| Verifier source gate | quote 机械定位、source hash（零权威后无语义审查） | 定位失败的检查沉默为 coverage gap，覆盖率依赖 builder 质量 |
| Verifier checker gate | 合法/错误 fixture、双次运行 | 自动 fixtures 不能穷举 Checker 控制流；无审计后 checker-要求错位只能靠 writer 复核 |
| Verifier executor | Landlock 文件 allowlist、seccomp 无网络、独立 scratch、双次确定性运行 | 依赖 Linux Landlock ABI 和 libseccomp |
| Verifier snapshot | symlink 拒绝、去写权限、tree hash | 快照复制和 mount 启动失败时只能返回 error |
| Writer 预提交自检 | 同一冻结包，suite/script/source hash 每次运行复验，快照只读，次数上限 | 冻结测试内容在提交前对 writer 可见（有意变化），需监控对未覆盖要求的挤出效应 |
| Original output | 不挂载到 Verifier namespace | Writer repair 仍按反馈自行修改原 output |
| Evaluator | task-native score，agent failed 时不执行 | 某些任务 evaluator 依赖外部模型 endpoint |
| Experiment arm | v10 同 endpoint、显式开关 | 每格 k=1，writer 方差仍大 |

Builder 的 fresh context 和并发顺序防止读取 Writer 历史或本轮 Prep。Executor 的 Landlock allowlist 和 seccomp 提供进程隔离；它不会依赖 prompt 要求脚本保持只读。隔离启动失败时不降级为普通进程。

## 失败策略

- Prep builder、报告解析和 staging 失败时，writer 继续。
- Verifier builder 或测试包冻结失败时，不运行测试；`verify` 工具报告不可用。
- builder 机械修复轮失败或没有减少定位失败时，保留原候选套件。
- 合同对账失败时只记日志，不注入任何文本，writer 照常开始。
- `verify` 工具单次调用崩溃（快照或 staging 异常）时向 writer 返回错误文本，不计入次数；
  跑完但 overall 为 error 的运行计入次数。两者都不影响求解和 DONE 后复核。
- Snapshot、隔离环境或测试进程 error 写入 verifier metadata，不归因于 Writer。
- Repair 只接收 blocking failures；达到上限时停止。每轮都运行完整测试包。
- Agent 基础设施失败时，lifecycle 跳过 evaluator并保留 null score。
- Evaluator failure 与 artifact 0 分分开记录。

这组策略保护基线可运行性，也意味着启用 Prep 或 Verifier 不会自动把 unit 判为失败。实验分析必须同时读取 agent status、eval status、Prep status 和 Verifier status。

## 当前生产与实验状态

| 功能 | 默认 | 当前证据 |
|---|---:|---|
| ALE-Claw writer | on | 基线系统 |
| writer skills | off | skills v2 相对 base `-0.0161` |
| task-specific Prep v21 | on | v20 把 self-check 升为一等字段；v21 改文件式消费 + digest 交接、self-check 限定结构覆盖；v20 六题配对正在 pgl 运行 |
| public Verifier v18 | off | v16 六题 6/6 构建 error（4/6 单 locator 整包 lint 死）；v17 lint 逐条隔离、预检后移；v18 零权威——删 Auditor、blocking 恒 false、契约名聚焦、overall 改覆盖描述；六题 smoke 待跑 |
| contract cross-check | prep_verifier 臂自动 | 纯机械文件覆盖对账，零 LLM 成本；分歧率待六题 canary 读数 |
| writer repair | Verifier 开启时 1 轮 | Writer 先判断反馈；预提交自检不消耗复核轮数；仍需复验收益和误修率 |

下一阶段需要先在 pgl 的预定义任务子集上做机制 canary，再做 `k>=3` 复验。需要测量 source/auditor gate 通过率、脚本生成成功率、false failure、Writer dispute、修复收益和回归率。现有两个通用 skills 不进入该实验轴。
