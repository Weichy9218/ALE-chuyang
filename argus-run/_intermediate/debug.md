# Argus-on-ALE 调试与运行记录

活文档。记录用 Argus 四角色 harness 跑 ALE 的数据、配置、轨迹位置,以及跑动中
发现的每个问题和解法。目的是让下一个人不重复踩坑。最后一次事实更新见文末时间戳。

---

## 1. 结论速览(当前快照)

- 接入成功:Argus 作为 ALE agent 跑通,完整 Manager→Planner→Engineer→Reviewer 循环,
  产物落在题目要求的精确路径,轨迹正常解析。
- **目标:跑完 ALE-CLI 全 105 题。105 题数据全部完整,无缺失**(按正确变体核验,见第 4 节)。
- 已跑 41 题,其中 **26 题是可信得分**(均值 0.704,10 题满分)。其余是环境噪声:
  10 题 Boyue 网关断流的假 0(可重试),5 题数据缺失(传完可跑)。剩余题数据传输 + 跑动进行中。
- 质量:控制掉网关断流后,Argus(gpt-5.6-sol,四角色)与 ale_claw 历史 base 打平到略优
  (26 题合并 best-of 时配对均值 +0.009,t=0.16)。明确胜出:ct_geometry 0→1.0(base 从没解出)。
- 成本:每题约 8× ale_claw 的 token,是多角色编排的固有代价。

---

## 2. 代码接入(都在 ALE 主仓库 ale_run/)

新增 agent 包 `ale_run/agents/argus/`(纯新增,安全):
| 文件 | 作用 |
|---|---|
| config.py | ArgusConfig。模型半边 → `codex_config()` 转成 CodexConfig;角色半边 → `role_env()` 转成 ARGUS_SKILL_* |
| deployer.py | ArgusDeployer,install/launch/parse_artifacts,只支持 sandbox(in-VM) |
| _launcher.py | VM 内驱动进程,跑 `_invoke_supervisor`;把 ALE 题面播种进 backlog(见问题 3) |
| events_to_trajectory.py | argus 事件日志 → ALE trajectory |
| _vendor/argus_skill-*.whl | argus-skill wheel(PyPI 没有,随源码 ship 进沙箱) |

两处对既有共享文件的**定点补丁**(不是整文件覆盖,见问题 1):
- `orchestration/factory.py`:加一行 `"argus"` registry 条目
- `executors/sandbox.py::_ship_ale_subtree`:加 `"agents/*/_vendor/*.whl"` ship pattern

**为什么只能 sandbox(in-VM):** ale_claw 是唯一 host 端 agent,因为它自己实现工具层、
每次调用都是对 VM 的 RPC。Argus 的执行面是 codex CLI 自带 shell,作用在 codex 所在机器上。
host 端跑,四角色会在 harness 机器上干活,而产物本该出现在 VM。装进 VM 后:题目精确路径变成
本地路径、harness host 物理不可达、只剩 GUI 需要 cua MCP 桥(和 codex agent 同样接法)。

---

## 3. 配置(argus-run/agent_argus_full4.yaml)

关键点,踩过坑才定下来的:
- `model: gpt-5.6-sol`(**不带** openai/ 前缀;那是 litellm 前缀,直连 Boyue 网关会 503)
- `provider: openrouter` + `base_url: ${env:OPENAI_BASE_URL}` + `api_key: ${env:OPENAI_API_KEY}`
- 四角色 reasoning effort 全 xhigh/high;网关自己确认支持 xhigh
- `model_context_window: 128000`(= ale_claw 的 CONTEXT_WINDOW_OVERRIDE,两臂同预算)
- `model_catalog_path`:可选。codex 无 catalog 也能跑该模型;catalog 见 model_catalog_boyue.json
- `manager_division: false`:钉死 vertical=ale_last_exam,省一次可能判错的 Manager 分类
- `cost_control: false`:网关模型未定价,argus 默认 unpriced 策略是 block,会拒每次调用
- `argus_package: ""`:用 vendored wheel

---

## 4. 数据与可跑范围

- 规范清单:`/home/dataset-local/zmh/ALE_TEST/agents-last-exam/selected_tasks/ale_cli.txt` = **105 题**
- 那份 zmh 副本是评测方副本,带隐藏 `reference/`。**105 题全部数据完整(input+reference 都在)**,
  没有任何题因数据缺失而无法打分。
- **重要纠正(问题 7):** 变体名不总是 `base`。9 题用别的变体:
  pe_screening=`zscaler_fy2025`、ct_geometry=`instance_1`、celegans=`137`、
  cp_test_gen=`default`、ising=`n10_critical_u01_correlators`、k3=`h_4_4_4_m_1_8`、
  wsi=`center_point`、idp_ensemble=`default`、aerobics=`variant_1`。
  一度误判这 9 题"无 reference",其实是只查了 base/ 变体。正确变体映射在
  `~/argus/config/task_variants.txt`(每行 `task<TAB>variant`)。
- pgl 本地原本 35 题、传输后 86 题数据完整(按正确变体计)。缺 19 题需继续传。
  HF 镜像不含 reference,不能用来打分,数据必须从 zmh 副本传。
- **带宽是硬约束:** pgl 出口 ~1 MB/s(scp 和 HF 镜像实测一样,瓶颈是 pgl 的链路)。
  策略:小题先传即可跑;6 个巨型题(radiomics 12G、idp 12G、scene2 8G、skullstrip 7G、
  wsi 3G、celegans 1.5G,共 44GB)后台慢传,能到多少跑多少。

---

## 5. 跑动中发现的问题和解法

### 问题 1 — 整文件覆盖 pgl 的共享文件会炸掉整个包
pgl 的 `ale_run/` 与 batchcom 本地**已分叉**(sandbox.py 781 行 vs 801,`_secrets.py`
缺 `split_config_secrets`)。我一度用 rsync 整份覆盖 sandbox.py,导致 `ale_run.executors`
import 失败——那棵树上还跑着别人的实验,新起的进程都会死。约 90s 内发现并回滚,期间
结束的两个 run 是自己正常跑完的,是运气不是设计。
**解法:** 只做定点补丁——先 `cp <file> ~/argus/notes/<file>.bak`,再用锚定字符串的幂等
Python 补丁脚本改,改完 `.venv/bin/python -c "import <module>"` 验证。新增文件安全,改既有文件危险。

### 问题 2 — wheel 没被 ship 进沙箱(第一次 smoke install 失败)
`_ship_ale_subtree` 的 ship pattern 是固定白名单,没有 `.whl`。argus-skill 不在 PyPI,
沙箱又读不到 harness host,wheel 无路进去。
**解法:** 白名单加 `"agents/*/_vendor/*.whl"`,wheel 随 ale_run 树一起 ship。

### 问题 3 — Engineer 收不到题面(第二次 smoke 全 0 风险)
Argus supervisor 只在 backlog 空时叫 Planner,而它生成的 backlog item 是模板化的
"Goal Gate mission",objective 让 engineer "re-read the original operator objective" —
那段文字根本不在 prompt 里。实测:8318 字 engineer prompt 带 ALE 角色横幅,但零题面
(无 output 路径、无方法、无产物名)。会全 0。
**解法:** launcher 里把 ALE 题面直接作为 backlog item 的 objective 播种(`_seed_mission`)。
修后 prompt 12853 字,longstaff/output/tier3/.npy/schema 全部出现。smoke 拿到 1.0。

### 问题 4 — Boyue 网关在高并发下 stream 断流(最大的分数杀手)
codex 调用收到 `response.failed` / `stream disconnected before completion`,重连 5 次仍失败,
Engineer backend 连挂两轮触发 `backend_failure_streak=2/2`,mission error 退出,产物没开始写。
判据很干净:断流打成 0 的题输入 token 只有 2-6 万,正常跑完的题都是 200 万-1900 万。
根因是并发过载:26 题 concurrency 3 + 别人 4 个实验同打一个网关。那些实验结束后探网关 5/5 健康。
**解法:** 降并发 + 只重试断流题。retry 9 题在无竞争下重跑,5 题从 0 恢复真实分(sec_10k 0→0.928
等)。**这是最需要注意的规模化风险:concurrency 越高断流越多。** 更稳的做法是给 engineer
backend 加重试退避,或保持低并发。concurrency=5 的 16 题批果然大量断流,印证此点。

### 问题 5 — rsync `--files-from` 配目录条目不传内容(白跑一小时)
`rsync -az --relative --files-from=LIST`,LIST 里是目录条目(`task-data/x/y/`)时,只建空目录
不拷内容——`--files-from` 抑制了 -a 的递归。结果:任务目录数涨了但每个目录 0 文件。
**解法:** 每题一条 `rsync -az SRC/task-data/TASK/ DST:.../task-data/TASK/`(带尾斜杠,正常递归)。
清掉 50 个空壳后重传。

### 问题 6 — shell find 深度计数误判
`find task-data -maxdepth 4 -name input` 数不对(input 在第 5 层),让我以为传输没进展。
**解法:** 用 python `os.path.isdir` 精确判断,别用易错的 find 深度。
另外:**rsync 传输中途查完整性会误判**(input 字母序先于 reference 落地),要等 rsync 进程
退出再统计。

### 问题 7 — 假设变体名是 base,误判 9 题"数据缺失"
ALE 的 task-data 变体名不固定。9/105 题不用 `base`(见第 4 节映射)。只查 `base/` 会把这些题
误判成无 input/reference。harness 自己从题目 metadata 的 `variant_name` 定位变体
(`ale_run/tasks/loader.py`),所以数据必须按**正确变体**传和核验。
**解法:** 先从 batchcom 每题挑出有 input+reference 的变体生成 `task_variants.txt`,
按该映射传输和检查完整性,别硬编 base。

### 问题 8 — rsync 不建多级父目录,传输秒退零文件(必须 --mkpath)
`rsync -az SRC/ DST:.../a/b/c/`,当接收端父目录 `a/b/` 不存在时**立即报错**
(`mkdir ... No such file or directory`,code 11),rsync 只建最后一级、不建多级父目录。
现象:传输"秒完成"但 0 文件。传新题或非 base 变体(父任务目录 pgl 上还没有)时必踩。
一度以为 19 题传完,实际全空。
**解法:** 加 `--mkpath`(rsync ≥3.2.3)。**每次传完必须 `find DST/path -type f | wc -l`
核实,绝不信 exit-0。** 前面 49 小题碰巧成功,是因为它们父目录已存在(同题别的变体)。

### 问题 9 — ssh 在 while-read 循环里吃掉 stdin,循环只跑一次
传输脚本在 `while read ... done < list` 循环体内用 `ssh` 做逐题核验,`ssh` 会读走
循环的 stdin(整个 list),导致循环第一轮后就结束。现象:19 题只传了 1 题就报"全完成"。
**解法:** 循环体内的 ssh 加 `</dev/null`(或 `ssh -n`);或干脆循环内不放 ssh,传完统一核验。

### 问题 10 — 移动目录后脚本用相对路径,cwd 不对导致 scored=0
把 run 输出根从 `logs/` 移到 `runs/` 后,loop 脚本里 `make_scoreboard runs/run26/...` 是相对路径,
而 loop 的 cwd 是 `~/ale/agents-last-exam`(不是 `~/argus`),解析到不存在的路径,算出 scored=0,
差点把 26 个已跑好的题全重跑。
**解法:** 脚本内所有跨目录路径用绝对(`$ARG=$HOME/argus` 前缀),别依赖 cwd。改动后**先离线
验证** `make_scoreboard` 能找到已有结果,再启动。

### 问题 11 — Boyue 网关是 RPM 速率限流,并发 3 是安全上限
探测(排空后并行发同样请求):conc2 全过,conc3 起就 429(突发),conc4/5/6 都有失败。
这是 Azure swedencentral 的每分钟请求数限流,不是硬并发墙。真实任务里每个角色是**顺序**调用,
task 级 concurrency 3 的请求速率远低于探测,所以 concurrency 3 能跑(run26 印证),
concurrency 5 大量断流(rest/full96 印证)。
**决策:concurrency=3**(满足下限且是经验安全点)。**不往上提——网关撑不住,提了只造更多假 0。**
若将来网关配额提升可再探测上调。更稳的长期方案是给 engineer backend 加重试退避。

---

## 6. 结果文件与轨迹位置

- **得分表:** `argus-run/argus_scores.csv`。列:task, score, run_status, note, tokens, dur, trajectory。
  `note` 语义:`ok`=真实结果 / `gateway_last`=有分但最后一轮断流(分可信) /
  `gateway_zero`=断流假 0(可重试) / `data_missing`=缺数据(待传) / `ran_zero`=真 0 分。
- **轨迹:** CSV 每行 trajectory 列给出 pgl 上的绝对路径。run 根目录:
  `~/argus/logs/{run26,retry,rest}/…/v0/<ts>/trajectory.json`,同级有 run.json、eval_result.json、
  events.jsonl,以及 origin_log/argus/ 下的 argus 原始事件日志。
- **重新生成得分表:** 在 pgl 上 `cd ~/argus && python3 make_scoreboard.py OUT.csv logs/run26/argus_26 logs/retry/argus_retry logs/rest/argus_rest [新的run根]`。

---

## 7. 目录约定(规范化后)

**pgl `~/argus/`:**
```
bin/     所有脚本:loop_run.sh(主循环)、make_scoreboard.py、classify26.py、merge_best.py、compare_*.py
config/  agent_argus_full4.yaml、exp_argus.yaml(canonical,concurrency 3)、
         model_catalog_boyue.json、task_variants.txt(105 题→正确变体)、ale_cli_105.txt;
         _archive/(历史 exp 和临时清单)
dist/    argus_skill wheel
runs/    所有 run 输出根(结果+轨迹):run26 / retry / rest / full96 / loop/<ts>
logs/    driver 和每轮 stdout 日志
notes/   共享文件改动前的 .bak + 幂等补丁脚本(register_argus.py / patch_ship_vendor.py)
src/     argus-skill 源码(重建 wheel 用)
docs/    历史结果文档
argus_scores.csv   当前得分表(loop 每轮自动重写)
```

**batchcom `/home/dataset-local/wcy/ALE-chuyang/argus-run/`:**
```
README.md  debug.md  argus_scores.csv
bin/       make_scoreboard.py / classify26.py / merge_best.py / compare_argus.py
config/    agent_argus_full4.yaml / exp_argus.yaml / model_catalog_boyue.json /
           task_variants.txt / ale_cli_105.txt
```
batchcom 侧是 source of truth(改配置/脚本在这改,再 scp 到 pgl);pgl 侧跑实验、存结果。

---

## 7b. 目标条件逐项核验(2026-07-25)

| # | 要求 | 状态 | 证据 |
|---|---|---|---|
| 1 | model_catalog_boyue.json 含 xhigh + context,填进 model_catalog_path | ✅ | 探测 Boyue /responses 确认支持 xhigh(端点自报 none/minimal/low/medium/high/xhigh);context=128000(= CONTEXT_WINDOW_OVERRIDE);catalog 逐字段实测能 load 并完成 turn;live 配置第 22 行 `model_catalog_path` 已接,_entry.log 显示"model catalog written" |
| 2 | argus_package 指向带 ale_last_exam vertical 的版本 | ✅ | argus_package="" 用 vendored wheel;wheel 内含 4 个 ale_last_exam 文件;install() 有运行时断言 load_vertical('ale_last_exam') 失败即报错 |
| 3 | VM 镜像 python 版本 | ✅ | 镜像 PATH 上是 3.10,但 deployer 跑在 /opt/ale-run/.venv/bin/python = **3.12.13**(满足 argus >=3.11) |
| 4 | pgl 统一 argus/ 文件夹 | ✅ | ~/argus/{bin,config,runs,logs,notes,docs,src,dist} 规范化 |
| 5 | 先只跑 Linux 题 | ✅ | 核 105 题 task_card:全部 image=cpu-free-ubuntu,零 Windows/GUI 题。ALE-CLI 105 题本身即全 Linux |
| 6 | 单题 smoke + debug | ✅ | american_option smoke score=1.0,修了 3 个接入缺陷 |
| 7 | 26 题子集 vs ale_claw base 比分数成本 | ✅ | 合并 best-of 配对均值 +0.009(t=0.16),打平;成本约 8× token。见 docs/RUN26_RESULTS.md |
| 8 | 明早至少跑通 26 题,26 检查通过才跑 105 | ✅ | 26 题已跑通并对比;wcy 随后明确指示"跑剩下的题"才进 105 |

## 8. 当前运行机制(全自动)

`bin/loop_run.sh` 在 pgl 后台跑,自动收敛到 105 题:
每轮 → make_scoreboard 算出已可信跑分的题 → to_run = 正确变体数据已就位 且 未跑分 →
concurrency 3 跑 → 重复;空轮 sleep 10 分钟等更多数据传到。105 全跑分则退出。
`gateway_zero`(断流假 0)不算已跑分,会被自动重试。启动:
`cd ~/ale/agents-last-exam && nohup bash ~/argus/bin/loop_run.sh > ~/argus/logs/loop_main.log 2>&1 &`

## 9. 交接点

1. 目标全 105 题,数据无缺失,按 `config/task_variants.txt` 核验(勿硬编 base)。
2. 6 个巨型题(radiomics/idp/scene2/skullstrip/wsi/celegans,共 44GB)数据后台传,
   ~1MB/s 要约 12h;传完 loop 自动纳入。除这 6 题外今晚可全跑分。
3. loop 每轮自动更新 `argus_scores.csv`。最终若巨型题没传完,表里如实是 data_missing。

---

_最后事实更新:2026-07-25 ~15:40。105 题数据全部完整(无缺失)。文件夹已规范化
(bin/config/runs/…)。并发定为 3(网关 RPM 限流,探测确认撑不住更高)。
scored=31 可信(均值 0.675,11 满分);loop @conc3 正在跑 to_run=61(含 19 断流重试 + 新到位题);
19 题数据用 --mkpath 正确重传中(5/19,含 6 巨型题)。_
