# 2026-07-21 夜间两轮 26 题实验 — 早晨查看指南

两组 26 题实验在 pgl 上串行运行，都只跑 prep 和 verifier 两个 treatment 臂，
不重跑 base；对照用 `docs/task_analysis` 里各题的历史 base 多次运行均分。

| | 实验1 | 实验2 |
|---|---|---|
| 协议 | `task-prep-v21` / `public-verifier-v18` | `task-prep-v22` / `public-verifier-v19` |
| 启动 | 2026-07-21 15:00 前后，手动 | 实验1 结束后由 watcher 自动 |
| 结果目录 | `.logs/ale/prep_v21_verifier_v18_full26` | `.logs/ale/prep_v22_verifier_v19_full26` |
| 运行日志 | `prep_v21_verifier_v18_full26_{prep,verifier}.log` | `prep_v22_verifier_v19_full26_{prep,verifier}.log` |

两臂各 concurrency 6（合计 12，boyue 网关上限 20），模型 `openai/gpt-5.6-sol`。

## 一条命令看结果

在 pgl 的 `~/ale/agents-last-exam`：

```bash
python3 compare_vs_base.py \
  .logs/ale/prep_v21_verifier_v18_full26 \
  .logs/ale/prep_v22_verifier_v19_full26
```

每臂输出逐题的 base / 本轮 / 差值，末尾给配对均差、sd、t、正负计数；
notes 列带机制读数（verifier：build 状态、`verify` 调用次数、lint 丢弃条数；
prep：self_check 是否交付、清单与 findings 条数）。26 题的历史 base 均分硬编码在
脚本里（提取自 `docs/task_analysis/*.html`）。

## 调度与安全边界

`run_exp2_after_exp1.sh`（nohup 常驻）等实验1 的两个进程退出，确认没有其他
`ale_run run exp_` 在跑，才把 `~/ale/staging-v22-v19/` 的 v22/v19 代码覆盖进主仓库，
校验协议号确实是 v22/v19，跑一遍三个测试套件，全过才启动实验2。任何一步不满足
就写日志并退出，不会启动。调度日志：`exp2_scheduler.log`。

代码切换必须串行的原因：两组实验共用同一个 checkout，且 `verifier_runtime` 是
函数内 lazy import，运行中换文件可能被半路读到。

## v22/v19 改了什么（都来自 v21/v18 六题 smoke 的实测）

- **prep v22：findings 进 digest。** smoke 显示 writer 从不打开
  `PREP_REPORT.md`（运行时命令和 self_check 命令都在 digest 里，够用了），
  于是只存在于报告里的 findings 零到达——Variant 的 Ensembl severity 排序被交付、
  staged、然后没人看见。findings 是三类产出中唯一没有程序化载体的，现在标题加
  observation 进 digest（每条 600 字符上限），来源与 caveat 仍留在报告文件。
- **prep v22：`covers` 上限 300→900。** SEC 的自检覆盖声明被截在句子中间，
  而这个字段的作用恰恰是声明"它不检查什么"。
- **verifier v19：顶层字段缺失兜底。** smoke 里 SEC 整包构建失败，原因是 builder
  响应顶层缺 `reason`/`tests`/`unverifiable`，被 `_check_keys` 整包拒绝——v17 声称的
  "逐条隔离"只落到了条目层，信封层还是硬拒。现在缺字段填默认值并记入 `dropped`，
  只有"没有任何可用测试或要求"才失败。
- **verifier v19：构建失败时记录 builder 响应前 400 字符。** smoke 事后无法判断
  SEC 是 builder 真的产出坏 JSON，还是提取器选错了对象。

## 早晨要看的读数（除分数外）

1. **verifier 冻结成功率**：v18 六题是 5/6，v16 是 0/6。26 题看 `build=ready` 比例，
   以及 v19 的兜底是否把 v18 里因信封问题失败的题救回来。
2. **`verify` 调用率与转化**：六题里 bpmn/variant 出现过"看到 review item → 改 →
   复查减少"的完整链。26 题看 `verify_used` 分布，以及 `verifier_round_0.json` 的
   review_items 是否比 writer_check 阶段更少。
3. **prep findings 到达**：v22 的 digest 带 findings 后，transcript 里 findings 关键词的
   出现率应当上升；对比 v21 那轮 Variant 的零到达。
4. **删减读数**：每个快照的 `snapshot_manifest` 做连续差，看 `output_shrank`。
   零权威理论上降低删减压力，但没测过。

## 已知的既有失败模式（不是本轮引入）

- `rpc_timeout` / VM 层超时：实验1 第一批就有一例（american_option）。历史常见。
- checker 依赖任务运行时而 verifier 单臂没有 prep 装环境 → `execution_errors`
  持续存在（六题里 bias、agora 各一条）。合并臂才可能解决，本轮不测。
- `no running event loop`：v21 smoke 出现过 3 例，是工具分派移出事件循环后
  delegate 子代理的回归，已在 smoke 后修复；实验1 日志中该错误为 0。
