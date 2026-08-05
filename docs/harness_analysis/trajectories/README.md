# 抽样轨迹 — 两个 bug 的修复前/后对照

每个目录含该单元的 `trajectory.json`(完整轨迹)、`output/`(交付物)、`eval_result.json`(得分)、`run.json`。
挑的是两个倒扣 bug 的 before/after,直接对照能看清缺陷本身和修复效果。

## 1. verifier 过度对冲(sse_northbound 合规问答,q3)

- **`sse_verifier_BEFORE/`** — 消费轮,得分 **0.333**。在 `trajectory.json` 里搜 `d['q3_software_naming']['conclusion']='Unknown'`:
  writer 先写对 q3=No,收到 verifier 的 `unverifiable` 反馈后,把正确的 No 改成 Unknown → q3 判 0。
- **`sse_verifier_AFTER/`** — 修复验证轮,得分 **0.667**。搜 `NOT TESTABLE FROM PUBLIC MATERIALS` 和
  `not a doubt signal`:反馈改成中性段;轨迹里**没有** q3 改写命令,q3 保持 No。

> 打分是逐题四重(结论/引文/逐字证据/英文),看 `output/research_answers.json` 对照 answer_key。
> q2 两版都答 No(金标准 Unknown)是任务侧的 label 陷阱,与 verifier 无关。

## 2. prep 锚定(variant_annotation 变异注释,indel 频率)

- **`variant_prep_BEFORE/`** — 消费轮,得分 **0.794**(base 0.930)。在 `trajectory.json` 搜 `primary unresolved breakage`:
  prep 把自己没解决的断点标成"头号难题"注入 writer 首轮,writer 的预算被引进这个坑。
- **`variant_prep_AFTER/`** — 修复验证轮,得分 **0.999**。修复后 prep 的处方不进首轮、broke 不许排优先级;
  该单元 turn-0 请求里**无锚定 note**(搜 `prep agent worked` 无命中)。

## 3. 错别字提示实验(legal_ma,未翻盘)

- **`legal_ma_typohint_prep/`** — typohint26h(haoxiang),prep 臂,得分 **0.0**。
  writer prompt 加了"注意错别字"后:在 `trajectory.json` 里搜 `空股股东`(出现 3 次)——agent **注意到了**这个印刷错;
  但 `output/audit_report.md` 里**搜不到**"空股股东"——它把 typo 归一化掉、转而报了语义型的 Finding 6。
  打分器要求逐字"空股股东"+页1定位(target_a),缺失 → 四发现全或无 → 0。
  即:干预改变了行为(注意到),但没变到测量点上(逐字举报)。

## 更多轨迹

完整 26 题在 pgl `~/ale/agents-last-exam/.logs/ale/{consumption_full26,fixval13,typohint26}/`。
