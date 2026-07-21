# prep v18 六题配对实测（2026-07-21）

`exp_prep_v18_six_pair.yaml` 于 2026-07-21 在 pgl 跑完，base 与 prep 同 endpoint、同 task
version、同轮交错，各六题，日志在 `.logs/ale/prep_v18_six_pair`。任务清单见
[tasks.txt](tasks.txt)。本文是该轮的完整分析，PREP.md 与 FABLE.md 只引用结论。

## Prep 产出

| 题目 | 环境 | 清单 | findings | artifact | input token | 耗时 | dropped |
|---|---|---:|---:|---:|---:|---:|---|
| Agora | ready | 22 | 5 | 0 | 35,100 | 220 s | 报告截断 |
| Digital | partial | 24 | 6 | 1 | 36,952 | 296 s | 2 个 `.toml` 路径非法，截断 |
| SEC | ready | 19 | 4 | 1 | 75,635 | 296 s | 1 条 writer_action 越界 |
| Variant | ready | 24 | 5 | 2 | 106,197 | 582 s | 截断 |
| BPMN | blocked | 24 | 5 | 2 | 334,767 | 796 s | 截断 |
| Bias | ready | 20 | 3 | 0 | 359,161 | 996 s | 2 条越界，1 个 artifact 读不到 |

生成率 6/6，v17 是 0/6。四题打满 24 条清单上限，四题报告触到 12,000 字符被截断。成本方差
一个数量级，35k 到 359k input token。

BPMN 的 `blocked` 是 v17 协议下拿不到的那类事实：prep 自己在 `/tmp/ale-docker.sock` 起了
vfs 私有 daemon，拉到 Flowable 镜像层后卡在 `unshare: operation not permitted`，据此判定这个
嵌套 VM 跑不了镜像层。v11 复盘里两臂在 Docker 从未启动的情况下都编出 67/67 pass，现在
writer 开题就知道运行时自检这条路是假的。

## 配对分数

| 题目 | base | prep v18 | 差 |
|---|---:|---:|---:|
| SEC 10-K | 0.6609 | 0.9235 | +0.2626 |
| Bias | 0.0 | 0.0 | 0 |
| BPMN | 0.8438 | 0.8295 | -0.0143 |
| Digital | 0.9042 | 0.8708 | -0.0334 |
| Variant | 1.0 | 0.7930 | -0.2070 |
| Agora | 0.6900 | 0.3452 | -0.3448 |

均分 0.68315 对 0.62700，差 `-0.05615`，sd `0.20645`，`t=-0.666`，n=6。

按预注册判据：生成率一条通过；"清单条目到分项提高的完整链"没有出现；harm rate 明显超出
噪声区间。因此这一轮不支持扩到 26 题。

## Agora 的 -0.3448：清单造成的定向优化

用题目原 scorer（`tasks/legal/agora_governance_classify_instance_1/scripts/score_outputs.py`）
对两臂输出重跑，分类标签几乎没变，三份文档里两份的 `scope_f1` 完全相同。整个下跌来自
`evidence_gate`：

| 文档 | base pass_rate / gate | prep pass_rate / gate |
|---|---|---|
| 768 | 0.846 / 1.0 | 0.571 / 0.5 |
| 2047 | 0.909 / 1.0 | 0.636 / 0.5 |
| 1293 | 0.667 / 0.5 | 0.333 / 0.5 |

scorer 的规则是 `pass_rate >= 0.8` 给 1.0 否则 0.5，再乘到三个分项上，所以分数正好腰斩。

逐条验证失败原因：prep 臂的引文**全部通过原文子串检验**，无一例外。失败在另外两个条件
上，scorer 要求引文至少 `MIN_EVIDENCE_WORDS = 5` 个词，并且必须包含该类目的关键词。base
的引文中位数 28 词、最短 9 词、没有一条低于 8 词；prep 臂中位数 11 词、最短 3 词、7 条低于
8 词，例如 `frontier AI models` 只有 3 个词。

prep 清单的第 7 条和第 10 条反复要求"evidence 必须是缓存原文的精确子串"，writer 于是把引文
压缩成能保证逐字对上的最短片段。它优化了清单点名的那一维，代价是清单没提的两维。

这是合同清单作为**部分阅读**的结构性风险，不是这份清单写错了。任何只读公开题面的清单都
无法知道 `MIN_EVIDENCE_WORDS` 和关键词表的存在，而一旦清单强调某个维度，writer 就会在
未被点名的维度上让步。清单越具体、越有约束力，这个效应越强。

## 一条历史结论的纠正

1293 的 `legislative_status` 真值是 `Hard Law`。这一轮 base 答对，prep 臂答成 `Other`。
[EVOLUTION.md](../../EVOLUTION.md) 和 26 题 canary 记录中把 v15 Agora prep "将 1293 标为
`Other`" 列为正向采用链，该判断是错的，它是一次伤害。

## 采用链：三题 artifact 零调用

- SEC：prep 把运行时配好并给出已验证命令，writer 的 29 次 exec 里
  `ale-task-prep`、`UV_PROJECT_ENVIRONMENT`、`python_with_task_deps`、`manifest_lookup`
  各出现 0 次。分数上去的真实原因是这一轮 writer 自己想到去 `data.sec.gov` 的 XBRL
  companyfacts API 取权威财务数据，base 臂没走这条路（两臂都用 pdftotext，`data.sec.gov`
  在 base 轨迹里 0 次）。**+0.2626 不能归因给 prep。**
- Variant：prep 交付了官方 severity 排序和五个 indel 位点，`vep_rules.py` 与
  `VEP_SEVERITY` 在 writer 轨迹里各 0 次。最终 0.7930 与历史 base、v15、v17 三次完全相同，
  是"未修 indel lookup"的稳定取值。
- Digital、BPMN：差值都在历史噪声区间内。

报告内联保证了 exposure，没有保证 writer 会去执行 staged 的文件。这与 v15 26 题的老结论
一致，v18 没有改善它。
