# Harness Analysis

**入口:打开 [`index.html`](index.html)** —— prep 与 verifier 的实验总览(时间线、最新实现、26 题总分表、结论、评测层问题)。
本 README 只放目录地图和两个方法学问答;正文与数据都在 index.html。

## 目录地图

| 路径 | 是什么 |
|---|---|
| [`index.html`](index.html) | **总览 dashboard**(先看这个),覆盖全部 26 题 |
| [`verifier/index.html`](verifier/index.html) | verifier 逐题深挖 + sse 修复前后对照 |
| [`prep/index.html`](prep/index.html) | prep 逐题深挖 + variant 修复前后对照 |
| [`trajectories/`](trajectories/) | 两个 bug 的修复前/后**真实轨迹**(含 output 与得分),见其 README |
| [`master26_scores.csv`](master26_scores.csv) | 26 题 base/prep/verifier(消费轮) |
| [`fixval13_scoreboard.csv`](fixval13_scoreboard.csv) | 修复验证轮 13 题 |
| `../task_analysis/` | 每题 base 失分归因(题面、打分脚本、逐维度) |
| `../harness/PREP.md` · `../harness/VERIFIER.md` | prep/verifier 设计文档 |

## 一句话结论

两个倒扣 bug(verifier 过度对冲、prep 锚定)已修复并在 13 题验证——**先前所有负向题回到 base 或以上**;
但修复只到"去掉害",prep/verifier 净分 ≈ base,"高于 base"在这套题上**测不出**,因为得分由逐字抄录 + label 错配 +
二值门槛决定,而这三样是 prep/verifier 够不着的面。详见 index.html §4、§5。

## 两个方法学问答

**(a) sse 的 q2「恒错点」是题面错误吗?能订正吗?**
是任务侧的 **label 约定错配**(不是事实错误):q2 问"金额是多少"、材料查不到,金标准要 `Unknown`、模型恒答 `No`,
题面从未公布这条约定。**能发现**(某子项在所有运行里稳定归零就是指纹),**能订正但只能由出题方**(accepted 加 No /
改问法 / 公布约定);agent/prep/verifier 都改不了(要么禁止定 label,要么看不到隐藏键)。

**(b) 逐字原文抄录该放 verifier 还是 prep?**
不是作弊(契约明写要 verbatim excerpt)。**verifier 为主**:它已有 `staged_source_consistency` 检查,应把
"证据非逐字/漏引"做成显眼可执行的失败,在交付前拦住 paraphrase。**prep 为辅**:预置源文档原文段供 writer 直接粘。
**残余天花板**:评分器额外要命中**隐藏 anchor 短语**,两者都看不到,所以只能提命中率、不能保证得分——这正是
"评分器不能重构,作答侧就必须具备对齐 input 精确字符串的能力"的含义。
