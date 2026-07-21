# Task-Specific Prep

更新于 2026-07-21。当前实现为 `task-prep-v20`，默认开启。实现位于
`ale_run/agents/ale_claw/task_prep.py`，交接位于
`ale_run/agents/ale_claw/deployer.py`。v19 删除 `_targets_writer_output` 字符串检验，允许
（并鼓励）writer-facing 的检查项和自检工具引用 `output/` 交付物路径，见下文"v19 的边界
修正"。v20 在此之上把合同自检升为一等公民：新增 `self_check` 输出字段和报告里的
"Self-check" 一节，保留结构化 contract 供机械对账，见下文"v20：self_check 与对账"和
[FABLE.md](FABLE.md)。

## 定位

Prep 在 writer 之前、在 writer 的同一个沙箱里运行。它做三件事，按价值排序：

1. 把题目需要的运行时跑通，并把跑通的状态留在沙箱里。
2. 从题面和 `input/` 编译出交付物的合同清单，标出容易漏和容易读错的条目。
3. 补上 writer 难以自行获得的精确事实或可复用工具。

第一项是真实工作，不是关于工作的报告。prep 安装的包、改好的缓存路径、启动起来的服务，
writer 开始时仍然在。第二项是对公开题面的阅读，不是评分标准，也不是对隐藏答案的猜测。
第三项才是过去几版 prep 唯一在做的事。

## 为什么改成这三件事

26 题的失分按体量排，第一类是合同覆盖不全。BPMN 两臂总差 `-0.0353`，其中 81% 来自
data-flow 分项，evaluator 检查的是 67 条 producer-consumer 约束；CRF4 是 57 行 mapping 的
ValueList、WhereClause 和 role 词表。writer 知道要做什么，缺的是在提交前确认自己覆盖了
多少条的能力。第二类是运行环境阻断，SEC 的 Python 版本不兼容、Bias 的缺包、American
option 的 uv 缓存不可写都属于这一类。第三类才是外部精确取值，26 题里只有 Variant 一例。

v17 及以前的协议只允许交付第三类，并且要求单点闭环。结果是准入标准把 prep 收紧到无法
产出：v17 六题机制 canary（`.logs/ale/prep_v17_selected_six`，2026-07-21 05:59）6/6 空报告，
prep 臂等价于 base 臂并多花约 24.5 万 input token。逐题原因是：

| 题目 | 模型决策 | 代码 gate | 实际原因 |
|---|---|---|---|
| BPMN | use，带成功执行回执 | `missing_impact_coverage_evidence` | 要求 `N/N` 字面串出现在某条 source evidence 里 |
| Digital | use，回执为 `launcher_ok rows=10000 unique_ids=True` | `missing_impact_coverage_evidence` | 同上 |
| Variant | skip | `nonexternal_focus_used_web` | 已 fetch 到 Ensembl consequence 表，预算耗尽后放弃 |
| SEC | skip | 无 | 3.10 已绕过版本冲突，验证探针用了不存在的 PDF 模块 |
| Bias | skip | 无 | 缺包，300 秒内没验出 workaround |
| Agora | skip | 无 | 题面材料已经足够，属于正确的 skip |

两个 gate 的问题不同。`missing_impact_coverage_evidence` 是字符串巧合检验，没有语义内容，
却能丢掉整份已通过执行验证的报告。`nonexternal_focus_used_web` 在 `decision == "skip"` 时
`focus` 为 null，于是"查了网页、发现补不上、诚实 skip"被记成违规。加上 6 步、300 秒、
每轮 12KB tool result 的预算，Variant 这个 26 题里唯一确证有效的机制被掐死。

结论是准入标准继续收紧没有空间了。v18 换方向：把 prep 对准最大的失分面，放开预算，删掉
无法机械判定的 gate。

## 权威和分工

求解时的权威顺序：

1. 当前 task prompt。
2. 当前 `input/`、`software/` 中的 task-local 规则、数据和 provenance。
3. writer 对上述材料的直接复查结果。
4. 内联的 Prep 报告、`task_prep/PREP_REPORT.md` 和 `task_prep/artifacts/`。
5. 通用背景知识。

Prep 与前三级冲突时丢弃。合同清单是对题面要求的阅读，可能不完整，writer 依赖哪条就复查哪条。

| 角色 | 时间 | 任务 | 产物 |
|---|---|---|---|
| Prep | writer 前，同一沙箱 | 跑通运行时、编译合同清单、补精确事实 | 可用的运行时状态、清单、observation、可复用 artifact |
| Writer | 全过程 | 综合 task、input 和 Prep | 最终 artifact 和自检 |
| Verifier | 最终 snapshot 后 | 判断候选 output 是否违反公开 contract | observed/expected/source verdict |

边界是"谁碰候选产物"。Prep 不读、不写、不检查 `output/`；对候选产物下判断是 Verifier 的角色。
Prep 交付的是 writer 自己去跑的清单和工具，不是对 writer 结果的裁决。

## v19 的边界修正

v18 及以前用字符串匹配强制上面这条边界：命令、检查、writer action 和 artifact 内容中出现
`output/` 引用的条目会被丢弃。这个实现方式和 v17 的 `missing_impact_coverage_evidence` 是
同一种病：用机械代理检验一个语义边界，误伤恰好落在价值最高的条目上。三处具体误伤：

1. 合同条目的 `check` 字段被静默清空。"writer 如何验证"几乎必然要引用交付物路径，
   "运行 xmllint 检查 output/process.bpmn" 正是清单里最有用的那类条目。
2. `writer_action` 提到 `output/` 的 finding 整条丢弃。
3. artifact 内容含 "output/" 字样即被拒收，这直接封死了 prep 交付自检脚本的路。

关键事实是：prep 运行时 writer 的 `output/` 还不存在，prep 在运行期检查候选产物在物理上
不可能发生。字符串检验从未强制过运行期行为，它只是在净化给 writer 的建议文本。真正要防
的是 prep 替 writer 预定最终取值，那由 prompt 规则约束（"Do not choose final labels,
values, ..."），与是否提到路径无关。v19 因此删除该检验，边界的执行点回到"谁在什么时候
运行"：prep 从不执行任何针对候选产物的检查，但它交付的检查说明和自检脚本应当引用
`output/` 下的交付物路径。系统 prompt 相应新增一类推荐 artifact：可运行的合同自检脚本，
writer 对自己的草稿反复运行，prep 只在自己 scratch 里造的合成小样上测试它。

## v20：self_check 与对账

v19 允许 prep 交付自检脚本后，v20 解决"writer 怎么消费它"：

1. **self_check 是输出结构的一等字段。** prep 把可运行的合同自检脚本注册为
   `self_check = {command, artifact, covers}`；报告里渲染成独立的 "Self-check" 一节，给
   writer 一条确切命令（如 `python3 task_prep/artifacts/check_contract.py output`）。机械
   校验只有两条：command 非空、artifact 必须在已声明的 artifacts 里；artifact staging 失败
   时整节撤下并记入 `dropped`，报告重新渲染，不会向 writer 宣传一个打不开的文件。它没有
   任何权威，checklist 仍是事实来源；与 verifier 的 `verify` 工具相比，它随时可跑、不限
   次数、也不进入任何评审记录。
2. **结构化 contract 保留下来。** `normalize_prep_bundle` 拆成解析与渲染两步
   （`render_prep_report`），解析出的合同条目原样进入 `TaskPrepResult.contract` 和
   `task_prep_meta.json`。这使 prep_verifier 臂可以做机械合同对账（见
   [ARCHITECTURE.md](ARCHITECTURE.md) 的 Contract cross-check）：prep 清单与冻结测试是对
   同一公开表面的两次独立阅读，harness 按引用的公开文件对齐两者，"冻结测试引用而清单
   没有条目"的文件和"清单有条目而无测试覆盖"的文件都注入 writer 初始 prompt。对账只比
   文件覆盖，不判断谁读对了，也不改变任何测试权限。
3. 顺带删除了 v18 遗留的报告字符串替换 hack（artifact 缺失时改行首标记），统一为
   带 `unavailable` 集合的重新渲染。

## 输出结构

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
     "check": "writer 如何验证",
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

schema 只保留能被文件系统和响应结构机械判定的部分：类型、长度、条数、artifact 路径安全性、
后缀、大小，以及 `self_check.artifact` 必须在已声明 artifacts 中。artifact 内容层面只剩
`\x00` 二进制拒收（`task_prep.py:589`），v18 的 `_targets_writer_output` 字符串检验已随
v19 删除。判断类的字段全部删掉了，包括 `impact_coverage`、`confidence`、`focus.kind` 分类、
`task_relation`、`applies_if`、`expected_signal`、`validation_command` 和 `validation_signal`。
这些字段无法机械验证语义，做成硬 gate 只会退化成格式检验。

校验是逐条的。一条不合格只丢这一条，记进 metadata 的 `dropped`，不影响整份报告。v17 那种
整包丢弃已经删除。

上限：合同清单 24 条，findings 6 条，artifact 4 个各 64KB，报告 12,000 字符（超出截断，
不拒绝）。

## 预算和工具

| 项 | v17 | v18 |
|---|---:|---:|
| LLM step | 6 | 30 |
| 会话超时 | 300 s | 1800 s |
| 每轮 tool result | 12 KB | 60 KB |
| 报告长度 | 2,200 字符 | 12,000 字符 |
| artifact | 1 个 / 16 KB | 4 个 / 64 KB |

工具是 `read`、`exec`、`web_search`、`web_fetch`。搜索不再限定 focus 类型。deployer 把未经
`disabled_tools` 过滤的工具表交给 prep，所以 writer 臂关掉 `web_search` 时 prep 仍然有。
`web_search` 走 Exa（主）和 Firecrawl（备），key 由实验 yaml 的 `secret_file` 载入
`os.environ`；`web_fetch` 是直连 GET，不需要 key。2026-07-21 在 pgl 上验证：Exa 返回 200，
Firecrawl 返回 402，因此实际走 Exa。

缓存已经删除。prep 会在沙箱里留下真实状态，复用一份缓存报告会声称环境就绪而实际没做过
任何配置。同理 `compute_task_fingerprint` 和 `validate_prep_sources` 一并删除，scratch 目录
改为按 task root 哈希命名。

Prep 失败、超时或崩溃都不阻塞 writer。

## Writer 使用

报告在 artifact staged 之后写入 `task_prep/PREP_REPORT.md`，并原文内联到 writer 首轮 prompt。
交接文字说明三件事：运行时状态是真实的且已就位；其余内容是补充材料，题面和 `input/` 优先；
合同清单不是评分标准，可能不完整。writer 不需要回写采纳状态，采用链由 transcript 事后判断。

## v18 六题实测结果

`exp_prep_v18_six_pair.yaml` 于 2026-07-21 在 pgl 跑完，base 与 prep 同 endpoint、同 task
version、同轮交错，各六题，日志在 `.logs/ale/prep_v18_six_pair`。

### Prep 产出

| 题目 | 环境 | 清单 | findings | artifact | input token | 耗时 | dropped |
|---|---|---:|---:|---:|---:|---:|---|
| Agora | ready | 22 | 5 | 0 | 35,100 | 220 s | 报告截断 |
| Digital | partial | 24 | 6 | 1 | 36,952 | 296 s | 2 个 `.toml` 路径非法，截断 |
| SEC | ready | 19 | 4 | 1 | 75,635 | 296 s | 1 条 writer_action 越界 |
| Variant | ready | 24 | 5 | 2 | 106,197 | 582 s | 截断 |
| BPMN | blocked | 24 | 5 | 2 | 334,767 | 796 s | 截断 |
| Bias | ready | 20 | 3 | 0 | 359,161 | 996 s | 2 条越界，1 个 artifact 读不到 |

生成率 6/6，v17 是 0/6。四题打满 24 条清单上限，四题报告触到 12,000 字符被截断。成本方差
一个数量级，35k 到 359k input token。

BPMN 的 `blocked` 是 v17 协议下拿不到的那类事实：prep 自己在 `/tmp/ale-docker.sock` 起了
vfs 私有 daemon，拉到 Flowable 镜像层后卡在 `unshare: operation not permitted`，据此判定这个
嵌套 VM 跑不了镜像层。v11 复盘里两臂在 Docker 从未启动的情况下都编出 67/67 pass，现在
writer 开题就知道运行时自检这条路是假的。

### 配对分数

| 题目 | base | prep v18 | 差 |
|---|---:|---:|---:|
| SEC 10-K | 0.6609 | 0.9235 | +0.2626 |
| Bias | 0.0 | 0.0 | 0 |
| BPMN | 0.8438 | 0.8295 | -0.0143 |
| Digital | 0.9042 | 0.8708 | -0.0334 |
| Variant | 1.0 | 0.7930 | -0.2070 |
| Agora | 0.6900 | 0.3452 | -0.3448 |

均分 0.68315 对 0.62700，差 `-0.05615`，sd `0.20645`，`t=-0.666`，n=6。

按预注册判据：生成率一条通过；"清单条目到分项提高的完整链"没有出现；harm rate 明显超出
噪声区间。因此这一轮不支持扩到 26 题。

### Agora 的 -0.3448：清单造成的定向优化

用题目原 scorer（`tasks/legal/agora_governance_classify_instance_1/scripts/score_outputs.py`）
对两臂输出重跑，分类标签几乎没变，三份文档里两份的 `scope_f1` 完全相同。整个下跌来自
`evidence_gate`：

| 文档 | base pass_rate / gate | prep pass_rate / gate |
|---|---|---|
| 768 | 0.846 / 1.0 | 0.571 / 0.5 |
| 2047 | 0.909 / 1.0 | 0.636 / 0.5 |
| 1293 | 0.667 / 0.5 | 0.333 / 0.5 |

scorer 的规则是 `pass_rate >= 0.8` 给 1.0 否则 0.5，再乘到三个分项上，所以分数正好腰斩。

逐条验证失败原因：prep 臂的引文**全部通过原文子串检验**，无一例外。失败在另外两个条件
上，scorer 要求引文至少 `MIN_EVIDENCE_WORDS = 5` 个词，并且必须包含该类目的关键词。base
的引文中位数 28 词、最短 9 词、没有一条低于 8 词；prep 臂中位数 11 词、最短 3 词、7 条低于
8 词，例如 `frontier AI models` 只有 3 个词。

prep 清单的第 7 条和第 10 条反复要求"evidence 必须是缓存原文的精确子串"，writer 于是把引文
压缩成能保证逐字对上的最短片段。它优化了清单点名的那一维，代价是清单没提的两维。

这是合同清单作为**部分阅读**的结构性风险，不是这份清单写错了。任何只读公开题面的清单都
无法知道 `MIN_EVIDENCE_WORDS` 和关键词表的存在，而一旦清单强调某个维度，writer 就会在
未被点名的维度上让步。清单越具体、越有约束力，这个效应越强。

### 一条历史结论的纠正

1293 的 `legislative_status` 真值是 `Hard Law`。这一轮 base 答对，prep 臂答成 `Other`。
[EVOLUTION.md](EVOLUTION.md) 和 26 题 canary 记录中把 v15 Agora prep "将 1293 标为 `Other`"
列为正向采用链，该判断是错的，它是一次伤害。

### 采用链：三题 artifact 零调用

- SEC：prep 把运行时配好并给出已验证命令，writer 的 29 次 exec 里
  `ale-task-prep`、`UV_PROJECT_ENVIRONMENT`、`python_with_task_deps`、`manifest_lookup`
  各出现 0 次。分数上去的真实原因是这一轮 writer 自己想到去 `data.sec.gov` 的 XBRL
  companyfacts API 取权威财务数据，base 臂没走这条路（两臂都用 pdftotext，`data.sec.gov`
  在 base 轨迹里 0 次）。**+0.2626 不能归因给 prep。**
- Variant：prep 交付了官方 severity 排序和五个 indel 位点，`vep_rules.py` 与
  `VEP_SEVERITY` 在 writer 轨迹里各 0 次。最终 0.7930 与历史 base、v15、v17 三次完全相同，
  是"未修 indel lookup"的稳定取值。
- Digital、BPMN：差值都在历史噪声区间内。

报告内联保证了 exposure，没有保证 writer 会去执行 staged 的文件。这与 v15 26 题的老结论
一致，v18 没有改善它。

## 已知未解决的问题

1. 合同清单是对题面的**部分**阅读，没有机械手段验证它是否完整。Agora 给出了这个风险的
   第一份实测证据：清单条目本身正确且有 locator，writer 也照做了，但它优化被点名的维度
   （引文必须是原文精确子串）时牺牲了未被点名的维度（引文长度和关键词），单题 -0.3448。
   危害不来自清单写错，来自清单不完整加上 writer 会照着清单优化。v20 把清单变成可执行的
   自检脚本会**放大**这个效应，因为脚本比文字更有约束力：writer 会跑到脚本 100% 通过为止，
   而脚本编码的仍是同一份部分阅读。这一点尚无实测数据。
2. 清单和 evaluator 的检查项都来自同一份公开题面，两者接近时有 Goodhart 风险。约束是清单
   只能由冻结的题面和 `input/` 编译，不能从 writer 的候选产物采集，但这条目前靠 prompt。
3. Prep 在沙箱里的修改没有回滚机制。装错包或改错配置会直接影响 writer。
4. Prep 独立于 writer 运行，无法知道 writer 本来是否会自己发现同一事实。真正的边际价值只能
   用配对重复估计。
5. 报告内联仍然产生显著性，锚定风险只能降低不能消除。
6. v19 起 prep 可以交付面向草稿的自检脚本（writer 自跑，无任何裁决权，不需要 Verifier 的
   冻结与审计机制）。它的采纳率、正确率和危害率还没有配对测量；脚本本身错了会把 writer
   引向错误修改，这个风险与合同清单错误同源，靠"题面与 `/input` 优先"的权威顺序兜底。
   v18 的采用链数据说明前提尚未成立：三题交付的 artifact 全部零调用，`self_check` 是否
   因为报告里单列一节、给出确切命令就能提高调用率，是 v20 待验证的核心假设。
7. 报告 12,000 字符上限在 v18 六题里对 4 题构成绑定约束，清单上限 24 条也有 4 题打满。
   v20 新增的 Self-check 一节会继续挤占同一预算。上限未随 v19/v20 调整。
8. 成本没有和收益挂钩。v18 六题的 prep input token 从 35k 到 359k 相差一个数量级，最贵的
   Bias（359k）产出 0 个 artifact，且该题两臂历史均为 0。

## 验证

```bash
.venv/bin/python -m pytest -q \
  tests/test_task_specific_prep.py tests/test_analyze_factorial.py
.venv/bin/ruff check \
  ale_run/agents/ale_claw/task_prep.py \
  ale_run/agents/ale_claw/deployer.py \
  ale_run/agents/ale_claw/config.py \
  harness/run/analyze_factorial.py \
  tests/test_task_specific_prep.py
```

2026-07-21 在 pgl（`~/ale/fable-check` 独立副本，不触碰正在跑实验的 `~/ale/agents-last-exam`）：
v20 定向套件 `test_task_specific_prep.py` 26 passed（self_check 三个新用例）、
`test_contract_crosscheck.py` 4 passed、`test_analyze_factorial.py` 9 passed，改动文件
Ruff passed。全量 `pytest -q` 为 1087 passed、4 skipped，真实失败集合（ale_claw 工具/会话
测试 9 个、`test_spec_keyless.py` 3 个）与未改动的原仓库逐项一致，v19/v20 没有引入新失败。
副本上另有 2 个 `FileNotFoundError` 失败来自副本未拷贝 `secret/`、`tasks/` 数据目录，与
代码无关。
