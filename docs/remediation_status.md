# system_issues 修复状态

对照 `system_issues.md` 逐条给状态。以**实测**为准（compile / 单测 / grep 核对），
不写没验证过的结论。

前提变化（重要）：`ale_run/` 现在是 zmh 框架的**本地快照副本**（commit `1e99f3a` 导入本仓库），
所以框架代码级修复直接改在 `/home/dataset-local/wcy/ALE-chuyang/ale_run/…`，不碰 zmh 的活跃目录、
不动远程在跑评测、不复制 task-data（复用 zmh 那份）。上一版本文档把这些标成"待与同学协调"，已过时。

## 已修并验证（本仓库，commit b3b912b 及更早）

| 编号 | 问题 | 修复位置 | 验证方式 |
|---|---|---|---|
| gitignore | `pi/` 误伤 `ale_run/agents/pi/`，deployer 修复无法入库 | `.gitignore` 改 `/pi/` 锚定根 | `git check-ignore` 确认 deployer 不再被忽略、顶层 `pi/` 仍忽略 |
| 3.1 | pi --mode json 假零分 | `ale_run/agents/pi/deployer.py` `detect_llm_error_stop` | `tests/test_pi_deployer_bugfixes.py` 通过 |
| 8.1 | splitlines 撕碎 Unicode 行界事件 | `deployer.py` parse 改 `split("\n")` | 同上测试（含 U+2028 用例） |
| 6.2 | api_key 明文进 `_spec.json`（139 份落盘） | `_secrets.py`+`sandbox.py`+`docker.py`+两个 entry：密钥字段拆进 `_secrets.json` 侧车、entry 重新挂回 config | `tests/test_spec_keyless.py` 通过（spec 无明文、密钥经侧车往返、api_key_env 不误伤） |
| 4.1 | ensure_node_npm sudo 卡死 180s | `_bootstrap.py` 加 `sudo -n true` 探测 + `sudo -n` 安装 | 实测探测命令 0.3s 返回、绝不挂起 |
| 3.2 | 墙钟超时不杀进程，eval 与 agent 竞争 | `lifecycle.py` 外层 wait_for 加 600s 裕量 + `executor.force_kill()`；`docker.py` 硬删容器；base 加 no-op | compile + 代码走查（inner docker 清理 180s < 600s 裕量，先触发） |
| 3.3 | failed 照评分写 0 分污染榜单 | `lifecycle.py` agent failed 跳过 evaluate、failed 置 score=None、run.json 加 `score_valid` | compile + 走查 |
| 9.1 | 停机信号无人消费，容器泄漏 | `runner.py` gather 与 shutdown 事件竞速，触发即 cancel 各 unit 走 finally 清理 | `tests/test_runner_shutdown.py` 通过（部分结果 + 全部 finally 跑到 + 正常路径异常传播） |
| 9.3 | detached eval 天花板 3300s < 声称 7200s | `tasks/driver.py` `_DETACHED_TIMEOUT_S` 7000 + 更正注释 | grep 确认 |
| 6.1 | `.env` 权限 644 | `chmod 600` | `stat` 确认 |
| 6.3 | env.md 明文 HF token | 改"见 secret/.env" | grep 确认 docs 无 `hf_` 明文 |
| 1.1 | rsync `--files-from` 丢内容 | env.md 命令改 `rsync -ar` + 校验注释 | 本地复现：旧命令 0 文件、`-ar` 拷全 |
| 7.2 | 镜像分发排序 | env.md 补 zstd+rsync 续传方案 | 文档（方案性） |

说明：3.2/3.3 是编排层改动，只做了 compile + 逐行走查，**没有跑通 Docker 全链路集成测试**（那需要起容器、
占 batchcom 资源）。真正上线前建议先 1 题冒烟验证这两条不破坏正常路径。

## 待你操作（轮换凭据，我无法代做，你明确排除的部分）

密钥已泄露的补救必须你在控制台吊销换新。收紧权限/删明文已做，但**旧凭据仍有效，必须轮换**：

1. 两把网关 key（haoxiang gpt-5.6、apihy qwen）——已随 139 份 `_spec.json` 落 zmh `.logs`、也在 `.env`。
   （6.2 的代码修复只堵住"以后不再泄"，**存量 139 份仍是明文**，需批量掩码 + 轮换。）
2. 两个 HF token（env.md 的、download 脚本里的）。
3. pgl 远程机 sudo 密码（`.env` 明文，且随文档 rsync 到远程）。
4. 清远程副本：下次登 pgl 清 env.md / download 脚本的明文 token。
5. `.env` 里其余服务 key（JINA/SERPER/E2B/EXA/OPENROUTER 等）稳妥起见一并轮换。

## 不能在本仓库修（需 benchmark 参考数据，复用 zmh 那份、未复制）

| 编号 | 问题 | 为什么本仓库改不了 |
|---|---|---|
| 5.2 | pcap reference 域名拼错 taktlat→tactlat | 改的是题目 `base/reference`，红线不进本仓库；需在 zmh task-data 里改 |
| 5.3 | healthcare_bias input 预填答案 | 同上，属出题侧 task-data |

## 剩余代码修复（未做，中/低危，可后续在本仓库继续）

| 编号 | 问题 | 优先级 |
|---|---|---|
| 2.1 | 未匹配模型静默兜底（generic_vlm `.*` 注册 + 前 3 轮无工具调用判 failed 护栏） | 中高 |
| 1.2 | stage_input 只校验目录存在、不校验非空 | 中 |
| 3.4 | run.json 归因字段（超时误记 evaluation phase、缺 wall-budget 类目） | 中（score_valid 已挡住最伤的假零分部分） |
| 4.2 | 容器内 python3 指向 3.14 venv（vm_mcp_server run_command 包 `env PATH=…`） | 中 |
| 4.3 | install() key 断言不对症、check_status 返回值被丢 | 中 |
| 6.4 | `pi_qwen35_apihy.yaml` 硬编码 key（删+改 `${env:}`）；key 以环境变量暴露给 agent | 中 |
| 8.2/8.3 | parse_artifacts 丢超时最后一轮 / errorMessage 等解析缺口 | 中低 |
| 9.2 | 容器就绪检测无并发感知、配额只下发不核算 | 中 |
| 7.1/7.3 | 93G 单层镜像重分层 / 容器代理未清 | 高但需改构建/重烤镜像 |
| 10 | 清单文件名不一致（research_batch_p1 vs _wcy，一名两文件） | 中低 |
