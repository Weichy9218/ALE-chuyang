# FABLE.md — harness 优化记录（2026-07-21）

本文按时间记录两轮改动。第一轮交付预提交自检（v15）和 Prep 边界修正（v19）；第二轮交付
Verifier 信号率修正（v16）、Prep self-check 一等公民化（v20）、机械合同对账和一次代码清理。
每轮都含动机、实现、决策、验证。当前协议：`task-prep-v20`、`public-verifier-v16`。

---

# 第一轮：预提交自检与 Prep 边界修正

本文记录一次针对 harness 的两项优化的动机、实现、决策和验证，对应代码协议
`task-prep-v19` 和 `public-verifier-v15`。改动只在 batchcom 的
`/home/dataset-local/wcy/ALE-chuyang` 完成；pgl 的 `~/ale/agents-last-exam`
主仓库没有同步，正在跑的 v18 六题配对实验不受影响。何时把 v19/v15 同步到 pgl
由实验负责人决定。

## 动机

两项改动都来自同一个判断：Prep 和 Verifier 只能通过改变 writer 在提交前的行为产生分数，
而当前系统在"可行动信号到达 writer 的时机"上有结构缺陷。支撑数据来自
[results/latest](results/latest/)（v10 协议、26 题四臂）：

- Verifier 的全部测量在 DONE 之后到达。52 个 verifier run 的 repair 数为 0；344 条 check
  中 180 条 pass 的确认信息在 DONE 后毫无用处；写满步数预算的 writer 收到硬失败也没有步数
  可修（`writer_step_limit` 这个 stop_reason 就是该问题的记录）。
- 最大的失分面是合同覆盖（BPMN 的 67 条 producer-consumer 约束、CRF4 的 57 行 mapping），
  这类义务机械可查，但 writer 只拿到一份 t=0 注入的文字清单，没有任何可执行的自检回路。
  [PREP.md](PREP.md) 的原话："writer 知道要做什么，缺的是在提交前确认自己覆盖了多少条的能力"。
- v18 的 `_targets_writer_output` 字符串检验恰好把"可执行自检"这条路封死了（详见下文）。

## 改动 1：预提交自检（public-verifier-v15）

### 设计

冻结的意义是"标准不随 output 变"，它不要求"只在结束后运行"。v15 保持标准、隔离、权威
逻辑完全不变，只把执行时机开放给 writer：

- Verifier 开启且 `verifier_writer_checks > 0`（默认 2，范围 0 至 8）时，writer 的工具表
  增加一个 `verify` 工具。调用一次即对当前 `output/` 做只读快照（命名空间
  `snapshot-writer<n>`，与 DONE 后的 `snapshot-<i>` 分开），在同一 Landlock/seccomp 沙箱里
  双次运行完整冻结测试包，返回同一份四类报告，措辞换成 pre-submission（明确
  "all-pass 只覆盖公开可测部分，不是完成信号"）。
- 冻结包在 writer 首次调用时才 stage 进 VM。writer 不调用，测试内容就不落盘，暴露面与
  v14 相同。
- `execute_test_suite` 的既有完整性检查每次照常执行：suite hash、script hash、公开来源
  hash、快照前后 tree hash。预运行无法改变任何判准。
- writer 在主运行文本里写的 `VERIFIER_DISPUTE <check>` 与复核轮同协议解析，进入同一个
  dispute 集合。
- 预运行不消耗 `max_review_rounds`；DONE 后的快照、重跑、复核循环原样保留。
- fail-open：套件未冻结成功时工具报告不可用并给出原因；单次调用崩溃返回错误文本且不计入
  次数；跑完但 overall 为 error 的运行计入次数（防止在损坏环境上无限重试）。

### 实现清单

| 文件 | 内容 |
|---|---|
| `ale_run/agents/ale_claw/verifier_precheck.py` | 新增。`WriterVerifyTool`（BaseTool，name=`verify`）：可用性状态机、次数预算、lazy staging、快照+执行+报告、host/VM 双份记录 |
| `ale_run/agents/ale_claw/verifier.py` | 协议升 v15；`build_feedback_prompt` 增加 `pre_submission` 参数，只替换收尾的 WRITER INSTRUCTION 段 |
| `ale_run/agents/ale_claw/verifier_runtime.py` | `snapshot_output` 的 `iteration` 接受受校验的字符串标签；新增通用 `stage_verifier_report`（deployer 与工具共用） |
| `ale_run/agents/ale_claw/deployer.py` | 构造并注册工具（在 `disabled_tools` 过滤之前，可被显式禁用）；build 完成后 `bind_suite`/`mark_unavailable`；套件冻结成功时在 solver prompt 末尾加一段说明；主运行文本纳入 dispute 解析；`verifier_meta.json` 增加 `writer_checks_max`、`writer_checks_used`、`writer_check_overalls` |
| `ale_run/agents/ale_claw/config.py` | `verifier_writer_checks: int = 2`，校验 0 至 8 |
| `harness/run/presets.py`、`harness/run/launch.py` | preset 显式写出 `verifier_writer_checks`；settings 键 `verifier.writer_checks` |
| `harness/run/analyze_factorial.py` | behavior 表新增 `verifier_writer_checks_max/used`、`verifier_writer_check_overalls`、`verifier_writer_check_hard_mismatches` 列，来源是 meta 和 `verifier_writer_check_*.json` |

产物命名：host `verifier_writer_check_<n>.json`，VM `verifier/writer_check_<n>.json`。与
`verifier_round_*.json` 的 glob 不冲突，旧分析脚本不受影响。

### 决策记录

- **writer 主动调用，而不是 harness 在固定检查点自动运行。** writer 知道草稿何时完整；
  固定检查点会在半成品上制造大量无意义的 hard mismatch，消耗 writer 注意力，也污染
  "调用后是否修复"这个采纳指标。
- **没有给 DONE 后复核轮增加独立步数预算。** 那会改变 writer 步数预算的实验语义，破坏与
  历史臂的可比性；且预提交自检本身就是对 `writer_step_limit` 问题的直接解法，反馈在预算
  内到达。如果 v15 实验显示 DONE 后仍有大量硬失败挤在无预算处，再单独评估这项。
- **测试内容提前暴露被接受为有意的协议变化。** v14 的复核轮本就向 writer 展示来源、命令、
  expected 并要求复现冻结测试；v15 只是允许更早。Goodhart 面限于公开可测部分，
  `coverage_gaps` 继续声明未覆盖面。这一条写进了 ARCHITECTURE.md 的信任边界表。
- **计数策略。** 崩溃不计次（基础设施问题不该消耗 writer 的预算），执行完成的 error 计次
  （防止损坏环境上的无限重试循环）。

## 改动 2：Prep 边界修正（task-prep-v19）

### 问题

v18 用 `_targets_writer_output` 字符串匹配强制"Prep 不检查候选 output"这条边界，产生三处
误伤（行号为 v18 代码）：

1. 合同条目的 `check` 字段含 `output/` 即被静默清空（`task_prep.py:342`）。
   "writer 如何验证"几乎必然引用交付物路径，最有用的条目恰好活不下来。
2. `writer_action` 含 `output/` 的 finding 整条丢弃（`task_prep.py:371`）。
3. artifact 内容含 `output/` 字样即拒收（`task_prep.py:509`），封死了 prep 交付自检脚本的路。

关键事实：prep 运行时 `output/` 尚不存在，prep 在运行期检查候选产物在物理上不可能。字符串
检验从未强制过运行期行为，只是在净化 writer-facing 文本，而要防的"prep 替 writer 预定最终
取值"由 prompt 规则约束，与是否提到路径无关。这与 v17 的
`missing_impact_coverage_evidence`（字面串检验丢掉整份已验证报告）是同一种病，
[PREP.md](PREP.md) 对 v17 的诊断原文适用。

### 修法

- 删除 `_targets_writer_output` 及全部四处调用（env commands、contract check、finding
  writer_action、artifact 内容）。artifact 仍拒收含 NUL 的二进制内容。
- 系统 prompt 反向鼓励：合同条目的 check 应当是"writer 可对自己 `output/` 草稿运行的确切
  命令或比较"；新增一类推荐 artifact，可运行的合同自检脚本，writer 对草稿反复运行，prep
  只在自己 scratch 里的合成小样上测试它，从不在真实任务根上运行。
- "Never read, write, lint, score, or check the writer's `output/`" 的运行期边界原句保留。

这项改动与改动 1 合成一个闭环：prep 交付无权威的自检工具（随时可跑、不消耗 verify 次数），
verifier 提供有权威分级的冻结测量（次数有限），writer 在提交前两层都能用。

## 验证

改动基于的 batchcom 仓库与 pgl 主仓库在全部相关文件上逐字节一致（sha256 对照过
task_prep/verifier/verifier_runtime/deployer/config/presets/launch/analyze_factorial 和
测试文件）。验证在 pgl 的独立副本 `~/ale/fable-check` 上进行（只拷贝 `ale_run`、`harness`、
`tests`、`pyproject.toml`、`uv.lock`，用 `PYTHONPATH=$PWD` 压过原仓库 venv 的 .pth 注入，
已用 `verifier_precheck.__file__` 确认 import 解析到副本），不触碰正在跑实验的主仓库。

定向套件（2026-07-21）：

```text
tests/test_task_specific_prep.py   23 passed          （v18 为 22：改 2 个边界用例，净增 1）
tests/test_verifier.py             24 passed 1 skipped（未改动，回归通过）
tests/test_verifier_precheck.py     7 passed          （新增）
tests/test_analyze_factorial.py     9 passed          （新增列为可空追加，旧夹具通过）
ruff check（全部改动文件 + 测试）  All checks passed
```

全量 `pytest -q tests/`：1074 passed、4 skipped、14 failed。其中 12 个失败与未改动的原仓库
在同一命令下逐项一致（`tests/ale_claw/` 工具与会话测试 9 个、`tests/test_spec_keyless.py`
3 个，均为既有的 secrets/tools 重构遗留），另 2 个（`test_baked_in_sandbox`、
`test_qemu_provider`）是副本未拷贝 `secret/`、`tasks/` 数据目录造成的 `FileNotFoundError`，
与代码无关。结论：v19/v15 没有引入新失败。

新增测试覆盖的行为：绑定前不可用与原因透传、次数预算与耗尽提示、staging 只做一次、
pre-submission 反馈只替换收尾指令段、崩溃不计次且不抛出、记录落盘（含四类归属）、快照标签
校验、config 取值范围、`output/` 引用在 check/writer_action/commands/artifact 四处全部保留、
NUL 内容仍拒收。

## 下一步（未实施，供实验设计）

进入配对实验前，先用机制 canary 回答四个问题，每题都有确定读数，不依赖 k=1 的分数：

1. `verify` 调用率和时机：writer 是否调用、在第几步、快照是否非空。
2. 调用后行为：output 是否变化、hard mismatch 数在下一次运行是否下降。
3. DONE 后一轮的 hard mismatch 是否比 v14 显著减少（预期趋于 0）。
4. prep 自检脚本：交付率、writer 运行率、脚本判断与官方分解的一致率。

对照数据源：`verifier_meta.json` 新字段、`verifier_writer_check_*.json`、behavior 表新列、
transcript 采纳链。六题选择可沿用 v18 复测的六题（Variant/Agora/SEC/Bias/BPMN/Digital），
它们覆盖合同覆盖与运行环境两个主要失分面。

回滚：两项改动分别以协议串 `task-prep-v19`、`public-verifier-v15` 标识；
`verifier_writer_checks: 0` 可单独关闭预提交自检而保留 v15 其余行为（其余行为与 v14 等价）。

---

# 第二轮：信号率、self-check 一等公民、合同对账与清理

第一轮之后的复盘明确了两个辅助 agent 的定位，第二轮据此实施：

- **Prep 的产出只有变成 writer 提交前执行的动作才有价值。** 环境状态通过共享沙箱无损转移；
  合同知识的最高保真载体不是散文清单，而是 writer 可以反复运行的程序。所以 self-check 从
  "prompt 里鼓励的一类 artifact"升为输出结构的一等字段。
- **Verifier 的价值受限于"可行动信号的产生率"。** v10 数据里 344 条 check 有 156 条没运行
  就死在 source gate（ambiguous 145 条），而定位失败里行号数错这一类是纯机械错误。修正
  信号率不需要动任何权威判定。

## 改动 3：Verifier 信号产生率（public-verifier-v16）

三处修正，全部只依赖机械证据：

1. **quote 自动重定位**（`verifier.py` 的 `_LOCATE_SOURCE` 与 `_relocate_in_text`）。quote
   是事实本体，`lines:N-M` 只是坐标。引用行窗未命中且 quote 在全文恰好出现一次时，机械反查
   正确行号并修正 locator，`locate_evidence` 记录 "corrected from ... to ..."；行号越界不再
   当场报错，同样进入重定位；quote 出现多次或不存在才算失败。JSON Pointer 不做重定位。
   冻结包里存修正后的坐标，执行前的 `_verify_sources` 复验因此保持一致。
2. **一轮机械修复**（`build_test_suite`）。定位仍失败的 source 把失败清单（check、path、
   locator、quote、机械证据）发回一个新 builder 会话（label
   `verifier-builder-locate-repair`），指令限定为修 quote/路径或把该要求降为 unverifiable，
   其余字段原样保留。修复产物重新 lint、重新定位，失败数严格减少才采用，否则保留原候选。
   证据纯机械，不含 Writer/Prep/隐藏信息，独立性不受影响；成本是最多一次额外 LLM 调用，
   且只在有失败时发生。
3. **ambiguous 以 advisory 运行**（`verifier_runtime.execute_test_suite` 的分派）。旧规则
   `source_status != supported 或 entails 为假 → 不运行`改为：只有 `missing`（定位失败）和
   `contradicted`（公开材料反驳）不运行；`ambiguous` 和 entails 不足的检查照常执行，差异
   进入 `review_items`，反馈里新增来源侧 caveat（引用 Auditor 的 source_evidence）。硬权限
   授予条件（supported + entails + checker 对齐 + 可复现 + 环境健康 + 非 simulation）逐字
   未变。

## 改动 4：Prep self-check 一等公民（task-prep-v20）

- 输出结构新增 `self_check = {command, artifact, covers}`；报告渲染独立 "Self-check" 节，
  位置在 Runtime 之后、合同清单之前，给 writer 一条确切命令。机械校验两条：command 非空、
  artifact 必须已声明；staging 失败时整节撤下、记入 `dropped`。
- `normalize_prep_bundle` 拆成解析与渲染（新函数 `render_prep_report`），结构化合同条目
  进入 `TaskPrepResult.contract` 与 `task_prep_meta.json`。v18 遗留的"artifact 缺失时字符串
  替换报告行"hack 删除，统一为带 `unavailable` 集合的重新渲染。
- prompt 相应更新：合同条目多于几条机械项时，明确要求把清单实现成一个自检脚本并注册到
  `self_check`。

与 `verify` 工具的分工：self-check 随时可跑、不限次数、零权威、不进评审记录，供 writer 边写
边用；`verify` 是冻结标准的正式测量，次数有限、有权威分级、进 `verifier_meta`。

## 改动 5：机械合同对账（新模块 `contract_crosscheck.py`）

prep 清单与冻结测试是对同一公开表面的两次独立阅读，此前从不比对。语义对齐无法用代码可靠
完成，但双方都机械地声明了"引用了哪些公开文件"：prep 条目的 locator 归一化成
`task_prompt | input/... | software/...`，与冻结测试全部 sources 的 path 集合做双向差集。
结果写入 `contract_crosscheck.json`，非空时把一段简短说明注入 writer 初始 prompt：

- "冻结测试引用而清单没有条目"的文件，提示 writer 清单可能漏读了那里的义务；
- "清单有条目而无测试覆盖"的文件，提示提交前只有自检覆盖它们；
- 明示只比文件覆盖、不判对错、题面与 `/input` 仍然最高。

只在 prep_verifier 臂发生（其余臂缺一方），零 LLM 成本，失败只记日志。analyzer 的 behavior
表新增 `prep_self_check`、`crosscheck_shared/prep_only/verifier_only_paths` 列。

## 改动 6：清理

- 删除孤儿模块 `ale_run/agents/ale_claw/_cache_lock.py`（v18 删缓存后无任何引用）。
- 删除 `VerificationResult.failures` 别名属性（无调用方）。
- 顶层 `docs/README.md` 重写：修正"prep/verifier 均默认关闭"等过时陈述，把索引里指向已
  归档文件的断链改指 `docs/archive/`，`harness_design.md`（pi 干预原型，代码不在本仓库）
  和 `progress_2026-07-13.md` 移入 `docs/archive/`。
- `harness/COGNITION.md` 的 Prep/Feedback 节从 v5 时代改写到 v20/v16 现状；
  `harness/run/README.md` 的 settings 表更新 `max_review_rounds`/`writer_checks`。

## 第二轮验证

同一 `~/ale/fable-check` 副本流程。定向套件：prep 26 passed、verifier 30 passed 1 skipped、
precheck 7 passed、crosscheck 4 passed、analyzer 9 passed；改动文件 ruff 全绿（对
`ale_run/agents/ale_claw/` 整目录扫描得到的 61 个错误与未改动的原仓库逐字节相同，属 harness
子树存量问题，未纳入本轮）。全量 pytest 1087 passed、4 skipped、14 failed，失败集合与第一
轮完全相同（12 个存量 + 2 个副本数据缺失），零新增失败。

新增测试覆盖：唯一 quote 的错误行号重定位、越界行号重定位、重复 quote 不重定位、修复轮的
触发/提示词内容/采用判据、ambiguous 检查真实执行并落入 review_items、contradicted 不运行、
反馈中的来源 caveat、self_check 的渲染/声明校验/staging 失败撤节、locator 归一化、对账差集
与注入文案、对账一致时静默。

## 第二轮之后的机制 canary 追加读数

在第一轮四个问题之上追加：

5. 重定位命中数：`locate_evidence` 含 "corrected from" 的来源数。
6. 修复轮触发率与采用率（`verifier-builder-locate-repair` 出现次数、采用与否）。
7. ambiguous 检查的运行数、differ 数、writer 采纳数——直接回答"放开 source gate 是信号
   还是噪声"。
8. 对账注入率与两个方向的路径数（behavior 表新列）；writer 是否按提示重读了
   verifier_only 文件。
9. self_check 交付率、writer 运行次数、运行后 output 是否变化。

回滚：`task-prep-v20`、`public-verifier-v16` 协议串标识本轮；对账随 prep contract 为空或
verifier 关闭自动失效，无独立开关。
