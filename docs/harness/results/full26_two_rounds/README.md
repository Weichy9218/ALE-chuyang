# 26 题两轮实验（2026-07-21 夜）

两组实验在 pgl 上串行运行，都是 26 题、只跑 prep 和 verifier 两个 treatment 臂，
base 用 `docs/task_analysis` 里各题的历史多次运行均分（硬编码在 `compare_vs_base.py`）。
两轮的 base 值完全相同，所以两轮之间的差异只来自 treatment 臂的运行和协议改动。

逐题原始输出在 [compare_vs_base.txt](compare_vs_base.txt)。

| | 实验1 | 实验2 |
|---|---|---|
| 协议 | `task-prep-v21` / `public-verifier-v18` | `task-prep-v22` / `public-verifier-v19` |
| 结果目录（pgl） | `.logs/ale/prep_v21_verifier_v18_full26` | `.logs/ale/prep_v22_verifier_v19_full26` |
| 模型 | `openai/gpt-5.6-sol` | 同 |
| 并发 | 每臂 6 | 同 |

## 配对结果

| 臂 | 实验1 配对均差 | 实验2 配对均差 |
|---|---|---|
| prep | `-0.0070`（sd 0.0444，t `-0.77`，n 24，+5 / =13 / -6） | `+0.0163`（sd 0.0618，t `+1.26`，n 23，+6 / =13 / -4） |
| verifier | `+0.0209`（sd 0.0416，t `+2.57`，n 26，+10 / =15 / -1） | `+0.0005`（sd 0.0499，t `+0.05`，n 25，+5 / =14 / -6） |

n 小于 26 是因为个别 unit 未产出分数：实验1 的 american_option 和 epidemiology（prep 臂），
实验2 的 bpmn_category、marc、agora（prep 臂）和 bpmn_category（verifier 臂）。

## 实验2 没有复现实验1 的 verifier 效应

实验1 的 `+0.0209`、t `+2.57` 是目前为止 verifier 最好的一次读数。实验2 用几乎相同的
协议（v18 到 v19 只加了信封字段缺失的兜底和构建失败时的响应记录，都是 fail-open 方向）
重跑，得到 `+0.0005`、t `+0.05`。

两轮之间没有能解释这个差距的协议改动，所以 `+0.0209` 更可能是运行方差，不是可重复的效应。
两轮平均是 `+0.011`，这是目前对 verifier 收益的最好估计，且没有通过任何显著性门槛。

单题层面的翻转直接支持这个判断。同一道题、同一个臂、协议只差一点，两轮的 delta 可以
反向：

| 题目 | 臂 | 实验1 | 实验2 | 跨轮差 |
|---|---|---|---|---|
| digital_marketing_audience_segmentation_1 | verifier | `+0.0925` | `-0.1247` | 0.2172 |
| healthcare_variant_annotation_pipeline | prep | `-0.1374` | `+0.0686` | 0.2060 |
| sec_10k_financial_parsing | prep | `+0.0244` | `+0.2638` | 0.2394 |
| pe_screening_memo_1 | verifier | `+0.0413` | `-0.0524` | 0.0937 |

单题的运行方差达到 ±0.1 量级，而两个臂的配对均差都在 ±0.02 以内。用 26 题测这个量级的
效应，功效不足。

## 一半的题对任何臂都没有反应

两轮都算分的题里，delta 在两轮都恰好为 0 的：verifier 14/25，prep 11/21。这些题包括
两轮都是满分的（american_option、financial_stmt、internal_employee、epidemiology、
legal_dr_fees）和两轮都是零分的（bpmn_category、legal_ma、crf_sdtm_mapping_1、
ct_geometry、bias_audit）。满分题没有改进空间，零分题的失败原因在 prep 和 verifier
的作用范围之外。

有效样本因此只有名义样本的一半，这是标准误约 0.01 却要测 ±0.02 效应的直接原因。
下一轮应当预先剔除多轮 delta 恒为 0 的题，用同样的机器时间把有效 n 翻倍。剔除清单要在
看本轮结果之前定好。

## 稳定的单题效应

跨两轮方向一致且幅度接近的只有一例：agora_governance_classify 在 verifier 臂
实验1 `+0.1597`、实验2 `+0.1550`。variant_annotation 在实验1 verifier `+0.0686`、
实验2 verifier `+0.0686`、实验2 prep `+0.0686`，三次都是 0.9304 到 0.9990 的同一个跳变，
说明它是一个可复现的修复而不是随机波动。

## 机制读数

verifier 冻结成功率：实验1 是 26/26 `build=ready`，实验2 是 25/26（tcga_luad 一题
`build=error`）。对照 v16 六题的 0/6，v17 的 lint 逐条隔离和 v19 的信封兜底解决了整包
失败问题。

`verify` 工具调用率：两轮所有 `build=ready` 的题都调用了，没有出现冻结成功但工具零调用
的情况。

prep 的 self_check 交付率在实验2 明显高于实验1，因为 v22 把 findings 放进了 digest，
报告文件不再是唯一载体。交付率本身不是目标，交付之后是否转化为分数才是，而这一点两轮
都没有给出正面证据。
