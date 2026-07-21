# Verifier v13 六题实验

> **结论已撤回（2026-07-21）。** 本实验判定「六题门未通过、Verifier 无效」是错误的。v13 的
> 反馈通道只把硬阻断失败送进 Writer，其余可复现测量全部丢弃，实验结构上无法暴露 Verifier
> 的价值，因此六题门未通过是通道 bug 的产物，不是 Verifier 无效的证据。SSE 那次被标为 false
> blocking 的 repair 实际有效，问题只在把语义先验当成硬门。修正见
> [VERIFIER.md](../../VERIFIER.md)（`public-verifier-v14`）。下方原始数据保留作实验依据。

本实验沿用六个预注册任务，比较 `max_repairs=1` 和 `max_repairs=3`。每个 repair
设置单独运行同期四臂：Base、Prep、Verifier、Prep + Verifier。所有 arm 使用同一模型、同一
endpoint 配置和同一任务清单。

## 启动 26 题的门槛

至少一个 repair 设置必须同时满足：

1. 12 个 verifier-enabled unit 中至少 10 个成功冻结测试包；所有正式执行使用冻结 suite。
2. 人工复核全部 blocking failure，确认 false blocking 为 0。
3. 所有 repair transition 重跑完整 suite，suite hash 不变；环境错误不算作 output failure。
4. 六题 factorial verifier main effect 大于 0。
5. 不存在由无依据或错误测试驱动、相对对应 control 降低 0.2 以上的任务。
6. 至少一个真实 failure 在 Writer 复核后消失，且没有新增 blocking failure。

若两个设置都满足，选择 verifier main effect 更高、回归更少、平均 repair 轮次更低的设置运行
26 题。六题每格只有一次 rollout，只作为扩展实验的机制门，不作为稳定收益结论。

## 配置

- `harness/run/settings_verifier_v13_six_r1.yaml`
- `harness/run/settings_verifier_v13_six_r3.yaml`
- `docs/harness/results/prep_v11_six/tasks.txt`

结果完成后在本目录保存分数、Verifier check、repair transition、人工 source audit 和结论。

## Pilot 记录

repair=1 的协议 pilot 发现三类问题。这些运行只用于修正机制，不进入效果比较：

1. Builder 将 fixture map 解释为 `{path, content_base64}`，导致 lint 拒绝整包。最终 fixture
   改为非空文件数组。
2. Auditor 调用重复嵌入全部 script 和 fixture，单个 BPMN unit 累计 426837 input tokens。
   最终只传紧凑 manifest，Auditor 按需读取 staged 文件；候选包在 Writer 前删除。
3. 单一 source 不能证明公开重算的完整 expected。Digital 的筛选规则、governance 和 Parquet
   共同决定精确计数，只引用 brief 不足以获得 blocking 权限。最终每个 check 使用完整
   `sources` 数组；二进制数据用 whole-file hash。

最终协议使用非空文件数组：

```json
[
  {"path": "result.csv", "encoding": "utf8", "content": "id\n1\n"}
]
```

Executor 同时保留结构化 `observed` 和 `evidence`。Analyzer 按时间选择每个
`(arm, task)` 最新结果，不读取 pilot 的无效 unit。最终代码在 pgl 通过
`70 passed, 1 skipped`，Ruff 全部通过。

## 六题结果

| 设置 | Base | Prep | Verifier | Prep + Verifier | Verifier 主效应 | 冻结成功 | Repair |
|---|---:|---:|---:|---:|---:|---:|---:|
| `max_repairs=1` | 0.70500 | 0.71999 | 0.71209 | 0.72596 | +0.00653 | 10/12 | 0 |
| `max_repairs=3` | 0.69465 | 0.75007 | 0.70597 | 0.74324 | +0.00225 | 11/12 | 1 |

`max_repairs=1` 的 16 条 blocking check 全部 pass，没有真实 failure 可供 Writer 复核和修复，
因此不满足门槛 6。

`max_repairs=3` 首轮共有 27 条 blocking check：26 pass、1 fail。唯一 failure 是 SSE
`q2_hft_fee_amounts`。公开规则只说明具体收费标准另行规定，没有定义该问法应映射为 `No` 还是
`Unknown`。Checker 却强制 `Unknown`，Writer 因此把原有 `No` 改成 `Unknown`。这是 false
blocking，不是真实修复。虽然该修改碰巧把任务原 evaluator 分数从 `0.6667` 提高到 `1.0`，
Verifier 不能读取或用隐藏评分反向证明公开判准。去掉 SSE 后，r3 的 Verifier 主效应为
`-0.03064`。

Repair 确实重跑了完整冻结包：前后 suite hash 都是
`42aa1af775a14cb5b1a0c8625531de1f09456d29a344973473489e522f56bef7`；snapshot hash 从
`f0072d...` 变为 `b5a906...`。完整值见 [r3/verifier_repairs.csv](r3/verifier_repairs.csv)。

## 扩展门结论

| 门槛 | repair=1 | repair=3 |
|---|---|---|
| 至少 10/12 个冻结包 | 通过，10/12 | 通过，11/12 |
| false blocking 为 0 | 通过，无 blocking failure | **失败，1 条** |
| repair 重跑同一 suite | 无 transition | 通过，hash 相同 |
| Verifier 主效应大于 0 | 通过，+0.00653 | 表面通过，+0.00225；由错误 SSE repair 支撑 |
| 无错误测试导致超过 0.2 的回归 | 通过 | 通过 |
| 至少一个真实 failure 被修复 | **失败，0 个 repair** | **失败，唯一 repair 不成立** |

两个设置都没有同时通过六项门槛，因此没有启动 26 题。

## SSE 修正 canary

Builder 和 Auditor 现同时要求公开来源直接定义命题到枚举标签的映射。修正后重新运行 SSE 的
Verifier、Prep + Verifier 两臂：两者均为 1 轮、0 repair、得分 `0.6667`。两套测试都把三问的
语义标签判准列为 `unverifiable`；Prep + Verifier 只保留公开 schema contract 为 blocking。
Verifier-only 的结构脚本因输出 `passed/failed` 而被 fixture preflight 降权，随后 Builder
协议进一步明确脚本状态只能是 `pass / fail / unverifiable`。机器结果见
[sse_label_canary/](sse_label_canary/)。
