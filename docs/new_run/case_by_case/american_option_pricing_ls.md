# business_finance/american_option_pricing_ls 题目拆解

## 一句话概述

用蒙特卡洛加 Longstaff-Schwartz 最小二乘回归给美式期权定价，从有闭式解的欧式期权校准，到单资产美式看跌，再到 5 资产相关篮子美式看跌并算 Greeks。交两个文件，评分是确定性的 Python 打分脚本，分值只有 0.0、0.5、1.0 三档。

---

## 一、题目源在哪

这题属于 `agents-last-exam`（ALE）基准，`task_card.json` 里记的 `sourceSubmissionId` 是 `2090fc20-6faf-425c-9c12-145afde1af35`，分类是 `business_finance` 下的 `quant_finance`（子域 6.7）。

本机（batchcom）上的完整题目源在 zmh 的副本里，分两块。

题目定义（代码，进 git 仓库）：
`/home/dataset-local/zmh/ALE_TEST/agents-last-exam/tasks/business_finance/american_option_pricing_ls/`

- `main.py`：任务配置、`task_description`（发给 agent 的提示词）、`start()` 装载、`evaluate()` 打分入口。
- `task_card.json`：任务元信息，含 taskPrompt、要交的文件、evaluation 说明、VM 规格。
- `scripts/score_american_option_outputs.py`：真正的打分逻辑，`score_submission()` 是核心。

题目数据（不进 git，单独 rsync 到远端 `~/ale/agents-last-exam/task-data/`）：
`/home/dataset-local/zmh/ALE_TEST/agents-last-exam/task-data/business_finance/american_option_pricing_ls/base/`

- `input/problem_spec.md`：完整题面，agent 能看到，248 行，含全部参数、算法步骤、输出 schema、自检清单。
- `input/runtime_env/pyproject.toml`、`uv.lock`：钉死版本的 NumPy/SciPy 运行时。
- `software/python.sh`：题目指定的 Python 入口，内部用 `uv run --frozen` 拉起上面那套运行时，环境装到 `output/.agent_runtime_env`。
- `reference/results.json`、`reference/exercise_boundary_tier2.npy`：隐藏的参考答案，只有打分时读，agent 看不到。
- `reference/option_solver.py`：出题方的参考实现，用来生成上面两个参考文件，不参与打分。
- `reference/reference_manifest.json`：记录哪些是 agent 可见输入、哪些是参考文件、要求 agent 交哪些输出。

VM 规格（`task_card.json` 的 `vm` 字段）：机型 `c4-standard-4`，镜像 `cpu-free-ubuntu`，超时 7200 秒。题面自检里另写了「8 小时 wall-clock、4 核约 3GHz」的上限，参考解 Tier 2 实测约 0.53 秒，所以时间不是瓶颈。

---

## 二、题目做什么（三个 Tier）

三个 Tier 难度递增，共用同一套 GBM 模拟约定：风险中性测度下用精确对数正态公式推进价格，禁止用 Euler 离散，随机数种子统一 `numpy.random.default_rng(77777)`。

### Tier 1：欧式看跌，Black-Scholes 校准

参数：S0=100，K=100，r=0.05，sigma=0.2，T=1.0。

要做四件事：算 Black-Scholes 闭式看跌价；算 Greeks（Delta、Gamma、Vega、Theta）；跑 10 万条路径的蒙特卡洛；验证 MC 价落在 BS 价的 2 倍标准误之内。这一层是校准，确认模拟框架本身没写错。

### Tier 2：单资产美式看跌，Longstaff-Schwartz

参数：S0=100，K=110（实值），r=0.05，sigma=0.2，T=1.0，10 万条路径，100 个时间步（即 100 个可行权时点），回归多项式次数 3。

这一层是题目的主体，要点在于 Black-Scholes 在这里会算错。BS 给的是欧式价约 10.68，而实值美式看跌可以提前行权，真实价约 12.00，提前行权溢价约 1.25，占欧式价约 12%。用 BS 给美式看跌定价，绝对误差会超过 1.0。

Longstaff-Schwartz 的做法是在模拟路径上做反向归纳：在每个行权时点，把「继续持有的未来贴现现金流」对「当前状态变量的多项式基」做横截面回归，估出继续持有价值，当即时行权收益超过它就行权。题面点名了几个实现细节：只用实值路径进回归；回归前把 S 标准化再造多项式基（否则 S 在 100 附近时 degree-3 的 Vandermonde 矩阵病态）；实值路径数少于 poly_degree+1 就跳过这一步；时间 0 不作为行权时点。

还要输出行权边界：每个时间步记录当步行权路径里的最高资产价，连起来就是估计出的提前行权边界。

### Tier 3：5 资产相关篮子美式看跌加 Greeks

参数：5 个资产，S0 全 100，sigma=[0.18, 0.22, 0.25, 0.20, 0.28]，篮子权重=[0.25, 0.20, 0.20, 0.15, 0.20]，篮子行权价 K=95，r=0.05，T=1.0，两两等相关 rho=0.3，20 万条路径，100 步，回归次数 3。

篮子价是 5 个资产的加权和，看跌收益是 max(K − B(t), 0)。相关路径靠对相关矩阵做 Cholesky 分解，每步先取 5 个独立标准正态 epsilon，再 Z = L @ epsilon 得到相关增量。回归基比单资产丰富：篮子价及其各次幂，加每个资产价的一次和二次项（标准化），共 1 + 3 + 2×5 = 14 个特征；要求实值路径数至少 2×poly_degree×N_assets+1 才做回归。

Greeks 用 pathwise 法在冻结行权边界的前提下算：先用 LS 定出每条路径的停时 tau，再对贴现收益就参数求导，行权决策保持不变。Delta_j 对初值 S0_j 求导，Vega_j 对波动率 sigma_j 求导，题面给了两者的逐路径导数公式。

---

## 三、硬性要求

来自 `main.py` 的 `task_description` 和 `problem_spec.md` 的 Constraints：

- 只能用 Python + NumPy + SciPy。禁用 QuantLib、py_vollib 等期权库，禁用 autograd、JAX、PyTorch、TensorFlow 等自动微分框架。
- GBM 必须用精确对数正态公式，不能用 SDE 的 Euler 离散。
- 严格照题面的固定种子、路径数、回归设计、输出 schema。
- Tier 1 和 Tier 2 是拿分的必要条件，Tier 3 是拿满分的必要条件。
- Tier 3 做不完就如实留空，不要伪造 Tier 3 的指标；Tier 1/Tier 2 的输出要真实。
- 不许改 `base/output` 以外的任何文件。
- 环境：Python 3.10+，NumPy≥1.24，SciPy≥1.10，Matplotlib 只用于可选画图。

---

## 四、要交什么

两个文件，都写到 `base/output/`：

1. `results.json`：三个 Tier 的结果，字段 schema 在 `problem_spec.md` 第 185 行起有完整定义。Tier 1 含 bs 价、四个 Greeks、mc 价与标准误、mc_within_2se；Tier 2 含 bs 欧式价、美式价与标准误、从同一批路径算的欧式 MC 价、提前行权溢价、两个布尔判据、10 个采样的边界值；Tier 3 含篮子美式价与标准误、欧式 MC 价、溢价、5 个 delta、5 个 vega、加权 delta 和。
2. `exercise_boundary_tier2.npy`：shape 为 (100,) 的 NumPy 数组，第 t 项是第 t 步行权路径的最高资产价，该步无人行权则为 NaN。

`results.json` 里 Tier 2 的 `exercise_boundary_sample` 必须是 `boundary[::10]` 这 10 个采样点（NaN 写成 null），打分时会逐点比对，防止 JSON 和 npy 对不上。

---

## 五、用什么评测

确定性的 Python 打分脚本，没有 LLM 裁判，没有人工。评分链路：

`main.py` 里的 `evaluate()`（被 `@cb.evaluate_task` 装饰）读取 agent 交的 `output_files` 和隐藏的 `reference_files`，两组都是 `{results.json, exercise_boundary_tier2.npy}`，把字节流传给 `scripts/score_american_option_outputs.py` 的 `score_submission()`，返回 `[report.score]`。ALE 本地 harness（`ale_run`）的 `TaskDriver.evaluate()` 拿 `result[0]` 作为这题的最终分。

打分是对照隐藏参考答案 `base/reference/results.json` 和 `base/reference/exercise_boundary_tier2.npy` 判的，不是重跑 agent 的代码。

分值三档（`score_american_option_outputs.py` 第 438 行起）：

- 1.0：Tier 1、Tier 2、Tier 3 全过。
- 0.5：Tier 1、Tier 2 过，Tier 3 缺失或没过。
- 0.0：缺文件、`results.json` 解析失败，或 Tier 1/Tier 2 任一没过。

---

## 六、怎么评测（逐条判据）

打分前的门槛：参考文件必须齐；`results.json` 必须存在且是合法 JSON，否则直接 0 分；`exercise_boundary_tier2.npy` 缺失则 Tier 2 直接判负（连带 Tier 3 一般也拿不到满分）。每个 Tier 先校验固定常量字段（浮点容差 1e-9），字段缺失或对不上就该 Tier 失败。

### Tier 1 判据

- 常量：S0=100、K=100、r=0.05、sigma=0.2、T=1.0、mc_n_paths=100000。
- bs_price、bs_delta、bs_gamma、bs_theta 对参考的绝对误差 ≤ 1e-4；bs_vega ≤ 1e-2（Vega 量级大，容差放宽）。
- mc_stderr > 0；mc_within_2se 字段必须为 true。
- 脚本自己再算一遍 |mc_price − bs_price| ≤ 2×mc_stderr，光靠交上来的布尔值不算数。

### Tier 2 判据

- 常量：S0=100、K=110、r=0.05、sigma=0.2、T=1.0、n_paths=100000、n_steps=100、poly_degree=3。
- bs_european_put 对参考误差 ≤ 1e-4。
- |american_put_price − 参考| ≤ 0.20。
- american_put_se < 0.05。
- 溢价自洽：|(american_put_price − european_mc_from_paths) − early_exercise_premium| ≤ 1e-6。
- early_exercise_premium > 0.5；premium_positive 为 true；bs_underestimates 为 true。
- 行权边界（`_validate_boundary`）：shape 必须 (100,)；数值型；有限项 ≥ 80；非零有限项 ≥ 80；非零有限项全落在 [70, 115]；`boundary[::10]` 的非零有限采样 ≥ 7 个；采样序列的单调违背（相邻差 < −1e-6）不超过 2 次；最后 10 项的中位数 > 95；`results.json` 里的 `exercise_boundary_sample` 必须长度 10，且逐点等于 `boundary[::10]`（容差 1e-8，null 对应 NaN）。

### Tier 3 判据

- 常量：n_assets=5、S0 五个 100、sigma 五元、weights 五元、K=95、r=0.05、T=1.0、rho=0.3、n_paths=200000、n_steps=100、poly_degree=3。
- |american_basket_put_price − 参考| ≤ 0.30。
- american_basket_put_se 在 (0, 0.05) 开区间内。
- 溢价自洽同 Tier 2，容差 1e-6；early_exercise_premium > 0。
- 5 个 delta 全 < 0；5 个 vega 全 > 0（看跌篮子的方向性检查）。
- 每个 delta、每个 vega 与参考的比值 |actual|/|ref| 落在 [1/3, 3]，即量级不能偏离参考 3 倍以上。
- 加权 delta 和自洽：sum(w_i × S0_i × delta_i) 与交上来的 weighted_delta_sum 差 ≤ 1e-6。

另外脚本会把 `boundary_mae_vs_reference`（边界和参考的平均绝对误差）写进 notes，只作记录，不进分数。

---

## 七、参考答案的目标值

来自隐藏的 `base/reference/results.json`，用于对表：

- Tier 1：bs_price 5.5735，bs_delta −0.3632，bs_gamma 0.01876，bs_vega 37.524，bs_theta −1.6579，mc_price 5.582，mc_stderr 0.0274。
- Tier 2：bs_european_put 10.675，american_put_price 11.998，american_put_se 0.0270，european_mc_from_paths 10.744，early_exercise_premium 1.254。
- Tier 3：american_basket_put_price 2.376，se 0.00888，european_basket_put_mc 2.128，early_exercise_premium 0.248，deltas 约 −0.041 到 −0.068，vegas 约 4 到 5.4。

对应题面自检：Tier 1 的 BS 价约 5.57、Delta 约 −0.36；Tier 2 的欧式价约 10.68、美式价约 12.00、溢价约 1.0 到 1.5、边界从早期约 90 单调升到接近行权价；Tier 3 全部 delta 为负、全部 vega 为正、篮子美式价高于欧式价。

---

## 八、失分的典型形态

按 `task_card.json` 的 evaluation 说明和打分逻辑，拿不到 1.0 通常是这几种：缺输出文件；只在 JSON 里编指标而 npy 对不上；行权边界不合理或和 JSON 采样不一致；Tier 2 的美式价塌回欧式价（说明提前行权逻辑没生效）；Tier 3 的 Greeks 符号错或量级偏离参考 3 倍以上。Tier 1/Tier 2 如实做出、Tier 3 缺失，拿 0.5。
