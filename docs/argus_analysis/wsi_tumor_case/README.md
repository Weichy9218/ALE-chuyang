# wsi_tumor_localization_1 轨迹分析

病理全切片肿瘤定位。Argus 四角色（`gpt-5.6-sol`）得 1.0。这道题不在 ale_claw 跑的 26 题内，没有同模型单体对照，单体基线取 ALE 的 Qwen3.5-397B 参考运行（模型和 Argus 不同）。Argus 轨迹从 pgl 爬取。

## 文件
```
argus/
  prediction.json      最终交付坐标 {"x":72000,"y":125000}
  run.json / eval_result.json / events.jsonl
  role_events.jsonl    角色逐轮事件
  argus_summary.json   两轮任务摘要与 Reviewer 认证原文
  trajectory.json      完整轨迹
task_card.json         题面
```

## 题目
CAMELYON16 全切片病理图，level-0 分辨率 97792×221184 像素。给 `wsi_tools.py`（读 metadata、缩略图、区域、组织掩膜）。要求定位肿瘤转移灶中心坐标，输出 `{"x":float,"y":float}` 到 `center_point/output/prediction.json`。评分看坐标是否落在隐藏的肿瘤标注区内。

## 两边
| | Qwen3.5-397B 单体基线 | Argus 四角色 |
|---|---|---|
| 得分 | 0.0 | 1.0 |
| 步数 / 输入 token / 时长 | 52 步 / 30 万 / 56 分钟 | 357 步 / 604 万 / 80 分钟 |
| 结果 | completed 但坐标不在肿瘤区 | 坐标在肿瘤区内，成本 $18.86 |

## Argus 过程
- Mission 1 Reviewer 判 done：`prediction.json` 只含该文件、解析为有限浮点 {"x":72800,"y":125500}、无多余键；用 OpenSlide 确认 level-0 尺寸 97792×221184、坐标在界内、level-3 到 level-0 区域可重读；肉眼确认落在密集异型上皮肿瘤组织内，不在正常淋巴组织或肿瘤边界。
- Goal Gate 拦下收尾，开 mission 2 独立认证。
- Mission 2 Reviewer 先判 continue，Engineer 把坐标微调到 (72000,125000)，再判 done，新鲜 level-3/2/0 读取与交付证据图逐一吻合。

## base 为什么失败
单体 52 步跑完标 completed，但坐标落在肿瘤区外。它没有一个独立环节去用 OpenSlide 重读对应区域、做组织学判断确认坐标真指向肿瘤。这一步正是 Argus 的 Reviewer 做的。

## 注意
n=1。单体基线是 Qwen 不是 gpt-5.6-sol，模型不同，这题是「Argus 能做对一类单体做不动的题」的定性例子，不是同模型对照。
