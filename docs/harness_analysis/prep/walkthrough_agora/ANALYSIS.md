# Prep 轨迹走查 —— prep 的 MD 如何影响 writer(真实文件)

任务:`legal/agora_governance_classify_instance_1` · 消费轮 prep 臂 · 得分 0.621(base 0.525)。
这组是**未加工的原始文件**,给同事直接核对 prep→writer 的因果。

## 文件清单(本目录)

| 文件 | 是什么 |
|---|---|
| `task_prep.md` | **prep 子 agent 写的完整报告**(writer 可在 VM 里打开的 `PREP_REPORT.md` 原文) |
| `turn0_digest_shown_to_writer.md` | **注入 writer 首轮的摘要**(从 turn-0 原始 API 请求里切出的 `## Task-specific prior research` 段) |
| `turn0_api_start.json` | writer 第 0 轮的原始请求(摘要即在此,可自行核对未被裁剪) |
| `trajectory.json` | writer 的完整轨迹(工具调用、输出) |
| `eval_result.json` | 该单元得分 |

## prep 提供了什么(看 `task_prep.md`)

三段:**Runtime [ready]**(运行时可用、3 份缓存文档 SHA 校验通过、给了可复现命令)· **Core step [completed]**(prep 真跑了一遍跨文档正则检索)· **Findings**(5 条),其中命中评分维度的关键两条:

1. **Canonical evidence precedence** —「证据以 input/documents 缓存文本为准,逐字保留字符/空格/标点/OCR 痕迹,不要用公网更干净的措辞替换」。
2. **Legislative status test is enforcement-based** —「按 enforcement 判定法律地位,而非看『Act/Policy』字样」。

这两条正是 agora 评分的两个维度(逐字证据 + 法律地位标签)。

## writer 怎么被影响的(看 `trajectory.json`)

**可复现的因果链:**
1. 首轮 writer 收到 `turn0_digest_shown_to_writer.md`(摘要:runtime + core-step + findings 的 title/observation)。
2. writer **主动打开了完整报告**——轨迹里第一个相关工具调用:
   ```
   [read] path=/media/user/.../base/task_prep/PREP_REPORT.md
   ```
   (在 `trajectory.json` 搜 `PREP_REPORT` 可定位。)
3. 之后 writer 的分类与取证按报告的两条指引走(逐字复制缓存证据、按 enforcement 判定地位)。

## 怎么读 / 值得注意

- **机制是真的、可追的**:prep 写 MD → 注入摘要 → writer 打开完整报告 → 按 findings 作答。整条链在文件里都能核。
- **但得分效应是噪声**:agora 消费轮 prep 0.621 高于 base 0.525,看着像价值;**换一次抽样(最新代码 clean3)prep 掉到 0.359、跌破 base**。agora base 自身抖动就是 0.48–0.69。所以「prep 报告确实改变了 writer 行为」成立,「因此稳定加分」不成立。详见总览 `../../index.html` §4。
- 对照:prep **负面**影响的真实轨迹见 `../../trajectories/variant_prep_BEFORE/`(prep 把没解决的断点标成"头号难题"→ writer 被带进坑)。
