# Argus × gpt-5.6-sol — ALE-CLI 105 题最终结果

Argus 四角色 harness(Manager / Planner / Engineer / Reviewer,全部 `gpt-5.6-sol`)
跑完 ALE-CLI 全 105 题,每题在评测 VM 内产出交付物,对隐藏答案打分。

## 最终得分
- 105 题全部评分,平均 **0.546**,中位数 0.670;74/105 题得分 > 0。
- 分布:29 满分 · 22 高(0.7–0.99)· 16 中 · 7 低 · 31 零。
- 领域均分:物理 0.741 · 交通 0.822 · 商金 0.623 · 教育 0.597 · 计算 0.584 ·
  医疗 0.520 · 生命 0.475 · 工程 0.243 · 心理神经 0.186。
- 成本:全程输入约 5.5 亿 / 输出约 850 万 token,人均约 550 万 / 8.4 万。

## 本目录文件
| 文件 | 内容 |
|---|---|
| `argus_report.html` | 可视化最终报告:统计 + 逐题结果 + 系统架构与执行流程图(浏览器直接打开) |
| `argus_final_scores.csv` | 105 行清单:`task, domain, score, run_status, in_tok, out_tok, dur_s, trajectory` |
| `config/` | 定义实验的配置(agent / exp / model_catalog / task_variants) |
| `bin/` | 生成得分表的脚本 |
| `_intermediate/` | 中间重跑与调试记录(已移出主视图,非最终结果) |

## 原始轨迹在 pgl 上
不下载轨迹到本地。`argus_final_scores.csv` 的 `trajectory` 列是每题最终运行轨迹的
**pgl 绝对路径**。同事登 pgl(`ssh ubuntu@pgl.zgcagi.ac.cn -p 11015`)即可查看,那里有一份
自包含的最终文件夹:

```
~/argus/FINAL/
  README.md                同款说明(含配置/超参/架构)
  argus_final_scores.csv   同款清单
  trajectories/            105 个软链,每题一个:<domain>__<task>.json -> 该题最终轨迹
  config/                  实验配置
```

每条 `trajectory.json` 所在目录同级还有 `run.json`(分数/token/耗时)、`eval_result.json`、
`events.jsonl`,以及 `origin_log/argus/.../events.jsonl`(角色逐轮事件)和 `agent_io.jsonl`
(原始 codex 调用帧)——可查到 Manager/Planner/Engineer/Reviewer 每一步的细节。

## 实验配置与超参
- 模型 `gpt-5.6-sol`(Boyue 网关),harness=argus(四角色),executor=sandbox(in-VM)
- reasoning effort:Manager/Planner/Engineer xhigh,Engineer 首轮 high,Reviewer high
- context window 128000,auto-compact 100000;max_missions 1,max_rounds 500,iterate false
- manager_division false(vertical 钉死 `ale_last_exam`),cost_control false
- 每个运行进程 concurrency 3,单题 wall_time 28800s

## 系统架构(执行流程)
Argus 不持有模型,每个角色是一次 `codex exec`,整套 harness 装进评测 VM:
`ale_run run` 解析 harness `"argus"` → `ArgusDeployer`(sandbox)→ 在 VM 里装 codex + argus
wheel → `_launcher` 驱动 `Manager → Planner → Engineer → Reviewer` 循环 → 产物落精确路径 →
`evaluate()` 读 output + 隐藏 reference 打分。相对单角色 agent,多出的是 Engineer 写完后
Reviewer 的独立复核。隐藏答案在 agent 运行期间不可见,评分时才装入,与作答隔离。
详见 `argus_report.html`。
