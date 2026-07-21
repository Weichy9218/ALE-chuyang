# Prep v11 六题首轮结果

本轮是可编辑 working-prior 设计的首个 6 题 `base/prep` 对照。12/12 unit completed。

| Task | Base | Prep v11 | Delta |
|---|---:|---:|---:|
| BPMN supply disruption | 0.86050 | 0.82520 | -0.03530 |
| Digital marketing segmentation | 0.90420 | 0.90420 | 0 |
| SSE northbound reporting | 0.66667 | 0 | -0.66667 |
| PDE homework grading | 0.59315 | 0.66564 | +0.07248 |
| CRF SDTM mapping 4 | 0.61720 | 0.62680 | +0.00960 |
| FluSight offline forecast | 0.73940 | 0.65480 | -0.08460 |

Base 均分 `0.73019`，Prep `0.61277`，配对差 `-0.11741`，`t=-1.05`。6 份报告全部非空，共 17 条 entry，初始均长 5487 字符；只有 BPMN 使用 web，且没有 `web_fetch`。Writer 读取全部报告，回查 17/29 个 source，修改 5 份。

SSE 的 Prep 报告把“只明确允许英文”放大为 `Unknown`，Prep arm 从 base 的 `0.6667` 降为 0。该反例和低 web adoption 触发了 v12 的 search+fetch gate、skip 和更短报告预算。v12 最终结果见 [prep_v12_six](../prep_v12_six/)。

机器表见 [scores.csv](scores.csv)、[behavior.csv](behavior.csv)、[prep_findings.csv](prep_findings.csv)、[prep_writer.csv](prep_writer.csv) 和 [summary.json](summary.json)；报告位于 [reports](reports/)。
