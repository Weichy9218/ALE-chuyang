# Verifier — 分析与修复效果

> 设计见 [`../../harness/VERIFIER.md`](../../harness/VERIFIER.md)。一句话:对 writer 的产出,用从
> **公开材料**冻结的机械检查测一次,结果分 pass / fail / **unverifiable**(无公开 oracle 可测),
> 交给 writer 自行决定改不改——verifier 不替 writer 判分,也不写 output。

## 发现的问题:unverifiable 被读成"存疑",逼 writer 把对的改错

消费轮里 **sse_northbound verifier 臂 0.333,而 prep/base 都是 0.667**。追轨迹:

- writer 先写 q3(法国公司自研软件只有外文名能否照填)结论 = **No**(正确;规则只允许英文,不等于允许任意外文)。
- verifier 机械层正确地把 q2、q3 的结论标签判成 **`unverifiable`**(推理→label 的映射不在公开材料里,不能冻结)。
- **但旧渲染把 unverifiable 和真失败混在同一段**,还带上 builder 替 agent 论证的文字;WRITER INSTRUCTION
  又说"对任何你存疑的结果,重开源、复算、再改"。
- 下一步 writer 执行了 `d['q3_software_naming']['conclusion']='Unknown'`,**把正确的 No 改成 Unknown** → q3 判 0 → 总分 0.333。

即:verifier 没断言任何错的东西,它只是把 q3 标成"没法测";writer 把"没法测"当成"可疑",过度对冲丢了分。
这与 FABLE"测量通道的中性信号被当成负面证据"同型。

## 修复(`ale_run/agents/ale_claw/verifier.py`)

1. **拆通道**:`unverifiable` 单列进 **`NOT TESTABLE FROM PUBLIC MATERIALS`** 段,`neutral=True` 渲染——
   只留 requirement + "why untested",**删掉 builder 那段替 agent 论证的 interpretation/evidence**。
2. **改指令**:两条 WRITER INSTRUCTION 都加 "an unverifiable requirement is **not a doubt signal and not
   counterevidence**: never change an answer because a requirement could not be tested"。
3. **堵源头**:builder 提示约束 unverifiable 的 `expected`/`reason` 只能陈述"为何测不了",不得对答案取值论证。

## 效果(fix-validation,n=1)

| 任务 | 旧 verif | 新 verif | 机制确认 |
|---|---|---|---|
| **sse_northbound** | 0.333 | **0.667** | 轨迹里出现新 `NOT TESTABLE` 段 + "not a doubt signal";**无 q3 改写命令**,q3 保持 No |
| **audience_seg** | 0.725 | **0.904** | 回到 base 上界 |
| crf_4 / pe / bpmn_supply | 0.586 / 0.938 / 0.864 | 0.584 / 0.969 / 0.826 | 带内小幅波动 |

**真实轨迹对照(sse q3):**

```
# 修复前(verifier 臂,消费轮) —— writer 被 unverifiable 逼着翻案:
step 13  exec: d['q3_software_naming']['conclusion']='Unknown'          # 正确的 No 被改成 Unknown → q3=0

# 修复后(verifier 臂,fixval13) —— 反馈里出现:
NOT TESTABLE FROM PUBLIC MATERIALS
  No frozen test could measure these requirements ... neither a pass nor a doubt.
WRITER INSTRUCTION ... an unverifiable requirement is not a doubt signal and not counterevidence ...
# 结果:轨迹中无任何 q3 结论改写命令,q3 保持 No → q3=1.0 → 总分 0.667
```

深入:`~/ale/agents-last-exam/.logs/ale/fixval13/fixval13_verifier/…/sse_northbound_…/{trajectory.json,output/}`

## 边界与残余(必读)

- verifier 只能测**公开材料**能冻结的东西。sse 的 q2(金标准 Unknown、模型恒答 No)、q3 结论标签,本就属于
  "公开材料测不了"的类别——verifier 正确地不去碰它们。所以**修复消除的是倒扣,不是给 verifier 加了判分权**。
- 证据逐字性:verifier 有 `staged_source_consistency` 检查能验证 snippet 是否为源文档逐字摘录,但评分器额外要求
  命中**隐藏 anchor 短语**,verifier 看不到。把"非逐字"做成显眼失败能提命中率,不能保证得分(见 `../README.md` §3b)。
- **净效应 ≈ base**:去掉 sse 这个被单题标签陷阱主导的极值,verifier 在会动的题上小幅偏正,但 n=1 且部分是抽样偏好,
  不足以宣称"verifier 高于 base"。
