# Prep

输入侧辅助 agent，默认开启，实现在
[`task_prep.py`](../../ale_run/agents/ale_claw/task_prep.py)，交接在
[`deployer.py`](../../ale_run/agents/ale_claw/deployer.py)。本文只描述当前设计。历史教训在
[FABLE.md](FABLE.md)，系统整合在 [ARCHITECTURE.md](ARCHITECTURE.md)，契约与 schema 审计不在
本文，见 [VERIFIER.md](VERIFIER.md)。

> 在 writer 开始之前，把这道题的运行时真正跑通，并把跑的过程中断掉的地方如实报告。
> 不编清单，不猜评分，不选取值。

## 定位

Prep 是**先行侦察**，不是质检。它和 writer 共享同一个沙箱，在 writer 之前运行，唯一目的是
让 writer 接手时环境已经是可用的，并且已知的坑已经被踩过一遍。

### 三条能力边界与它们的代价

红线里两条禁令是有意的：prep 不选 label/值/模型/缺失值策略（防它变成第二个答题器），不碰
writer 的 output（那是 verifier 的活）。代价是天花板：判断密集的闭卷题，丢分恰好落在这两处，
prep 守着禁令就够不着。2026-07-22 的 26 题实测印证了这点，也定位到三个结构问题，已按下述修订：

1. **能动分的地方 prep 不许碰，prep 许碰的这套题不丢分。** prep 三件事是跑通运行时、跑一次
   核心步骤、补外部事实。这套题过半是闭卷纯文本：env ready 23/26，运行时本就不崩，材料全
   staged 无外部事实可取。于是 prep 在这些题上按自己 charter 的期望值≈0，跑它只剩锚定风险。
   **修订**：prep 显式获准在这类题上判空——三件事都为空时返回 `not_needed`、其余段留空即收，
   digest 为空则 deployer 一个字都不注入。空 prep 是成功的 prep，不是失败。
2. **消费被动、没有载体。** sources_revisited 全 26 题为 0，artifact 只有 7 题有且都很小。
   writer 从不回到 prep 引用的源去核对或复用，findings 被当散文提示消费掉。variant 那题 prep
   咬到了真难点（等位基因归一化），却给成一段文字而不是一段跑得通、writer 能直接调的 resolver。
   **修订**：job 3 要求交测过、可调用的 artifact 优先于散文；成功指标改为 artifact 被调用、
   源被回访，而不是报告被 inline（见末节读数）。
3. **锚定成本让它略偏负。** −0.011（t=−1.30，噪声内，非显著负）方向上的负来自可复现的锚定：
   variant（−0.136）prep attempt=broke 自己没解决，却把它写成 `writer_action: "Treat this
   as the primary unresolved breakage…"`，把一个啃不动的硬子问题标成"头号未解难题"递给 writer，
   预算被引进坑；flusight（−0.097）prep 给的是"把 US 序列当独立观测"这类泛泛框，不改 WIS 评分
   却替 writer 定了议程，把本能答好的题带到 base 地板以下。机制与 verifier 的 unverifiable
   回声同型：把"我没搞定"渲染成"你要重点搞"。**修订**：见下方反锚定三条。

反证是 agora（+0.096，最正一题）：它的 findings 恰好全打在评分维度上（逐字保留证据的 OCR
痕迹、implicit 的使用边界、按 enforcement 判定法律地位）。prep 一旦命中评分面就是正的，
但当前命中靠碰巧不靠机制，因为 charter 把它从评分面推开、消费方式又是被动散文。

它交付三类东西，按保真度排序：

1. **沙箱运行时状态**。装好的包、改好的缓存路径、起好的服务、验证过的命令。零损耗，writer
   不需要相信任何文字，状态直接生效。
2. **断点报告**。Prep 亲自跑一遍这道题的核心机械步骤，把断掉的地方连同确切命令和报错原文
   记下来。这是 prep 唯一有资格提供的"易错点"，因为它是实测的，不是想象的。没有机械核心的
   题（只读材料写散文）返回 `not_attempted` 加一句理由，不编步骤。断点未解决时，把复现脚本
   作为 artifact 附上，断点只作一条观察（命令加原始报错）陈述，不排优先级、不标"头号问题"、
   不指挥 writer 预算去向。
3. **findings**。题面缺失的外部精确事实，每条附来源、可对源核验。方法选择、建模假设、对任务
   的框定（"把这些序列当独立观测""无需日历展开"）不是 finding，不得当 finding 报——它替
   writer 做了推导，而错的框比缺的事实代价更大。可用、测过的 artifact 优先于散文。

明确不做的事：不编交付物合同清单，不生成自检脚本，不选定最终取值，不判断候选产物对错。
契约与 schema 审计整体属于 Verifier。

### 为什么合同清单和自检脚本被移走

同一道题上，Verifier 的 builder 和 Prep 各自从同一份公开题面出发，编译出的是同一张清单。
实测对比：agora 题 Verifier 冻结 6 条（JSON 顶层结构、三个文档 ID 加 URL 标题、立法状态单选
加逐字证据、十类技术范围、六阶段生命周期、gap 词数），Prep 的 18 条契约覆盖同样这些义务；
sec_10k 题 Verifier 4 条对 Prep 的 4 个区域逐条对应。两边还把同一批语义维度标成不可验证
（agora 的 taxonomy 语义正确性、矩阵一致性、gap 实质内容；sec_10k 的取值准确性、分析题取值），
而分数正好长在这些维度上。

一份产物付两次 LLM 编译费，收益为零，风险为正：清单越具体、越可执行，writer 越会照着它
优化，代价落在清单没点名的维度上。agora 的 prep 臂轨迹是完整样本，writer 先读了自检脚本的
源码搞清楚考什么，接着九次工具调用几乎全花在修空白字符让逐字子串断言通过，拿到
`155 passed, 0 failed` 就收工，自己派出去的语义复查 subagent 从没等过。同一轮它三篇文档的
证据门通过率是 0.750、0.500、0.600，全部低于 0.8 阈值，三个分项全被乘 0.5。

结论不是"自检有害"，而是"契约检查只该有一份，且该由能对着真实产物测量的那一方拥有"。

## 实现

Prep 返回一个 JSON 对象，每一部分都可以为空：

```json
{
  "environment": {
    "status": "ready | partial | not_needed | blocked",
    "summary": "题目需要什么运行时，现在是什么状态",
    "commands": ["已验证的确切命令"],
    "blocked_reason": "跑不通的部分"
  },
  "attempt": {
    "step": "尝试的核心机械步骤是什么",
    "outcome": "completed | broke | not_attempted",
    "command": "跑的确切命令",
    "breakage": "断在哪里，报错原文",
    "writer_action": "writer 接手时应当注意什么"
  },
  "findings": [
    {"title": "", "observation": "带取值的事实",
     "writer_action": "writer 怎么用",
     "sources": ["URL 或 input/path#locator 或 runtime:probe"],
     "do_not_infer": "这不授权什么，可选"}
  ],
  "artifacts": [{"path": "scratch 下的相对路径", "purpose": ""}]
}
```

`attempt` 是本次重构新增的一等字段，也是 prep 现在的主产出。它要求 prep 把预算的一部分从
"读"移到"做"。旧设计里 prep 通读题面然后编清单，结果是清单正确而无用；variant 题是标准
样本，prep 查到了官方 severity 排序，送达、被 writer 抄进代码、结果正确，而真正丢掉 20 分的
是一个 indel 等位基因归一化 bug，prep 的五条 findings 一条都没碰到它。那个 bug 只有亲手搭
一遍 pipeline 才会撞上。

### 机械校验

校验是逐条的，只做三件事：不合格条目**逐条丢弃**、**记入 `dropped`**、**永不整包拒绝**。

- **不截断内容字段。** summary、断点 breakage 原文、finding observation 这类自由文本一律整段
  保留。字符级静默截断会丢掉 writer 需要的内容，又不像条数上限那样在 `dropped` 留痕，等于让
  审计轨迹谎称 prep 返回得比实际少。唯一的整体大小闸是报告文件的 48,000 字符安全上限：超限时
  截断在尾部、头部打一条断言横幅、并记 `report:truncated`——记录在案，不是静默切片。
- **条数上限产生 `dropped`。** findings 6、artifacts 4（各 64 KB）、`environment.commands` 8、
  `finding.sources` 4；超出部分记 `<name>: N beyond the <cap> cap`。
- **结构不合格逐条丢弃。** 非对象、枚举外的 `status`/`outcome`（置空）、路径不安全或后缀不符、
  artifact 内容含 NUL（`artifact:rejected_content`）、超 64 KB（`artifact:too_large`）。

声明的 artifact 读不到时，先看命令返回码再解析字节数，两种失败分别记 `artifact:missing` 和
`artifact:unreadable`，并把 scratch 目录里实际存在的文件列进 `dropped`，用来区分"路径写错"
和"根本没写"。这条"缩减必留痕"的原则在 prep 和 verifier 两侧各被同一类 bug 咬过一次，
见 [FABLE.md](FABLE.md)。

### 预算与工具

50 LLM step、1800 s、每轮 tool result 60 KB。步数用掉约 80% 时注入一次预算提示，要求 10 轮内
收尾并返回 JSON：prep 现在要真的跑核心步骤，是开放式工作，跑满步数返回的是 sentinel，整轮
产出全部作废。工具为 `read`、`exec`、`web_search`、`web_fetch`，
不受 writer 臂 `disabled_tools` 影响。scratch 目录初始化单独给 180 s 并重试一次，它在 LLM
会话开始之前跑，失败会让整个 prep 机会作废（观察到的形态是 `llm_turns=0` 的 TimeoutError），
而命令是幂等的 `rm -rf && mkdir`，重试无副作用。

## 交接与消费

按保真度排序，两条通道：

1. **沙箱状态**：直接生效，零损耗，不经过任何文字。
2. **报告文件 + digest**：完整报告写到 VM 的 `task_prep/PREP_REPORT.md`；writer 首轮 prompt
   注入 digest。digest 开头是完整的五级权威顺序（见下节"红线上方"），随后是运行时状态与已验证
   命令、`attempt` 的断点摘要、findings 的标题与观察、以及一条读报告指令（英文
   "Read it before you start planning"，指向 `task_prep/PREP_REPORT.md`）。findings 的观察与断点
   在 digest 里各截到 600 字符，这是**注入预算**不是数据丢弃——全文都在报告文件里，digest 明确
   指向它。`writer_action` 与来源一律不进 digest。

digest 必须携带真实状态和断点，因为这两类信息在 t=0 就要到达才有用。findings 进 digest 是
因为只存在于报告文件里的 finding 曾经零到达。

报告不内联进首轮 prompt。48,000 字符是防爆炸的安全上限而非注意力预算，超限时截断发生在文件
尾部，且文件头部写明"本报告被截断"，读者不会把残缺内容当完整内容。

**staging 的一条硬要求**：报告必须在 artifacts 为空时也能落地。`_stage_prep_bundle` 曾把
`create_dir(report_dir)` 写在 artifact 遍历循环内，artifacts 为空时目录不存在，紧接着的
`write_text(report_path, ...)` 抛 ENOENT 被吞掉，整份报告静默丢失而 prep 仍记为 completed。
这个 bug 污染过一整轮对照实验。回归测试 `test_report_is_staged_even_with_no_artifacts` 必须
常驻。

题面和 `/input` 的权威永远高于 bundle。完整权威顺序在 t=0 就全部下发给 writer（digest 开头与
报告头各印一份，不再只给最顶一级）：task prompt > `input/`/`software/` > writer 复查 >
prep 产出 > 通用知识；冲突时 prep 产出丢弃。

## 红线

- **不选定最终取值。** 标签、数值、缺失值策略都留给 writer。
- **不编清单、不交自检脚本。** 这条只有提示词约束：artifact 的机械校验看路径、后缀、大小，
  不辨用途，.py/.sh 是放行的。所以它的守住与否要靠轨迹审计：writer 对 prep 交付脚本做
  检查式调用，就是违规样本。与 verifier 的边界同理，两者共享沙箱、认知隔离，隔离靠双方
  prompt 里点名的禁读路径，不是文件系统机制。
- **运行期不碰候选 `output/`。** 彼时它不存在。
- **只做机械校验。** 语义 gate 无法机械判定，做成硬门必然退化成格式检验并误杀高价值内容。
- **fail-open。** prep 失败、超时或为空都不阻塞 writer。
- **不缓存。** prep 留下的是真实状态，缓存的报告会谎称环境就绪。
- **能保持沉默。** 被迫产出内容比不产出更有害。曾有一轮 prep 把"只明确允许英文"放大成
  `Unknown`，同题分数从 0.6667 直接降到 0。

## 怎么判断 prep 是否改变了 writer 的行为分布

Prep **不以端到端分数论成败**。三轮 26 题加一轮 14 题 k=3，prep 的配对均差分别是 −0.007、
+0.016、−0.004、+0.005，全部不显著，而其中两个最大的单题效应（sec_10k +0.257、variant
−0.137）经拆解都是"题面没规定的地方押中或押错了哪一边"，不是能力差异。继续用聚合均值判 prep
只会得到噪声。

改用直接测行为分布的读数，全部与 base 臂对照，不需要精确、不需要分数归因。核心是两条，
与 verifier 侧的读数同构（到达、转化）：

1. **到达**：transcript 里 `PREP_REPORT` 的命中次数。命中 0 次的 unit 等于 prep 白跑，
   不能计入 treatment。引用任何单题 prep 效应之前先跑这个 grep。
2. **转化（使用而非投送）**：报告被 inline 只证明送到了，不证明被用。真正的转化读数有两条，
   都度量使用：`artifact_calls`（writer 工具调用里命中 `task_prep/artifacts/` 的次数）和
   `sources_revisited`（writer 是否回到 prep 引用的源）。2026-07-22 两者几乎全 0，是本轮判定
   "投送已解决、消费仍空"的直接依据。另比对 prep 臂与 base 臂 writer 前 N 回合的环境准备类
   工具调用占比，prep 若真把环境交好，占比应下降；判定关键字清单冻结在 analyzer 里。

两条辅助读数：

3. **环境到达率**：`environment.status == ready` 的比例。这测的是 prep 自己的声明，属于
   "组件没坏"，单独不构成有效证据，要与第 2 条合看。当前基线 23/26。
4. **断点判别（跨臂）**：`attempt.breakage` 报告的断点，base 臂 writer 在同一任务上是否
   也撞上。base 臂撞上说明 prep 侦察到了真实的坑；base 臂也没撞上说明它在报告想象中的坑。
   不能在 prep 臂内部读这条：digest 已把断点告诉 writer，避开断点正是期望结果，臂内的
   "未命中"分不开"坑是假的"和"警告生效了"。反向信号也要记：prep 报 `completed` 而 writer
   仍断在核心步骤，是 attempt 失职的直接证据。

删减读数（`output_shrank`）依赖快照序列，快照只在 verifier 在场时产生，prep 单独臂算不出，
归属见 [VERIFIER.md](VERIFIER.md)。

## 流程

```text
公开题面 + input/ + software/
  -> Prep（writer 同沙箱；read/exec/web；50 步 / 1800 s；80% 处提示收尾）
       1 跑通运行时，状态留在沙箱
       2 亲自跑一遍核心机械步骤，记录断点
       3 补题面缺失的精确外部事实
  -> 一个 JSON -> 逐条机械校验（不合格丢条目，记 dropped）
  -> 收集 artifacts（缺失则重新渲染报告，撤下对应引用）
  -> stage task_prep/PREP_REPORT.md（artifacts 为空也必须落地）
  -> writer 首轮 prompt 注入 digest：运行时状态 + 断点 + findings + 读报告指令
  -> writer：状态直接用；读报告；契约检查去找 Verifier
```

## 协议标识

不使用手工递增的版本号。`prep_protocol_digest()` 对实际下发的 system prompt（含输出 schema）
取 SHA-256 前 12 位，加 `prep-` 前缀写进 `task_prep_meta.json` 的 `protocol_digest`；取哈希前把
`task_root`/`scratch` 等路径占位符归一化，好让同一份契约在不同任务、不同路径下得到相同 digest。
两次运行的 digest 相同，当且仅当它们拿到的是同一份契约。版本号会随改动膨胀且无法反查真实内容，
哈希不会。
