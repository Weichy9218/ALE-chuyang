# Task Prep / Skills v2 中期分析

快照时间：2026-07-19 20:52（Asia/Shanghai）。实验仍在 pgl 运行；本报告冻结当前
`base`、`skills` 和已完成的 `prep` 结果，`skills+prep` 尚无已评分单元。后续终版使用
同一脚本覆盖更新，不把本报告中的缺失格当作 0 分。

机器可读快照：[`scores.csv`](task_prep_skills_v2_partial/scores.csv)、
[`behavior.csv`](task_prep_skills_v2_partial/behavior.csv)、
[`summary.json`](task_prep_skills_v2_partial/summary.json)。复算脚本：
`harness/run/analyze_factorial.py`。

## 结论先行

1. 新版短 skills 没有正向总体信号。25 个有效配对的平均差为 **-0.0161**，
   `sd=0.0960, se=0.0192, t=-0.84`；3 题提高、15 题不变、7 题降低。
2. prep 当前也精确接近零。24 个有效配对平均差为 **-0.00125**，
   `sd=0.0740, se=0.0151, t=-0.08`；4 提高、16 不变、4 降低。它没有复现旧报告中
   TCGA、FluSight、CRF4、SAP 的正收益；Variant 的稳定负收益再次复现。
3. 旧 TCGA `+0.16` 不是可靠的 skill 贡献。公开 contract 允许灵活 `ph_test` 结构；
   本轮 base 和 skills 都给出完整且数值有效的 Schoenfeld 检验，只因隐藏 parser 不接受
   `variables` / `results` 包装而同时被 cap 到 0.84。旧 skills 恰好用了直接键拿到 1.0。
4. 两个 skills 的核心限制不是篇幅，而是没有独立 outcome signal。SEC 的 schema、完整性、
   determinism 三臂都满分，但财务数值准确率没有提高；FluSight 三臂都满足 212 行结构，
   skills/prep 的真实 WIS 和 MAE 反而更差。
5. 新正文确实降低了旧 skills 的开销，但仍是净成本：相对同轮 base，skills 平均多
   106 秒、2.72 steps、15.7K main input tokens 和 `$0.0365`，得分没有收益。
6. skills 应定位为 writer 可按需调用的可复用能力包，不是 verifier。独立 verifier 应在
   harness 编排层使用 fresh context、只读 artifact snapshot、公开 source anchor 和结构化
   failure feedback；详细设计见 [VERIFIER.md](VERIFIER.md)。

## 总体统计

| arm | 当前状态 | score n | 当前均分 | 配对 n | 对 base 平均差 | sd / se / t | 正 / 平 / 负 |
|---|---|---:|---:|---:|---:|---:|---:|
| base | 25 completed, PE eval failed | 25 | 0.6068 | - | - | - | - |
| skills | 25 completed, PE eval failed | 25 | 0.5907 | 25 | -0.0161 | 0.0960 / 0.0192 / -0.84 | 3 / 15 / 7 |
| prep | 24 completed, Digital AB running, PE eval failed | 24 | 0.5892 | 24 | -0.00125 | 0.0740 / 0.0151 / -0.08 | 4 / 16 / 4 |
| skills+prep | 5 active, 0 scored | 0 | - | 0 | - | - | - |

不同臂的“当前均分”分母不完全相同，不能横向相减；配对差才是当前有效比较。PE 的
solver 已完成，但 GPT gateway 不支持题目 evaluator 所调用的 `gpt-5-mini`，因此 score
为空。四臂结束后会在支持该模型的 Boyue endpoint 只 `--resume` PE 的四个失败单元。

## 资源统计

| arm | completed n | duration 秒 | steps | LLM turns | tools | main input | output | main cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 25 | 990.5 | 31.04 | 11.40 | 18.64 | 250,291 | 6,679 | $0.4941 |
| skills | 25 | 1,096.6 | 33.76 | 12.60 | 20.16 | 265,947 | 6,940 | $0.5306 |
| prep | 24 | 1,143.1 | 32.42 | 11.88 | 19.54 | 284,301 | 6,282 | $0.5246 |

`prep` 的 run duration 已包含研究时间，但 `run.json.usage` 不包含 prep agent tokens。
26 份报告全部已生成，`empty=0`：研究本身合计 7,587 秒、4,672,864 input tokens、
167,549 output tokens、185 LLM turns、305 tools；平均报告 12,209 字符。无净得分收益时，
这是不可忽略的成本，也说明 prompt 中的 `NO_TASK_SPECIFIC_PREP` gate 没有真正生效。

skills 的 26 个单元全部在 step 2 加载一次方法：24 次 `deliverable-contract`、2 次
`evidence-audit`；其中 25 个已评分单元为 23 / 2。弱效果不能归因为“模型没读 skill”，
更准确的解释是 deliverable 路由覆盖了几乎所有题，而方法本身不增加 source truth。

## 逐题分数

`ΔS` 为 skills-base，`ΔP` 为 prep-base。`-` 表示快照时尚未得到有效 score。

| task | base | skills | ΔS | prep | ΔP |
|---|---:|---:|---:|---:|---:|
| American option | 1.0000 | 1.0000 | 0 | 1.0000 | 0 |
| BPMN category | 0.0000 | 0.0000 | 0 | 0.0000 | 0 |
| BPMN supply | 0.8252 | 0.8195 | -0.0057 | 0.8405 | +0.0153 |
| Digital AB | 1.0000 | 1.0000 | 0 | - | - |
| Digital audience | 0.8667 | 0.7245 | -0.1422 | 0.9042 | +0.0375 |
| Financial statement | 1.0000 | 1.0000 | 0 | 1.0000 | 0 |
| Internal employee | 1.0000 | 1.0000 | 0 | 1.0000 | 0 |
| Legal MA | 0.0000 | 0.0000 | 0 | 0.0000 | 0 |
| LLM privacy | 0.5000 | 0.5000 | 0 | 0.5000 | 0 |
| PE screening | - | - | - | - | - |
| SEC 10-K | 0.6394 | 0.6289 | -0.0105 | 0.6313 | -0.0081 |
| SSE northbound | 0.6667 | 0.3333 | -0.3333 | 0.6667 | 0 |
| PDE grading | 0.5650 | 0.6950 | +0.1300 | 0.7132 | +0.1482 |
| MARC | 0.2000 | 0.2000 | 0 | 0.2000 | 0 |
| Moodle | 0.9500 | 0.8850 | -0.0650 | 0.9500 | 0 |
| CRF1 | 0.0000 | 0.0000 | 0 | 0.0000 | 0 |
| CRF4 | 0.6124 | 0.4282 | -0.1842 | 0.4665 | -0.1459 |
| CT geometry | 0.0000 | 0.0000 | 0 | 0.0000 | 0 |
| Epidemiology | 1.0000 | 1.0000 | 0 | 1.0000 | 0 |
| FluSight | 0.7757 | 0.7173 | -0.0585 | 0.7172 | -0.0585 |
| Bias audit | 0.0000 | 0.0000 | 0 | 0.0000 | 0 |
| SAP | 0.2500 | 0.3500 | +0.1000 | 0.2500 | 0 |
| TCGA LUAD | 0.8400 | 0.8400 | 0 | 0.8400 | 0 |
| Variant annotation | 0.9990 | 0.9990 | 0 | 0.7930 | -0.2060 |
| Agora | 0.4806 | 0.6476 | +0.1671 | 0.6681 | +0.1876 |
| Legal fees | 1.0000 | 1.0000 | 0 | 1.0000 | 0 |

## 重点题机制

### TCGA LUAD：旧正收益是隐藏 schema 偶合

本轮 base / skills / prep 全为 0.84，旧 skills 的 1.0 没有复现。三个新 run 的 cohort、
表达值、分组、Cox 系数和 log-rank 基本正确；base 与 skills 的 uncapped score 都是 0.98。
唯一 gate failure 是 `ph_test_valid=false`。

公开 `output_requirements.txt` 明写 `ph_test: structure is flexible`。base 使用
`ph_test.variables`，skills 使用 `ph_test.results`，两者都有 KRAS、age、stage 和 GLOBAL
的 Schoenfeld 统计量；隐藏 evaluator 只解析 `per_variable`、`table` 或直接键。旧 skills
恰好生成直接键，因而多了 0.16。这应修 evaluator 的 normalization 或公开唯一 schema，
不应把隐藏可接受形状写入 skill。TCGA 仍适合独立 verifier，因为 GDC 是可重取的公开
source truth；但 verifier 应验证语义等价结构和 record trace。

### SEC 10-K：contract 已满，缺的是语义 source trace

| arm | score | schema | metadata | financial accuracy | cross-validation | completeness | determinism |
|---|---:|---:|---:|---:|---:|---:|---:|
| base | 0.6394 | 1.0 | 0.984 | 0.732 | 0.71 | 1.0 | 1.0 |
| skills | 0.6289 | 1.0 | 0.990 | 0.656 | 0.83 | 1.0 | 1.0 |
| prep | 0.6313 | 1.0 | 0.990 | 0.734 | 0.62 | 1.0 | 1.0 |

新版 skill 的临时检查成功保证 schema、文件、确定性，且不再把 checker 留在 output；
但这些维度 base 已经饱和。真正失分是 PDF 表格中的财务值。有效 verifier 应在 writer
之外从公开 PDF 预注册抽样 filing/field，记录页码、表格行、单位和输出值，再做确定性
比较；“JSON 全绿”不能替代这个信号。

### FluSight：未来 outcome 在作答时不可验证

| arm | score | mean WIS 95（ex-US） | coverage 95 | MAE（ex-US） |
|---|---:|---:|---:|---:|
| base | 0.7757 | 87.423 | 0.8606 | 208.19 |
| skills | 0.7173 | 110.214 | 0.9663 | 259.73 |
| prep | 0.7172 | 110.236 | 0.7837 | 253.20 |

三臂都交付 212 行且通过 key、quantile、非负等结构要求。skills 多花约 418 秒后得到更宽
区间，但真实 WIS/MAE 更差；prep 几乎得到同一分数。2024-12-14 之后的真实住院 outcome
当时不可见，因此 skill 只能确认 contract，不能给预测质量反馈。若交付可执行模型，可用
预注册 rolling-origin backtest 作为明确标注的 proxy；若只交静态未来预测，不应启动
以“质量通过”为名的 LLM repair loop。

### Variant：prep 的稳定回归

base 与 skills 都是 0.999，prep 再次精确复现 0.793。prep 报告把 VEP normalized
allele 作为 AF key，覆盖了 task-local manifest 的 staged convention，造成 3 个 AF 错误；
reportable flag 少对 1 行，触发 20 分 all-or-nothing 子项丢失。v5 prompt 已写“task-local
优先”，但 LLM 没遵守，说明这个优先级不能只靠文字约束。prep finding 在注入前至少要
附 task-local source anchor，并由机械 conflict check 拒绝与 manifest 相冲突的上游规范。

### CRF4：旧 uplift 是跨日期 base 噪声

旧报告用历史 base 0.450 对新 prep 0.615，看起来约 +0.165；本轮同日 base 已变为
0.6124，而 prep 是 0.4665，方向反成 -0.1459，skills 为 0.4282。旧“prep 找到真实
Define-XML 所以提分”的机制描述不能支撑因果结论；信息可能有用，但一次 rollout 的
最终策略波动更大。必须用同轮 base，且至少 `k>=3`。

### Agora：有正向机制，但 prep 越界成第二个 solver

base 0.4806，evidence-audit skills 0.6476，prep 0.6681。skills 提高了多份文档的 evidence
pass rate、lifecycle 和 technical-scope 覆盖，这是当前最像 evidence-audit 正向作用的一题，
值得重复。可它仍只是单次样本；同一 skill 在 Legal MA 上增加 steps/tokens 后仍为 0。

Agora prep 报告则直接判断三份具体文档的法律状态、scope 和 lifecycle，并摘出决定性证据，
违反“read-and-judge 无工具/版本增量就 empty”的角色边界。它的增益不能证明 prep 设计
正确，只证明第二个 solver 可能帮助第一个 solver。若保留 prep，任务类型 gate 应由
orchestrator 硬执行，不应继续依赖 sentinel prompt。

### PDE：分数提高不等于 deliverable contract 生效

skills 为 +0.13，prep 为 +0.148。skills 与 base 的 error-tag 集合相同，`tags_score`
同为 0.818；提高来自 feedback 文本和 summary（0.367→0.683、0→0.333），不是 artifact
contract。prep 额外修正一个 tag，`tags_score=0.909`。因此 prep 可能提供了题目内容，
而 skills 的提高更像采样到更好的文字回答；不能把这题记作 deliverable skill 的机制证据。

### CT：真实 verifier 已存在，prep 仍没发现搜索分支

三臂本轮都为 0。prep 用 3,492 秒、107 steps、117 万 main input tokens，报告也做了大量
连续参数敏感性测试，但仍没有枚举 359.9xx 总角跨度附近的 LEAP 离散 weighting 分支。
公开 reference、MSE、SSIM 已能提供真实 feedback；verifier 能正确说“SSIM 未过”，却
不能自动提供“下一步试 359.999”的新知识。这里缺的是搜索/先验发现，不是再加 checker。

### SSE、Audience、SAP、Moodle：方向翻转显示策略噪声

- SSE：base/prep=0.667，skills=0.333；方法文本没有新增外部事实。
- Audience：base=0.867，skills=0.725，prep=0.904；正负方向同时出现。
- SAP：base/prep=0.25，skills=0.35；旧 prep 0.35 没复现。
- Moodle：base/prep=0.95，skills=0.885。

这些单题差异可以解释具体输出，却不能归因成通用方法效应；它们共同说明一次 rollout 的
策略选择方差足以淹没约 0.02 的目标提升。

## 当前决策

1. `deliverable-contract` 不应作为默认 verifier，也不应对几乎所有产出题加载。若保留，
   下一版 description 只匹配“存在非平凡公开 validator/oracle 或机器可读 contract”的题；
   普通文件/列要求、无 outcome 的预测和泛化质量全部排除。当前证据支持默认关闭。
2. `evidence-audit` 可保留为窄门控的 writer 方法候选，因为 Agora 有可解释正向信号；
   但必须在 Legal/Agora 类任务上至少重复三次后再默认启用。
3. 真正的 skill 应提供可复用的新能力：稳定的领域 API/格式知识、解析器、可执行工具、
   workflow 模板或跨多题复用的操作 playbook。它不应只是“仔细检查”或“写 verifier”。
4. verifier 独立成实验轴：builder 在 solve 前只看公开材料并生成带 source anchor 的 spec；
   spec 先机械 lint；runner 使用 fresh context 和只读 hash snapshot；确定性检查优先，语义
   LLM 必须返回页码/行号/record id；只把最小失败集合反馈 writer，最多 2–3 轮。
5. 信号分为 `deterministic`、`public_evidence`、`proxy`、`unverifiable`。后两者不能冒充
   outcome pass；verifier error 也不能变成对 writer 的负反馈。
6. 新 verifier 作为 `base / skills / verifier / skills+verifier` 独立消融，prep 另作正交轴；
   每格 `k>=3`，报告 false positive、repair 次数、unverifiable 比例、token 和时长。

当前 combined 和剩余单元继续运行。终版会补齐 104 个单元、PE Boyue resume、combined
cache 26/26 一致性、最终均分和完整配对统计。
