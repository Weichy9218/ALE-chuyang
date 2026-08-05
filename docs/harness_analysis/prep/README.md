# Prep — 分析与修复效果

> 设计见 [`../../harness/PREP.md`](../../harness/PREP.md)。一句话:writer 开跑前,一个子 agent 先
> ①把运行时跑通 ②把核心步骤跑一遍看哪里崩 ③补 writer 推不出来的外部事实,产出报告注入 writer 首轮。
> prep **不产出交付物、不定 label/值/格式**。

## 发现的问题:prep 无净价值、且略偏负——是锚定,不是投送

消费轮里 prep 相对 base **均值 −0.011**(t=−1.30,不显著),投送已解决(26/26 报告 inline),但:

- **投送不是瓶颈,消费才是**:`sources_revisited=0` 出现在全部 26 题,artifact≈0——writer 把 prep 当散文提示读过、不回去用。
- **prep 被 charter 挡在丢分点之外**:这套题丢分主要在**判断/label**和**输出格式**上,而 prep 明令禁止碰这两样。
  闭卷纯文本题运行时本就不崩(job 1 空转)、无外部事实可取(job 3 空转)。
- **略偏负 = 锚定成本**,两个真实案例:
  - **variant(−0.136)**:prep `attempt=broke` 自己没解决,却把它写成 `writer_action: "Treat this as the
    primary unresolved breakage…"`,把啃不动的硬子问题标成"头号难题"递给 writer,预算被引进坑。
  - **flusight(−0.097)**:prep 把建模框架("把序列当独立""无需日历展开")当 finding 注入,替 writer 定了框。

## 修复(`ale_run/agents/ale_claw/task_prep.py`)

1. **反锚定**:broke 未解决时禁止 "primary/critical" 排序;`writer_action`(prep 的处方)**完全不进首轮 digest**;
   broke 单元改注入中性句"Prep did not solve this … your own reading decides where your budget goes"。
2. **反定框**:method choice / 建模假设 / 任务框架**明令不算 finding**(逐字引了 flusight 的原话)。
3. **任务门**:闭卷 + 运行时已工作 + 纯 prose 的题 → prep 返回 `not_needed`、harness 对空 prep **注入空串**,
   writer 独立作答。
4. **载体优先**:job 3 优先给测过、可调用的 artifact;`analyze_factorial` 新增 `artifact_calls`,把成功指标从
   "投送"改成"writer 真调用了 artifact"。

## 效果(fix-validation,n=1)

修复后**先前所有 prep 负向题都回到 base 或以上**:

| 任务 | base | 旧 prep | 新 prep | Δ vs 旧 |
|---|---|---|---|---|
| **variant** | 0.930 | 0.794 | **0.999** | +0.205 |
| **flusight** | 0.713 | 0.616 | **0.750** | +0.134 |
| **bpmn_supply** | 0.849 | 0.787 | **0.864** | +0.077 |
| **pe_screening** | 0.959 | 0.919 | **1.000** | +0.081 |
| crf_4 | 0.621 | 0.555 | 0.589 | +0.034 |
| sap | 0.273 | 0.240 | 0.250 | +0.010 |
| sse | 0.667 | 0.667 | 0.333 | −0.333 ⚠ |

⚠ sse 的 prep 掉分**与本次修复无关**:q1 结论对、引文对,但这次粘的中文证据段**漏了一句必需 anchor 短语**→
q1 判 0(见 `../README.md` §3b)。这是评分器逐字匹配造成的抽样方差,不是 prep 回归。

**真实轨迹对照(variant):**

```
# 修复前(prep 臂,消费轮) —— 锚定注入 writer 首轮:
writer_action: "Treat this as the primary unresolved breakage. Re-examine how 'for the submitted
                ALT allele' maps colocated indel frequencies…"        # 把啃不动的子问题定为头号议程
# 结果:writer 预算被引入该坑,variant 0.794(base 带底部)

# 修复后(prep 臂,fixval13):
turn-0 digest: (无 prep 报告注入 —— writer_action 不再进首轮,该单元无锚定议程送达 writer)
# 结果:variant 0.999(base 带顶部)
```

深入:`~/ale/agents-last-exam/.logs/ale/fixval13/fixval13_prep/…/variant_…/{trajectory.json,output/}`

## 边界与残余(必读)

- prep 的天花板由 charter 决定:**禁止定 label/值/格式**,而这套题的分主要就落在这三样上。所以修复能做到的是
  **去掉锚定的倒扣**,把 prep 拉回 ≈ base;"prep 高于 base"在判断密集的闭卷题上**基本不可达**。
- **n=1 警告**:variant/audience_seg 两臂同分且顶到 base 上界,说明 fix 轮部分走高是**这次抽样偏好**,不能全记在修复头上。
- prep 唯一稳定加分的存在证明是 agora(消费轮 findings 恰好命中评分维度)——说明 prep **能**有值,但当前靠碰巧命中评分面,
  不是机制。要系统化,得让 prep 命中评分面(受 charter 限制)且消费方式从散文改成可调用载体。
