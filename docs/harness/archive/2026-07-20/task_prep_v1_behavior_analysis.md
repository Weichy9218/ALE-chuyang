# Task Prep v1 行为审计与定向优化

本报告把“得分”与“行为”分开。数据来自 pgl 上
`.logs/ale/task_prep_v1` 的 78 个新臂 run，以及
`.logs/ale/harness_compare` 的历史四臂 run。逐题原始行为表在
[`task_prep_v1_behavior/per_task.csv`](task_prep_v1_behavior/per_task.csv)，来自 pgl
run artifacts 的一次性复算。便于筛选的 prep 与 skill 子表分别为
[`prep_reports.csv`](task_prep_v1_behavior/prep_reports.csv) 和
[`skill_triggers.csv`](task_prep_v1_behavior/skill_triggers.csv)。

历史 base 与新臂不在同一天，每格也只有一次。下面可以解释轨迹机制和资源开销，不能
把小幅均分变化解释成稳定因果效应。

## 1. 做题时长与交互轮数

这里的 `active` 是 `agent_run_started -> agent_finished`，不含排队；`solver` 对未命中
缓存的 run 减去 prep registry 的研究时长；`LLM turns` 是 trajectory 中真实 API
调用数。`run_steps` 同时计入模型响应和工具结果，因此约为 LLM turns 的两倍，不能
当成对话轮数。

| arm | active 秒 mean / median | solver 秒 mean / median | LLM turns mean / median | tools mean / median | main input tokens mean / median |
|---|---:|---:|---:|---:|---:|
| new_prep | 903.6 / 757.0 | 688.7 / 566.5 | 10.0 / 7.5 | 14.7 / 13.0 | 181,697 / 124,630 |
| new_skills | 1,082.7 / 860.5 | 1,082.7 / 860.5 | 13.9 / 11.0 | 20.3 / 16.0 | 302,424 / 210,918 |
| new_combined | 1,088.8 / 892.5 | 944.7 / 725.7 | 12.0 / 10.5 | 16.4 / 12.5 | 245,858 / 157,479 |

26 题累计 active 时间分别为 6.53、7.82、7.86 小时。相对历史 base：

- `new_prep` 平均少 2.19 个主模型回合，主 agent 少用约 48,945 input tokens；prep
  不是让 solver 冗长，而是提前承担了部分发现工作。加上 prep 后 active 时间平均只多
  16.6 秒，因为 solver 平均缩短约 198 秒。
- `new_skills` 平均多 1.77 个模型回合、71,782 main input tokens 和 196 秒。去掉 CT
  极端值后仍平均多 0.8 回合、42,408 tokens 和 94.6 秒。
- `new_combined` 主回合数与 base 接近，但 active 时间平均多 202 秒。去掉 CT 后多
  112 秒。
- `run.json.usage` 只计 main agent，不计 prep。观察到的 prep 输入加回后，26 个
  `new_prep` run 共使用 10.97M input tokens；其中 main 为 4.72M。不能用 main cost
  误称 prep 很便宜。

## 2. Prep 的实际质量与信息损失

52 个 prep-on 实例中，49 completed、3 failed、0 empty、10 cache hit。其余 42 次
真实研究会话共调用 629 次工具：`exec=527`、`read=18`、`web_search=35`、
`web_fetch=34`、`analyze_image=15`。单次研究的均值 / 中位数是：

| 指标 | mean | median | p75 |
|---|---:|---:|---:|
| prep 秒 | 222.3 | 207.4 | 266.5 |
| prep LLM turns | 7.9 | 8.0 | 9.0 |
| prep tools | 15.0 | 14.0 | 18.0 |
| prep input tokens | 232,473 | 180,922 | 317,258 |
| prep output tokens | 4,273 | 4,052 | 5,304 |
| 完整最终报告字符 | 3,452 | 3,518 | 4,113 |

现有所谓 `compact sourced findings` 不是另一次可靠压缩：prep-agent 生成最终报告后，
`sanitize_prep_output()` 直接取前 4,000 字符。52 个实例中 19 个出现截断，涉及 26 个
唯一 task fingerprint 中的 12 个；可恢复样本平均丢 320 字符，中位数 258。大多数尾部
是 `Confidence` 或 `Coverage gaps`，但并不总是无关：MARC 丢了约 1,233 字符的一整条
匹配统计，CRF1 丢了 Define-XML 来源选择的后半条事实。字符硬切还会切在单词或句子
中间。

不过截断不是 CT 失败原因。两个 CT prep 报告分别为 3,915 和 3,340 字符，都完整注入。
它们没有发现角跨度边界，所以即使把原报告全塞给主 agent，也不会提供缺失的关键事实。

质量方面还暴露出两种边界问题：

- 新 prep 的确发现了有价值的新信息，例如 CRF4 的真实 Define-XML、TCGA 的实际包/API、
  Flusight 的缺失结构和 LEAP 1.26 行为。这些是合理的 task-specific prior。
- SSE 报告直接给出三个待判命题的材料结论，Legal 报告直接枚举实质不一致。这已经很
  接近第二个 solver，而不是工具/版本研究。52 次没有一次输出 empty，也说明当前
  `NO_TASK_SPECIFIC_PREP` gate 太弱。SSE 的 0.333 -> 1.000 是真实收益，但不能据此
  声称 prep 角色设计已校准。

v1 的硬截断已从当前实现删除。prep 现在只生成一份完整报告：host 保存为
`task_prep.md`，任务 VM 保存为 `task_prep/PREP_REPORT.md`，主 prompt 只给路径。没有
compact/full 双份内容，也没有 `sanitize_prep_output()` 或字符上限。

## 3. Skills 到底有没有触发

有，而且不是偶尔触发：两个 skill-enabled 臂共 52 个任务全部执行了一次
`memory_get`，49 个在 solver 的第 0 回合加载。没有任何 `memory_search`。

| loaded skill | 次数 |
|---|---:|
| deliverable-contract | 48 |
| evidence-audit | 4 |

路由并不稳定。`new_skills` 在 Legal、PE、PDE 三题选择 evidence-audit；
`new_combined` 只有 Legal 选择它，同一个 PE/PDE prompt 又改选 deliverable-contract。
SSE 两臂都选择 deliverable-contract。由此不能把 skills 的弱效果归因于“主 agent 没看
skill”；更准确的问题是：几乎所有任务一开始就加载方法文本，但方法选择受同一次采样
影响，而且多出来的检查/回合没有稳定转化成更好的决策。

不增加新的 routing 层或强制 ledger。skills 保持给 main agent 使用，prep-agent 仍不
加载 skills；CT 的变量/边界研究属于 prep 职责，不写入通用 deliverable skill。

## 4. CT Geometry 为什么仍然是 0

阈值是 `SSIM >= 0.95 AND MSE <= 4e-6`，且 `input/reference_image.npy` 是题面公开
oracle。三个新臂都实际运行了 SSIM/MSE，不存在拿不到真实反馈的问题。

| arm | active 秒 | LLM turns | main tools | prep 秒 / turns / tools | angular span | MSE | SSIM | score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| historical base | 2,638 | 38 | 38 | - | 359.999 | 7.11e-8 | 0.99394 | 1 |
| new_prep | 2,525 | 29 | 30 | 202.5 / 8 / 19 | -360.0 | 1.06e-6 | 0.90242 | 0 |
| new_skills | 5,360 | 64 | 65 | - | -360.0 | 1.05e-6 | 0.90330 | 0 |
| new_combined | 5,091 | 53 | 55 | 168.5 / 6 / 11 | -360.0 | 1.83e-6 | 0.84864 | 0 |

三个新臂的 MSE 都过线，SSIM 都没过线，所以 evaluator 给 0 与公开完成度一致。问题
不在评分校准，而在搜索拓扑：它们不断优化 SAD、SDD、offset、tau、voxel/detector
pitch、post-processing 等连续变量，却没有把“总角跨度”当作会触发 LEAP 离散分支的
变量。历史 base 扫到 359.90、359.92、359.98、360.001 时，SSIM 分别约为 0.9436、
0.9615、0.9942、0.9033。360 度附近不是平滑目标面。

`new_skills` 用时和回合数接近 base 的两倍，证明失败不是“不够认真”。prep 还明确写了
角度是 `0,-1,...,-359` 且“不应 silently reverse”，这条正确但不完整的结论形成了
锚定。combined 还在运行中出现过优于最终 0.8486 的候选，却没有在继续试验后恢复
best candidate。

因此 CT 对系统的教训不是再加一个 checker。checker 已经能正确说“SSIM 未完成”；
缺的是 prep 对目标计算链、变量敏感性和 boundary-triggered branch 的研究。这个职责
现在只放在 prep protocol，不修改通用 deliverable skill。

## 5. 分数应该怎样读

相对历史 base，`new_prep/new_skills/new_combined` 的均分差是
`+0.0023/-0.0300/-0.0262`；去掉 CT 后是 `+0.0424/+0.0088/+0.0127`。相对旧版同名
臂，新版差为 `+0.0345/-0.0099/+0.0050`。这支持“新 task-specific prep 比旧 general
prep 更有机制价值”，不支持“new_* 已稳定提分”。

正向机制集中在信息瓶颈：SSE、CRF4、Flusight、TCGA。负向机制集中在三类：

1. 搜索空间遗漏离散边界，如 CT。
2. 上游规范覆盖 task-local 明示规则，如 Variant；prep v1 后已经明确 task-local 优先。
3. prep 与 skills 组合后的采样/策略干扰，如 TCGA、SAP；更多上下文和方法不是单调增益。

BPMN 和 Legal 继续为 0 也不是“差一点再提醒一下”就能解决。BPMN 的公开 artifacts
本身存在 a23/a24 与 a50、delist terminal 与普通场景的冲突，harness 不能修改任务。
Legal prep 找到了多个实质冲突，但 evaluator 需要的 lexical anomaly 仍漏掉；把 typo
scan 强制推广到所有任务的成本和误导大于收益，仍不进入通用 skill。

## 6. 当前决策

CT v2 prep-only 仍为 0，且完整 8,043 字符报告已被 main agent 读取，所以不再把截断视为
CT 的主要机制。当前停止真题实验，删除 CT 专用 canary 配置；下一步只收敛 prep 的
信息增量标准和单一完整报告交付，不增加新的 routing、checker 或实验流程。
