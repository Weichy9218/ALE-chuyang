# ct_geometry_calibration_catphan 轨迹分析

同题、同模型 `gpt-5.6-sol`、同 Boyue 端点。ale_claw 单体 base 得 0.0，Argus 四角色得 1.0。这是 26 题重叠集里的同模型对照。轨迹从 pgl 爬取。

## 文件
```
argus/  Argus 四角色，1.0
  geometry_calibrated.json   交付参数（含自测 ssim/mse）
  run.json / eval_result.json / events.jsonl
  role_events.jsonl          角色逐轮事件
  argus_summary.json         两轮任务摘要与 Reviewer 认证原文
  trajectory.json            完整轨迹
base/   ale_claw 单体 writer，0.0
  geometry_calibrated.json / run.json / eval_result.json / trajectory.json
  calibrate.log              优化器搜索日志
  final.log                  反复撞 voxel 约束的日志
task_card.json               题面与评分说明
```

## 评分
二值。评分器比对交付的 `reconstructed_calibrated.npy` 和隐藏参考图，`SSIM >= 0.95` 且 `MSE <= 4e-6` 才 1.0，否则 0.0。只看重建图，不看 JSON 参数值。

## base 为什么 0
1. LEAP CPU 投影器要求体素尺寸接近标称 0.8。base 反复改体素尺寸（0.833、1.0、0.765），每次报错，它的 MSE 是在被错误破坏的网格上测的。
2. 优化器朝错方向漂，SAD 从 800 走到 951，真值约 786。
3. 最终交的 JSON 是圆整数 784 / 1214 / -2.0，和它自己搜出来的都不一致。
4. 第 86 步自认完成，没有独立核验。

## Argus 为什么 1.0
1. 参数全找对，SAD 786.257、SDD 1217.892、offset -1.9875，还找出角度采样几何（起始角 -0.005°、范围 359.99°、步长 -1.0°、360 视角、tau 0、ramp 阶数 2）。
2. 保持体素 0.8 不动，绕开约束错误。395 次标定评估在案。
3. 第 1 轮 Engineer 后端断流，系统判 continue 换全新会话，第 2 轮成功。
4. Reviewer 从原始 sinogram 用交付几何独立重跑重建，和交付文件逐字节加 SHA-256 比对，独立测出 SSIM 0.9964、MSE 3.68e-8。
5. 第一次 Reviewer 通过后，Goal Gate 仍不认，强制再开一轮认证任务再核一次。
6. 355 步，568 万输入 token，成本 $16.19。

## 注意
每边各一次运行，n=1。ct_geometry 在 26 题四臂里 base/prep/verifier 都是 0，Argus 是 1。这道题的价值在于机制清楚，单点分数需重复才作数。
