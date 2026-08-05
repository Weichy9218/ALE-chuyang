# Verifier

输出侧辅助 agent，默认关闭，实验臂开启。实现在
[`verifier.py`](../../ale_run/agents/ale_claw/verifier.py)（编译、冻结、反馈）、
[`verifier_runtime.py`](../../ale_run/agents/ale_claw/verifier_runtime.py)（staging、快照、隔离执行）、
[`verifier_precheck.py`](../../ale_run/agents/ale_claw/verifier_precheck.py)（writer 的
`verify` 工具）、[`verifier_sandbox.py`](../../ale_run/agents/ale_claw/verifier_sandbox.py)
（Landlock/seccomp 进程边界）。本文只描述当前设计。历史教训在 [FABLE.md](FABLE.md)，系统整合
在 [ARCHITECTURE.md](ARCHITECTURE.md)。

> 先证明题目要求什么，再测量 output 是否符合，把结果交给 Writer。
> Writer 回到 `/input` 判断反馈，不直接服从 Verifier 的解释。

## 定位

Verifier 是**系统里唯一的契约一致性所有者**。凡是"交付物是否符合题面和 schema 规定"这类
问题全部归它，包括过去由 Prep 交付的自检脚本所覆盖的结构审计。Prep 不再编译任何契约清单，
不再生成自检脚本。

归并的理由是实测的重复。两个 agent 互相不许读，从同一份公开题面出发，编译出的是同一张清单：
agora 题 Verifier 冻结 6 条（JSON 顶层结构、三个文档 ID 加 URL 标题、立法状态单选加逐字证据、
十类技术范围、六阶段生命周期、gap 词数），Prep 的 18 条契约覆盖同样这些义务；sec_10k 题
Verifier 4 条对 Prep 的 4 个区域逐条对应。两边还把同一批语义维度同时标成不可验证（agora 的
taxonomy 语义正确性、矩阵一致性、gap 实质内容；sec_10k 的取值准确性、分析题取值），而分数
正好长在这些维度上。一份产物没有理由付两次 LLM 编译费，而契约检查应当归能对着真实产物测量
的那一方。

分数由任务原 evaluator 在 solve 结束后用隐藏 reference 产生，writer 在提交前没有任何独立
测量。历史数据划出两条硬约束：

1. **反馈必须在 writer 还有预算时到达。** 反馈只在 DONE 后推送的协议下，52 个 run 产生 0 次
   修复，180 条 pass 确认全部作废。
2. **测量必须真的发生。** 曾经冻结的 344 条 check 里 156 条死在来源审查门上没有运行
   （ambiguous 145 条）。信号损耗的最大单项不是测量质量，是测量被自己的门拦住。

## 实现原则

- **唯一合法新增信息是对冻结 output 的可复现测量，每条锚定公开来源。** Verifier 不掌握隐藏
  评分，不宣布 output 最终对错；结构 pass 不等于任务正确。
- **零权威。** 每条结果都是参考测量而不是判决：冻结时 `blocking` 恒为 false，builder 的硬性
  主张只作为 `requested_blocking` 留档。这条不只在冻结点执行，也在装载点执行：
  `lint_frozen_suite` 在每次执行前拒绝任何带 `blocking=true` 的 suite，所以未来出现第二个
  suite 生产者或有人手改冻结文件，硬权威也不会静默复活。硬权威曾要求证明来源蕴含、checker
  对齐、来源无冲突，为此设了 Auditor 和五项 gate，实测这条链每环都在断（6/6 构建 error、
  12 条测试只跑 2 条），而同轮零权威的拉取式自检调用率是 5/5。总判定同步取消：`overall` 只
  描述覆盖，不给可刷的全绿目标。
- **能机械推导的不交给 LLM。** 题目自带机器可读规格时，校验器由代码从规格生成，零 LLM。只有
  散文里的义务才需要 LLM 编译。见"检查的两层来源"。
- **契约优先。** LLM 编译检查时锚定题面点名的文件路径、字段拼写、必须保留的标识符、数量、
  单位、顺序、编码、跨文件一致性，全部按题面原文逐字进入 checker（paraphrase 测的是
  paraphrase，不是契约）；check id 以契约义务命名（`contract.<file>.<obligation>`）。宁可用
  简单的存在性与计数检查覆盖更多契约条目，不为一条义务做深验证而让其余失去测量。
- **永不报全清。** 任何一次检查运行的结尾都必须打印它没有覆盖的面。见"停止信号"。
- **标准先于产物。** 测试在 writer 开始前生成并冻结（内容、hash、来源全部固定）；output 产生
  后只更新运行结果。执行时机对 writer 开放。
- **机械门决定跑不跑，不决定信不信。** 来源已定位、checker 过 fixture 预检、环境健康的检查
  一律执行；来源定位失败的不运行（coverage gap），预检失败的记 execution error。没有任何
  语义审查环节。
- **quote 是事实，locator 只是坐标。** quote 在文件中唯一时，错误行号由 harness 机械修正；
  仍失败的来源给 builder 一轮机械修复（证据只有"quote 未找到"一类，失败数严格减少才采用）。
- **报告测量，不做诊断。** Checker 只输出 `{status, observed, evidence}`；第一处分歧和根因由
  Writer 沿自己的代码与数据流追。反馈 source-first，不含 repair hint。
- **fail-open 到条目级，不到整包级。** 顶层字段缺失填默认值并记入 `dropped`，只有"没有任何
  可用测试或要求"才整包失败；单条测试的 schema 违规、超限、重复 id 只丢那一条。逐条隔离必须
  同时落到条目层和信封层：只做条目层时，信封层的硬拒仍然会整包失败。整包失败时 `verify` 向
  writer 报告失败原因，并记录 builder 响应的前 400 字符，用来区分 builder 真的产出坏 JSON 和
  提取器选错了对象。
- **Writer 是唯一决定 output 的 agent。** 每条失败可用 `VERIFIER_DISPUTE <check>` 附公开反证
  驳回；不诱导照抄任何给定值（防 reference 复制）；真实 revision 计数加 output 无变化即停。
- **fail-open。** 构建失败不运行测试；隔离启动失败归 error 不降级；一切 Verifier 故障都不影响
  writer 提交。

## 检查的两层来源

### 第一层：机械生成，零 LLM

题目自带机器可读的交付物规格时，校验器由代码直接从规格生成并冻结。这一层确定性、零 token。
识别按文件名进行：`output_contract.json`、`output_schema.json`、`task_spec.json`、
`*.schema.json`；识别不到时这一层为空，这是约三分之二任务的常态。发现多个规格文件时用第一个
可解析的，其余逐个记入 `dropped`，不静默跳过。

当前实现覆盖五类义务：文件存在性、CSV/TSV 列名、行数、JSON 顶层键集、CSV 列的枚举取值。
规格里认不出的结构产出 0 条检查；通用的 file/path/name 键只为同一块里声明的义务提供目标，
自身不产生任何义务，所以描述输入文件的块不会被编成对交付物的要求。交付物解析失败（非法
JSON、非 UTF-8）按 fail 报告并附原始错误，因为那是对交付物的测量，不是校验器自身的故障。

动机来自实测浪费：sec_10k 的自检脚本曾手工重实现题目自带 schema 的键集、cik 正则、日期格式
检查，让 LLM 抄一遍规格只是引入抄错的机会和一整条可能静默失效的交付链路。注意该题的
`input/schema/extraction_schema.json` 不匹配上述文件名约定，也超出五类覆盖；把 JSON Schema
的 required/pattern/type 编译进这一层是已知的未实现项，文档不预支它。

### 第二层：LLM 编译，只处理散文义务

只存在于题面散文里、无法从任何机器可读规格推出的义务才交给 builder。例如"第二遍必须与第一遍
逐字相等"、"括号里的金额记为负数"、"所有金额换算成原始美元整数"。

这条分界由机制保证，不靠自觉：builder 的 system prompt 里逐条列出第一层已覆盖的义务并要求
只编散文义务；check id 与第一层碰撞时 parser 生成的检查胜出（这一层存在的理由就是模型抄写
规格有抄错风险，碰撞正是两份抄写并存的时刻），被顶掉的 builder 测试记入 `dropped`；builder
崩溃或整包不可用时，suite 回退为纯机械层继续交付，第一层的存活不依赖第二层成功。

Builder 在 fresh context 中运行，看不到 Writer 与 Prep；prep 与它并发共享同一沙箱，其
scratch 路径（`/tmp/ale-task-prep-*`）在 prompt 中被点名禁读，这是提示词边界而非机制边界，
文件系统层面两者可互见。Builder 产出至多 6 个测试加 8 条
unverifiable，每测试一个确定性 Python checker 加合法/错误 fixtures 加来源集。

Fixture 用显式无歧义的数组 schema `{path, encoding, content}`：文本直接交付，harness 在
staging 时编码，只有二进制用 base64。隐式的单对象编码曾被 builder 反复误解成单文件对象，导致
整包 lint 拒绝。

### 判准来源的边界

只能从公开来源建立判准：task prompt、`/input`、题目指定的 `software/` 与公开数据、题面明确
要求的外部标准（版本和适用范围须题面直接指定并冻结为本地可哈希证据）。官方 evaluator、隐藏
reference、Prep 产出、历史分数不可用。题目没规定的阈值、容差、顺序、精度不补充；样例值不
推广；文本、样例、schema 冲突的要求标 `unverifiable`。枚举标签必须有公开的命题到标签映射，
缺数值不能自行决定写哪个。

每个测试记录完整来源集：`{path, locator, quote}` 每项加 SHA-256。JSON 用 JSON Pointer，文本
与 task prompt 用 `lines:N-M`（至多 50 行），参与重算的二进制用 `file` 冻结整文件 hash。多个
字段依赖多份来源时必须全部显式声明，只引用其中一份不足以证明期望值。

`task_prompt` 来源定位失败时，locator 自动回退到公开文件 `input/task_prompt.md` 再试一次（两者
是同一份公开文本的两个入口），命中即采用并改写定位证据；仍失败才记 coverage gap。

## 生成与冻结

```text
阶段 A（与 prep 并发；只读公开任务表面）
  第一层：代码从机器可读规格生成校验器（零 LLM）
  第二层：Builder（fresh context；prompt 内列出第一层已覆盖义务）编译散文义务的候选测试
    -> Builder 失败且第一层非空 -> suite 回退为纯机械层，失败原因记入 dropped
    -> lint（schema、大小、路径、fixture 差异；单条违规丢该条记 dropped，
       信封层缺字段填默认，只有"无任何可用测试"才整包失败）
    -> 机械定位每个来源（单次批处理）：quote 唯一时自动修正行号；hash 固定
    -> 定位失败 -> 一轮机械修复（新 builder 会话只见失败清单；重 lint 重定位；
       定位失败数严格减少且 lint 丢弃数不增加才采用）

阶段 B（prep 完成后、prep 报告 staging 之前；纯机械，零 LLM）
  -> stage 候选 + fixture 预检（合法过/错误挂、连续两次一致、环境探针）
  -> finalize：blocking 恒 false + 整包 SHA-256 冻结
```

阶段 B 后移的原因是环境一致性。`environment_healthy` 和 `checker_reproducible` 是环境判定，
执行却发生在 writer 之后的沙箱里，而 prep 会在此期间装包、改缓存、起服务。预检若与 prep 并发，
依赖 prep 稍后装好的运行时的 checker 会被冻结成"不可复现"而永久降级。移到 prep 之后，gate 在
writer 将要接手的同一环境里测量。独立性不受影响：标准的内容全部在阶段 A 生成，不读 prep；
阶段 B 是纯机械步骤，在 prep 的语义产物 staging 之前完成，不读任何文本。

冻结后每条检查的处置只由机械事实决定：

| 情形 | 处置 |
|---|---|
| 任一来源定位失败 | `coverage_gaps`，不运行 |
| checker 未过 fixture 预检或环境不健康 | `execution_errors` |
| 其余 | 运行，差异进 `review_items` |

执行方式优先级：题目真实软件 > 公开重算 > simulation（报告中注明）。

## 执行与三类输出

Writer 的 `output/` 复制为只读快照（拒 symlink、去写权限、tree hash 双验）。每个测试在
Landlock/seccomp 隔离进程运行两次，结果不同归 error；只读公开 input/software/快照/checks，
只写独立 scratch，无网络；每次执行前复验 suite hash、script hash、公开来源 hash，以及
`verifier_sandbox.py` 自身的 hash。

隔离是必须的，不是防御性冗余：曾观测到任务 runtime wrapper 通过执行改动了 writer 原 output
下的环境文件，前后双 hash 把 4 次运行记为 error。

报告把每条检查的原始结果直接交给 Writer，不替它分类判断：status 是 checker 自己打印的
pass/fail/unverifiable 或执行层的 error，observed 与 evidence 是 checker 的原样输出，附
requirement、命令与来源。pass 压缩成单行，fail 与 error 保留完整记录。一条没跑成的检查就给
原始错误，它本身说明不了 output 什么，怎么处置由 Writer 判断。

**unverifiable 是唯一的例外，它不走结果通道。** 一条没测过的要求对答案对错是零信息，既不是
pass 也不是存疑；把它和真失败同段渲染，Writer 会把"没信息"读成"有问题"。实测事故：sse q3
的 unverifiable 条目带着 builder 的实质论证（"规则明确允许英文……单一 Yes/No 无法证明"）
与真失败并列送达，Writer 把已经答对的 No 改成了 Unknown（该题两臂 0.667 对 0.333），与
FABLE 里 prep 曾把"只明确允许英文"放大成 Unknown 是同一种翻车。因此 unverifiable 单独成段
（NOT TESTABLE FROM PUBLIC MATERIALS），中性渲染只留 requirement 和一句机械的"为何没测"
（Why untested）。builder 的 interpretation、evidence 以及它对答案取值的任何论证一律不渲染；
`expected` 也不以带标签的 Expected 行出现——它只以复述题面原文的 requirement 形式落地（代码里
unverifiable 项的 `requirement` 即取自 builder 的公开措辞 `expected`）。WRITER INSTRUCTION 显式声明
unverifiable 不是存疑信号，不因"某要求测不了"改答案，只对跑过且有差异并经复算的检查行动。
渲染侧挡一层，来源侧再挡一层：builder prompt 规定 unverifiable 的 `reason` 只准陈述机械
障碍、`expected` 只准复述题面原文，两者都不得对答案取值做判断或论证。

`review_items`（执行过且观测到差异）、`execution_errors`、`coverage_gaps` 三类不作为**渲染段**
出现在给 Writer 的反馈里，也不附带各自的"处置建议"，只留作机制读数与复核轮触发条件。它们仍以
纯 check-id 名单的形式存在于 staged 的"完整报告"JSON（`metadata().categories`）里——Writer 拿到的
是指向该文件的指针，主动打开才看得到；仅当报告文件 staging 失败时才把（截断后的）JSON 内联。
`overall` 只描述覆盖：`measured`、`error`、`unverifiable`。没有可优化的全绿总判定。

## 与 Writer 的两条通道

**拉取（主通道）**：writer 全程持有 `verify` 工具，对当前草稿快照运行完整冻结包，返回同一份
原始结果报告。调用不设稀缺配额：writer 自己的步数预算就是真实上限，`verifier_writer_checks`
只是防失控调用循环的安全上限（默认 8，0 至 64），工具描述与首轮提示都不渲染稀缺感，因为
稀缺感会诱导 writer 把调用囤到轨迹末尾，而那正是要改变的分布。冻结包首次调用才 stage 进
VM；快照命名空间独立；调用崩溃不计次，跑完为 error 计次；预运行不消耗复核轮数。

**推送（兜底）**：DONE 后快照、跑完整冻结包，存在未 dispute 的差异项时反馈给 Writer
（source-first：来源、hash、interpretation，然后命令、observed、expected、evidence），Writer
修改后重跑完整冻结包。上限 `verifier_max_review_rounds`（默认 1）；output 无变化即停；全部
可复核项被 dispute 即停。

拉取通道存在的理由就是转化链：同一份测量，DONE 前到达可以转化为修复，DONE 后到达只能转化为
验尸。

自动 repair 循环不开。历史上每次放开都诱发振荡、误修或 reference 泄漏：一次 repair 把原本
正确的枚举答案改成了公开规则未定义的另一个值；另一次 repair 后 writer 把 32% 公开 reference
混进重建产物，绕过了 evaluator 的 anti-copy 检查。修复权只在 writer 手上。

## 停止信号

这是本次重构新增的强制要求，来自一条实测行为链。

能返回"0 failed"的检查器就是停止信号。agora 题的 writer 先读了检查器源码搞清楚考什么，接着
把力气全花在让逐字子串断言通过，拿到 `155 passed, 0 failed, 2 cannot check` 立刻收工，自己
派出去的语义复查从没等过。而真正决定分数的隐藏证据门（每条证据至少 5 词、必须命中标签关键词、
一篇文档通过率低于 80% 则三个分项全乘 0.5）不在检查器覆盖范围内，那一轮三篇文档全被腰斩。

因此：

- **任何一次检查运行都不得以"全部通过"结尾。** 终局段 NOT CHECKED 逐条列出本次未覆盖的面，
  例如"本次未检查：取值是否正确、分析是否合理、题面只在散文里陈述且无冻结测试覆盖的要求"。
- **未覆盖清单从本次实际执行的检查集合推导**（`uncovered_statement(measured)`）：某维度这次
  真的有检查跑过，对应条目就从清单里消失。清单必须保持为真，一段恒定不变的横幅会被 writer
  学会跳过，一段偶尔说错的横幅会教 writer 不信它。
- **`unverifiable` 结果保留完整记录**，与失败同格式打印；pass 才压缩成单行。

对策是声明边界而不是加新 gate。新 gate 会制造新的可优化目标，而声明边界只削弱停止信号。

## 怎么判断 verifier 是否改变了 writer 的行为分布

分数不作为迭代依据。四轮实测的配对均差是 +0.021、+0.0005、+0.007、+0.0116，只有第一轮显著
而它没有复现，四轮平均约 +0.011。聚合均值还掩盖了真实结构：效应按题分布极不均匀，agora 三轮
稳定 +0.15 到 +0.18，sap 三轮精确相同，而个别题会出现大额损失。

改用机械读数，全部与 base 臂对照，核心是两条：

1. **到达**：`verify` 调用率与调用发生的回合位置。曾观测到自检的首次调用中位落在轨迹 82%
   处，24 个里 14 个在最后一或两轮，说明它被当成提交前的终局确认而不是过程工具。这个分布
   本身就是要改变的对象。
2. **转化**：`verify` 调用之后 output 是否变化，DONE 后一轮差异是否趋零。

三条护栏：

3. **信号率**：冻结 check 数与实际运行数之比，重定位命中数，修复轮触发与采用。这测的是
   组件没坏，不是组件有用。
4. **删减读数**：每次快照记录 per-file 字节与行数，分析侧做连续差。`output_shrank` 为真表示
   writer 靠删内容通过检查。这是本设计最需要证伪的副作用：面对机械检查删减永远是最便宜的
   通过路径，而隐藏 rubric 通常奖励被删掉的部分。
5. **安全**：writer dispute 计数与 dispute 触发的停止原因，revision 超过 1 的振荡题数。
   （"dispute 是否成立"需要裁定，不是机械读数，不列。）

## 流程

```text
                    ┌─ Prep ─────────────┐──> 沙箱状态 / 报告文件 + digest ──> Writer ─┐
公开题面+input+software┤                   │                                          │ output/
                    ├─ 第一层 校验器（机械生成，零 LLM）─┐                             │
                    └─ 第二层 Builder ─> 定位/修复 ──────┴─> fixture 预检 ─> frozen suite ┤
                       （阶段 A，与 prep 并发）      （阶段 B，prep 后，零 LLM）│         │
                                （solve 中）Writer ────────────────────────────┴─ verify ─> 快照+隔离执行 ─> 分类报告
                                （DONE 后）快照 ─> 完整冻结包 ─> 复核 ─> 重跑
```

## 协议标识

不使用手工递增的版本号。`verifier_protocol_digest()` 对 builder 的 system prompt 与第一层
生成的校验器模板一起取 SHA-256 前 12 位，加 `verifier-` 前缀写进 `verifier_meta.json` 的
`protocol_digest`。
