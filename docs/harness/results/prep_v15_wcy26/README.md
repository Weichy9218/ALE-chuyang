# Prep 26 题机制 canary

本目录整理 2026-07-20 的 26 题 Prep 泛化 canary。主 run 使用 v15 path-based handoff；
Legal MA 因原容器 VM bridge 失效，在其余 25 题终态后用 v16 新容器恢复，得分为 0。该 retry
只补任务终态，不与 v15 研究成本混写。

这不是同轮 Base/Prep 配对实验。`historical_comparison.csv` 使用同一任务的历史 Base，只能
观察机制和异常分布，不能给出严格因果估计。

## 结果

- 26 个任务均有终态：25 个有分数，PE Screening 的 evaluator 调用缺失模型 endpoint，记
  `failed`，不是 writer artifact 失败。
- 25 个分数均值为 0.6158。
- 相对历史 Base：平均差 +0.0103，标准差 0.0532，标准误 0.0106，`t=0.97`。
- 4 个正差、4 个负差、17 个持平，historical harm rate 为 4/25。
- 最大正差：Variant +0.2060、Agora +0.1459。
- 最大负差：BPMN Supply -0.0667、Digital Audience -0.0333。

这些差值包含 endpoint 时间、writer rollout 和配置代际差异。它们用于定位采用链，不用于
声称 +0.0103 uplift。

## Prep 成本

26 份 `task_prep_meta.json` 汇总：

| 指标 | 数值 |
|---|---:|
| completed / empty / failed | 19 / 6 / 1 |
| cache hits | 4 |
| input tokens | 2,253,510 |
| output tokens | 80,595 |
| duration | 11,819.5 s |
| tool calls | 194 |
| reports | 19 |
| accepted artifacts | 8 |
| report chars | 54,136 |

cache hit 的当前 meta 不重复记录原始研究成本，所以 2.25M tokens 和 11,819.5 秒仍是下界。
与“1.5M tokens 但总体变化无法区分噪声”的历史观察相比，扩大通用研究没有改善成本收益比。

## 正向机制

### Variant annotation

Prep 从官方 Ensembl release/113 获取题内缺失的 consequence severity rank，限制到 frozen
snapshot 实际出现的 11 个术语。writer 首轮读取报告和 rank receipt，复核 hash，并把 rank
表写入 pipeline；这直接改变 protein-coding transcript 的离散选择方法。最终得分 0.999，
历史 Base 为 0.793。

writer 后续还独立修正了 indel submitted-allele lookup。因此 0.206 全量不能只归因于 rank
receipt，但“报告 -> artifact -> rank table -> selection code”的采用链完整。这是高价值 Prep
的典型：任务缺失的外部精确语义、适用范围有限、可以机械复查、改变离散分支。

### Agora governance

Prep 把 AGORA 1293 的 `Engrossed in Senate`/`Passed the Senate` provenance 与拟议刑罚、FTC
enforcement 并列，提醒 writer 不要把 `Be it enacted` 当成法律已经生效。writer 第一调用读取
报告，回查原文，并将 1293 标为 `Other`。最终 0.6467，历史 Base 0.5007。

该报告只覆盖一个文档；总分还受另外两份文档的大量字段影响。因此这是可信的局部采用链，
不是可归因的整体 +0.1459。

### SEC runtime

Prep 确认 ambient Python 3.14 不满足项目的 `>=3.10,<3.11`，而 `/usr/bin/python3.10` 可运行
固定依赖。writer 没有执行附带 probe，但采用了 3.10 runtime 路径。得分 0.7058，历史 Base
0.6817。方法采用清楚，分差仍可能是 rollout 噪声；一次性版本事实更适合短 observation，
不需要脚本附件。

## 负向和无效机制

### Digital Audience

v15 再次报告只影响 1/6 overlap 行的 AUD-005 缺字段。writer 第 2 个工具调用读报告，第 8
个调用复查该行，最终把三个值留空，得 0.6912。相同 endpoint 的六题 Base 是 0.8667。
`do_not_infer` 没有抵消开题锚定；v16 的 affected/total coverage gate 专门拒绝这种低影响
finding。

### Artifact adoption 不等于收益

8 个附件中，writer 实际调用或读取 5 个：Bias runtime probe、CRF1 page crosswalk、CRF4
source locator、Variant rank receipt、Legal fees scope receipt。只有 Variant 有清楚的正向方法
链。Bias 和 CRF1 即使执行附件仍为 0；Legal fees 本身已是满分题。SEC、SSE 和 CT 附件未被
调用。

旧 artifact 还包括 Markdown receipt、一次性 runtime script 和 negative absence search。
v16 已删除 prose attachment，只允许 pull-based resolver、exact metric、参数化 runtime probe
或至少四个 locator 的静态 index。

### 其他失败模式

- BPMN candidate/contract 研究没有提供可执行 runtime 能力，分差为负。
- CT 只证明 float SSIM 必须显式给 `data_range`，但 identical-image control 无法比较候选范围，
  得分仍为 0。
- MARC 将“未定义完整”当 conflict，重复 negative gap，得分与历史相同；v16 要求两个正向
  task-local claim。
- Legal fees 用全 PDF 无命中证明 scope bridge 缺失，属于 absence receipt；writer 本来即可
  得满分，边际价值为零。

## 决策

不运行 105 题。理由不是均值为负，而是证据还没有满足扩展条件：

- 历史对照平均差只有 +0.0103，`t=0.97`。
- 成本下界已达 2.25M input tokens 和 3.28 小时 Prep wall time。
- 19 份报告中，强正向链集中在 Variant，Agora 为局部候选。
- Digital 的可复现锚定伤害仍存在于 v15。
- artifact execution 只有 1/5 显示清楚的结果价值。

这支持保留窄机制路由：外部精确语义、任务本地 authority/provenance 冲突、精确 metric、
阻断执行的 runtime 事实和真正的跨文件 resolver。它不支持 broad research 默认开启。

## 文件

- `historical_comparison.csv`：25 个可评分任务的历史 Base 对照。
- `analysis/`：行为、Prep finding、writer adoption 和 run 汇总。
- `raw/main/`：25 个主 run 终态和全部 26 份 Prep 原件。
- `raw/legal_retry/`：Legal MA 新容器恢复 run。
- `tasks.txt`：26 题清单。

对应的题目解释可在
`docs/archive/harness-general-prep-2026-07/case_by_case/` 和
`docs/archive/harness-general-prep-2026-07/pi-cases/` 继续下钻。
