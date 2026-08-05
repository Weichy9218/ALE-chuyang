# ALE Harness 系统设计

系统由实验控制面、ALE 生命周期、ALE-Claw writer、可选 Prep、可选 writer skills、可选 Verifier
和任务原 evaluator 组成。各模块职责互不重叠；最终 `[0,1]` 分数只由任务原 evaluator 在 hidden
reference staging 之后产生。

组件设计见 [PREP.md](PREP.md) 与 [VERIFIER.md](VERIFIER.md)，历史教训见 [FABLE.md](FABLE.md)。

## 一次重要的职责重划

契约与 schema 一致性检查过去由两方各做一份：Prep 编译合同清单并交付自检脚本，Verifier 的
builder 独立编译冻结测试。实测证明这是同一张清单编译了两遍（agora 题 Verifier 6 条对 Prep
18 条逐条对应，sec_10k 题 4 条对 4 个区域对应），而且两边把同一批语义维度同时标成不可验证，
分数正好长在那些维度上。

现在：**契约一致性整体归 Verifier，Prep 不再编译任何清单、不再生成自检脚本。** Prep 的职责
收缩为跑通运行时、亲自跑一遍核心机械步骤并报告断点、补题面缺失的外部事实。

同时 Verifier 内部按可推导性分层：题目自带机器可读规格的部分由代码机械生成校验器（零 LLM），
只有散文里的义务才交给 builder 编译。

## 总体数据流

```text
harness/run/settings*.yaml
  -> launch.py 生成 arm agent config 和 experiment config
  -> ale_run orchestration 为每个 task/arm 创建 sandbox
  -> stage public task prompt + input/ + software/
  -> AleClawDeployer.launch()
       -> 并发：Prep（跑通运行时、试跑核心步骤）
                Verifier 阶段 A（第一层机械校验器 + 第二层 builder 编译、定位、一轮机械修复）
       -> Prep 完成后：Verifier 阶段 B（fixture 预检 + 冻结，纯机械零 LLM，
          环境判定发生在 writer 将要接手的同一沙箱里，且在 Prep 产物 staging 之前）
       -> stage task_prep/PREP_REPORT.md（artifacts 为空也必须落地）
       -> writer 首轮 prompt 注入 prep digest（运行时状态、断点、findings、读报告指令）
       -> ALE-Claw writer 产出 output/
            （全程可用 verify 对自己的草稿跑冻结包）
       -> Verifier 快照 + Landlock/seccomp 隔离执行
       -> 可选一轮 writer 复核
  -> gather origin_log 并拉取 output/
  -> stage hidden reference
  -> 任务原 evaluator
  -> run.json + eval_result.json + trajectory.json
  -> 分析脚本生成 scores、behavior、prep 与 verifier 审计表
```

## 模块职责

| 模块 | 输入 | 输出 | 不能承担的职责 |
|---|---|---|---|
| `harness/run/launch.py` | settings、arm 列表、task 清单 | 生成的 agent 与 experiment YAML | 解题、判分 |
| ALE lifecycle | task card、sandbox、agent config | 完整 unit 运行、artifact、trajectory、eval | 修改任务 contract |
| ALE-Claw writer | 公开题面、工具、可选 Prep/Verifier | `output/` deliverable | 访问 solve 后才 staging 的 hidden reference |
| Skills | writer memory 中的可选方法文本 | writer 自行调用的方法 | 独立验证、隐藏评分 |
| Prep | 公开题面、`input/`、`software/`、runtime、web | 运行时状态、断点报告、findings | 编译契约清单、生成自检、选定取值、检查候选 output |
| Verifier 第一层 | 题目自带的机器可读规格 | 机械生成的校验器（零 LLM） | 处理只存在于散文里的义务 |
| Verifier 第二层 builder | 公开题面与公开文件 | 候选脚本、source set、fixtures | 查看 writer 产物或本轮 Prep 产出 |
| Verifier executor | frozen suite、公开文件、artifact snapshot | 执行记录、分类报告 | 临时决定检查方法、修改产物、替代原 evaluator |
| Task evaluator | writer output、solve 后 staging 的 reference | `[0,1]` score 与分项 | 向 writer 提供 solve 时反馈 |
| Analyzer | 多个 run artifact | 配对分数、成本、adoption、verifier 审计 | 修复运行结果 |

## 实验控制面

入口是 `harness/run/launch.py`。arm 定义：

| Arm | Prep | Verifier 第一层 | Verifier 第二层 | 用途 |
|---|---:|---:|---:|---|
| base | off | off | off | 基线 |
| prep | on | off | off | Prep 单独效应 |
| verifier | off | on | on | Verifier 完整效应 |
| verifier_l1 | off | on | off | 分离出 LLM 编译层的边际价值 |
| prep_verifier | on | on | on | 合并臂 |
| self_review_hint | off | off | off | 安慰剂：只加一句提交前自查提示 |

`verifier_l1` 取代了旧的 `prep_nosc`。它回答一个明确的问题：第二层 builder 那部分 token 到底
买到了什么？第一层是零成本的，如果两臂读数接近，压缩空间就很大。

`self_review_hint` 是 Verifier 的安慰剂对照，用来区分"测量内容有价值"和"writer 知道会被检查
所以自己复查了"。实测读数 −0.0078，说明 Verifier 那点效应不是纯粹的预期效应。

**对照臂的硬要求：每个 arm 必须断言自己只改了一件事，并在启动时验证操纵真的生效。** 这条
现在由 launch.py 机制化：写完每个 arm 的 preset 后逐行回读，与 ARMS 声明的开关矩阵和共享
预算逐项比对，任何不符直接拒绝启动；启动输出打印验证过的臂矩阵，且打印值与生成值取自同一份
默认表，杜绝"打印一套、运行另一套"。旧的
`prep_nosc` 因为撤掉自检时连带撤掉了唯一 artifact，触发 staging bug 导致报告一起丢，实际测的
是"prep 完全没送到"，污染了一整轮结论。

所有 arm 共用同一 endpoint。按 arm 轮转 endpoint 会把网关差异混进 arm 效应；launch.py 对
"多 endpoint + 多 arm"默认拒绝启动，确认不做因果比较时须显式传 `--allow-endpoint-rotation`。

## Writer 对辅助组件的消费定义

两个组件对 writer 的交付方式同构，各恰好两条通道：一条程序性通道（prep 是沙箱状态，
verifier 是 `verify` 工具），一条文本通道（prep 是首轮 digest 加 `task_prep/PREP_REPORT.md`，
verifier 是逐条原始结果报告）。消费读数对两者同一套定义，全部与 base 臂对照：**到达**
（writer 是否触达通道：读了报告、调了 verify）与**转化**（触达之后行为或 output 是否变化：
早期回合工具分布、调用后快照差异）。分数不做迭代依据；0 分题上强评分会掩盖系统层面的改变，
行为分布不会。各组件读数细目见 [PREP.md](PREP.md) 与 [VERIFIER.md](VERIFIER.md) 末节。

## ALE 生命周期

每个 task/arm 是一个 `RunUnit`，`run_one_unit()` 负责：解析 agent 与 config；获取并发信号量、
加载 task card、选择 environment provider；provision sandbox、stage 公开 task data、创建
executor；调用 deployer 的 `install()` 与 `launch(prompt)`；停止增量日志拉取并 gather 完整
origin log；把 VM 的 `output/` 拉到 host；staging hidden reference；调用任务原 evaluator；生成
trajectory、run status、score 与 error metadata。

Output 在 hidden reference staging 之前已经完成并拉取，reference 之后才进入环境。Agent status
为 failed 时跳过 evaluator 并保留 `score=null`，避免基础设施错误被误记为 0 分。

## ALE-Claw Writer

`AleClawDeployer.launch()` 建立 RemoteDesktopSession、MCP 工具桥、MemoryStore、SessionManager、
SubagentRegistry、模型配置与 OpenClaw agent。当前 headless 实验关闭 web search、computer 与
image analysis；主 agent 使用 read、write、edit、exec 等非 GUI 工具。

Writer 的系统 prompt 包含 ALE-Claw `AGENTS.md` 与 MemoryStore bootstrap。它按工具调用迭代，
收到 DONE 或达到 step budget 后结束。

## Prep

源码 `task_prep.py`，设计见 [PREP.md](PREP.md)。在 writer 之前、同一沙箱内运行，结果不缓存。

交付两条通道：沙箱运行时状态直接生效；报告文件写到 VM 的 `task_prep/PREP_REPORT.md`，writer
首轮 prompt 只注入 digest。题面与 `/input` 的权威永远高于 bundle。

Prep 状态为 `completed`、`empty` 或 `failed`，后两种都 fail-open。报告不写入 `output/`，避免
污染任务 deliverable。

**Prep 不以端到端分数论成败**，改用报告到达与早期回合工具分布两条核心读数（与 base 臂
对照），环境到达率与跨臂断点判别作辅助。

## Verifier

源码 `verifier.py`，设计见 [VERIFIER.md](VERIFIER.md)。

第一层从题目自带的机器可读规格机械生成校验器，零 LLM。第二层由 builder 在 fresh
context 中编译散文义务：builder prompt 内列出第一层已覆盖的义务，check id 碰撞时 parser 胜出，
builder 失败时 suite 回退为纯机械层。lint 逐条隔离（条目层与信封层都要兜底），来源机械定位并
哈希，定位失败触发一轮机械修复。阶段 B 在 Prep 完成后、Prep 产物 staging 之前执行 fixture
预检与冻结。

零权威：`blocking` 冻结时恒为 false，装载时 `lint_frozen_suite` 拒绝任何 blocking 检查，
`overall` 只描述覆盖。writer 全程持有 `verify`（无稀缺配额，只有防失控的安全上限）；DONE 后
最多一轮复核。自动 repair 循环不开，修复权只在 writer 手上。报告逐条给出检查的原始结果，
不替 writer 分类判断。

**任何一次检查运行都不得以"全部通过"结尾**，终局段从本次实际执行的检查推导未覆盖面。

## Artifact 与日志

每个 unit 的 host run directory 保存：`run.json`（agent、task、status、usage、score）、
`eval_result.json`、`trajectory.json`、`output/`、`origin_log/`。

ALE-Claw 的 origin log 还包括 `task_prep.md`、`task_prep_bundle/`、`task_prep_meta.json`、
`verifier_suite.json`、`verifier_round_<n>.json`、`verifier_meta.json`、main transcript、system
prompt report、memory 与 subagent registry。

`task_prep_meta.json` 与 `verifier_meta.json` 各记录一个 `protocol_digest`（prompt 与 schema
的内容哈希加 git commit）。**不使用手工递增的版本号**：版本号会随改动膨胀且无法反查真实内容。

## 信任边界

| 边界 | 当前保证 | 当前缺口 |
|---|---|---|
| Hidden reference | solve 与 verifier 完成后才 staging | 依赖 lifecycle 顺序，需持续回归测试 |
| Prep context | fresh session、无 skills、无 writer history | 与 writer 共享 VM，prompt 只读要求没有独立挂载 |
| Verifier 第一层 | 由规格机械生成，无 LLM 参与 | 只能覆盖题目真的给了规格的部分 |
| Verifier 第二层 builder | solve 前生成，fresh context，不读 Prep | 候选质量依赖模型，无 blocking 权限 |
| Verifier source gate | quote 机械定位、source hash | 定位失败的检查沉默为 coverage gap |
| Verifier checker gate | 合法/错误 fixture、双次运行 | 自动 fixture 不能穷举控制流 |
| Verifier executor | Landlock allowlist、seccomp 无网络、独立 scratch、双次运行 | 依赖 Linux Landlock ABI 与 libseccomp |
| Verifier snapshot | symlink 拒绝、去写权限、tree hash 双验 | 快照复制或 mount 失败时只能返回 error |
| 冻结包对 writer 可见 | 有意设计，拉取通道的前提 | 需持续监控对未覆盖要求的挤出效应 |
| Original output | 不挂载到 Verifier namespace | writer 复核时仍自行修改原 output |
| Evaluator | task-native score，agent failed 时不执行 | 某些任务 evaluator 依赖外部模型 endpoint |

## 失败策略

- Prep 生成、解析或 staging 失败时，writer 继续。**报告 staging 必须在 artifacts 为空时也
  成功**，回归测试常驻。
- Verifier 构建或冻结失败时不运行测试，`verify` 向 writer 报告失败原因并记录 builder 响应
  前 400 字符。
- builder 机械修复轮没有减少定位失败时，保留原候选套件。
- `verify` 单次调用崩溃时返回错误文本且不计次；跑完但 overall 为 error 的计次。
- Snapshot、隔离环境或测试进程 error 写入 verifier metadata，不归因于 writer。
- Agent 基础设施失败时 lifecycle 跳过 evaluator 并保留 null score，与 artifact 0 分分开记录。

启用 Prep 或 Verifier 不会自动把 unit 判为失败。实验分析必须同时读取 agent status、eval
status、Prep status 与 Verifier status。

## 怎么判断系统改变了 writer 的行为分布

分数不作为迭代依据。四轮实测里 prep 的配对均差是 −0.007、+0.016、−0.004、+0.005，verifier 是
+0.021、+0.0005、+0.007、+0.0116，只有一次显著且没有复现。更关键的是**效应按题变号，不存在
一个可估的聚合效应**：14 题 k=3 的 sd（prep 0.090、verifier 0.047）高于单轮 26 题，因为剔除
恒零题后残差主要是题间真实异质性，重复次数解决不了它。

因此迭代依据统一为机制读数：

- Prep：环境到达率、早期回合工具分布、断点命中率、报告到达率。
- Verifier：信号率、`verify` 到达率与调用回合位置、调用后 output 是否变化、删减读数
  （`output_shrank`）、dispute 与振荡数。
- 全局：采用链必须在 transcript 里成立，分差在此之前不归属任何干预。

分数只在机制门全部通过之后，用预先定好的剔除清单加多轮配对验证。
