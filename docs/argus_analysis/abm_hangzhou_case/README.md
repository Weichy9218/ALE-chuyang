# abm_hangzhou_metro 轨迹分析

杭州地铁客流 Agent-Based 仿真。Argus 四角色（`gpt-5.6-sol`）得 1.0。这道题不在 ale_claw 跑的 26 题内，没有同模型单体对照，单体基线取 ALE 的 Qwen3.5-397B 参考运行（模型和 Argus 不同）。Argus 轨迹从 pgl 爬取。

## 文件
```
argus/
  validation_report.txt   最终指标 R2=0.785409, RMSE=7.12min
  run.json / eval_result.json / events.jsonl
  role_events.jsonl       角色逐轮事件
  argus_summary.json      两轮任务摘要与 Reviewer 认证原文
  trajectory.json         完整轨迹
task_card.json            题面
```

## 题目
给杭州地铁 AFC 刷卡数据 1,264,325 条、线路 GeoJSON、站点序列、运营参数。搭 Agent-Based 模型仿真客流，输出逐乘客的 `passenger_records.csv`（9 列）和 `validation_report.txt`。评分比对仿真时长与真实 AFC 的偏差。

## 两边
| | Qwen3.5-397B 单体基线 | Argus 四角色 |
|---|---|---|
| 得分 | 0.0 | 1.0 |
| 步数 / 输入 token / 时长 | 18 步 / 38 万 / 超时（7248 秒） | 229 步 / 276 万 / 27 分钟 |
| 结果 | timeout，未产出合格交付 | R²=0.785，成本 $10.12 |

## Argus 过程
- Planner 把任务拆成环境准备、仿真执行、结果验证三步，每步带验收。
- Mission 1 Reviewer 判 done：两个文件都在指定路径、可解析；逐行校验九列 schema、整数字段、1,264,325/1,264,325 AFC 全覆盖、时长算术、站点有效、报告指标内部一致；独立复算 R² 0.781964；查源码确认仿真值来自网络路由和列车事件模拟，不是抄 AFC 标签；新鲜复跑零未服务行程、两个交付逐字节复现。
- Goal Gate 开 mission 2 再认证，独立复算 R² 0.785409。

## base 为什么失败
ABM 仿真要先配站点拓扑、发车间隔、路由逻辑，再模拟 126 万条记录。单体 18 步就在环境配置上耗尽时间超时。Argus 靠 Planner 的预先拆解，Engineer 有明确验收标准逐步推进，27 分钟完成。

## 注意
n=1。单体基线是 Qwen 不是 gpt-5.6-sol，模型不同，这题是定性例子，不是同模型对照。Reviewer 复算的 R² 与最终 `validation_report.txt` 里的 0.785409 一致。
