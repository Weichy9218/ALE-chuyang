# Verifier 轨迹走查 —— 验证反馈如何影响 writer(真实文件)

任务:`business_finance/sse_northbound_programmatic_trading_01` · 消费轮 verifier 臂(**修复前**) · 得分 0.333(base 0.667)。
这是 verifier「过度对冲」bug 的原始现场:verifier 的反馈把一道答对的题改成了错的。

## 文件清单(本目录)

| 文件 | 是什么 |
|---|---|
| `verifier_feedback_shown_to_writer.txt` | **writer 收到的验证反馈原文**(AUTHORITY / 每条 check / NOT CHECKED / WRITER INSTRUCTION,从轨迹切出) |
| `verifier_writer_check_1.json` | 该次 writer-check 的结构化原始记录(每条 check 的 status/requirement/interpretation/证据) |
| `verifier_suite.json` | 冻结的检查套件(builder 从公开材料生成) |
| `trajectory.json` | writer 完整轨迹 |

## verifier 反馈了什么(看 `verifier_feedback_shown_to_writer.txt`)

关键在 q3:`contract.q3_software_naming.conclusion` 被判 **`unverifiable`**,并附了 builder 的一段**实质论证**(「规则明确允许英文,而题目问的是法文原名……」)。旧版把它和真失败混在一段,末尾 WRITER INSTRUCTION 又说「对任何你**存疑**的结果,重开源、复算、再改」。

## writer 怎么被影响的(看 `trajectory.json`)

**可复现的因果链(在 `trajectory.json` 搜 `q3_software_naming` 定位 step 13):**
1. writer 先写对 q3 结论 = **No**(正确;规则允许英文≠允许任意外文)。
2. 收到上面的验证反馈后,writer 把 q3 当成"可疑",执行了一段改写:
   ```
   step 13  exec:
   d['q3_software_naming']['conclusion']='Unknown'
   d['q3_software_naming']['answer_text']="Unknown. The instruction expressly permits English ..."
   ```
   把正确的 **No 改成 Unknown** → q3 判 0 → 总分 2/3 → **1/3(0.333)**。

## 怎么读 / 值得注意

- **verifier 没断言任何错的东西**:它只是把 q3 标成"公开材料测不了"。是「unverifiable 被混进失败通道 + 那段替 agent 论证的文字」诱导 writer 过度对冲。
- **修复后对照(真实文件):** `../../trajectories/sse_verifier_AFTER/`(fixval13)——反馈里出现独立中性段 `NOT TESTABLE FROM PUBLIC MATERIALS` + 「unverifiable 不是存疑信号」,轨迹里**无 q3 改写命令**,q3 保持 No → 恢复 0.667。
- 这条是 verifier **确定的价值**:修复后「不再帮倒忙」。评分口径与 q2 标签陷阱见总览 `../../index.html` §4/§6。
