# system_issues 修复状态

对照 `system_issues.md` 逐条给状态。分三类:

- **已修并验证**:本机能安全改、不碰同学(zmh)活跃仓库、不碰远程在跑评测的,已改并验证。
- **待你操作**:涉及轮换凭据、改远程 sudo 密码的,只有你能做,我给清单。
- **待与同学协调**:涉及改 zmh 仓库活跃代码或 task-data 的,那是同学的文件夹且有评测在跑,我不单方面改;补丁和方案已备好,协调后应用。

诚实说明:高/中危里能由我在本机闭环的只有密钥文件权限、文档明文凭据、rsync 命令这几条。其余多数落在 zmh 的活跃代码/数据里,或需要你的账号轮换凭据。我没有擅自改动 zmh 的任何代码,也没登录远程机。

## 已修并验证(本机)

| 编号 | 问题 | 修复 | 验证 |
|---|---|---|---|
| 6.1 | `.env` 权限 644 | `chmod 600 .env` | `stat` 确认 644→600 |
| 6.3 | env.md 明文 HF token | 改成"见 secret/.env 的 HF_TOKEN",删除明文值 | grep 确认 docs 下不再有 `hf_` 明文 |
| 1.1 | rsync `--files-from` 丢内容 | env.md 命令改 `rsync -ar`,加 input 非空校验注释 | 本地复现:旧命令拷 0 文件,`-ar` 拷全 |
| 7.2 | 镜像分发方案排序 | env.md 补 zstd+rsync `--partial` 可续传方案 | 文档已更新(方案性,无需运行验证) |

## 待你操作(轮换凭据,我无法代做)

这些是密钥已泄露的补救,必须由你在对应控制台吊销/换新。收紧权限和删明文我已做,但**旧凭据仍然有效,必须轮换**:

1. **两把网关 API key**:haoxiang gpt-5.6 网关 key、apihy qwen key。已随 139 份 `_spec.json` 落盘到 zmh 的 `.logs`(6.2),也在 `.env` 里。到网关控制台吊销换新。
2. **两个 HF token**:env.md 里那个(6.3)、`download_ale_task_data_only.sh` 里那个。到 HuggingFace 设置吊销。
3. **pgl 远程机 sudo 密码**:在 `.env` 里明文(6.1),且文档链路已 rsync 到远程。登录 pgl 换 ubuntu 的 sudo 密码。
4. **清远程副本**:下次登 pgl 时,清理远程上 env.md、download 脚本里的明文 token(6.3 推断远程有副本,我未登远程核实)。
5. **清 zmh 存量泄露**:zmh `.logs` 下 139 份 `_spec.json` 的 api_key 字段(6.2)。这是同学仓库的数据,建议和同学一起批量掩码。

`.env` 里还有一批其他服务 key(JINA/SERPER/E2B/EXA/OPENROUTER 等),既然文件曾是 644 且在多用户机上,稳妥起见一并轮换。

## 待与同学协调(改 zmh 活跃代码/数据)

这些落在 `zmh/ALE_TEST/agents-last-exam` 的代码或 task-data 里,是同学的文件夹且有评测在跑。我准备了补丁和精确方案(见 system_issues.md 对应条目和 `harness/patches/`),但不单方面改,避免打断在跑的评测。按优先级:

| 编号 | 问题 | 现成方案 |
|---|---|---|
| 3.1 | pi json 假零分 | `harness/patches/pi_deployer_false_zero_guard.py`,带 5 条自检,拷进 deployer 即可 |
| 3.2 | 超时不杀进程,eval 与 agent 竞争 | lifecycle wait_for 加裕量 + 外层补 killpg 清理 |
| 3.3 | failed 照评分 + 汇总重复计数 | status=failed 置 score null;汇总按最新时间戳去重、只统计 completed |
| 2.1 | 未匹配模型静默兜底 | 去掉 generic_vlm 的 `.*` 注册改显式 opt-in + 前 3 轮无工具调用即判 failed |
| 4.1 | ensure_node_npm sudo 卡死 180s | 安装前 `sudo -n true` 探测,不可用即 fail-fast;或改用户级 node 安装 |
| 4.2 | 容器 python3 指向 3.14 venv | entrypoint.sh:15 去掉 venv bin 前缀重烤;或 vm 桥包 env PATH |
| 5.2 | pcap 参考答案域名拼错 | 改该题 reference 的 5 处 tactlat→taktlat;管线加 reference 校验 |
| 9.1 | 停机信号无人消费,容器泄漏 | Runner.run 消费 shutdown 事件,cancel gather 走 finally 清理 |
| 8.1 | splitlines 撕碎含 Unicode 行界的事件 | parse_artifacts 改 `split("\n")` |
| 其余中低危 | 1.2 / 3.4 / 4.3 / 5.3 / 6.4 / 7.1 / 7.3 / 8.2 / 9.2 / 9.3 / 10 | 见 system_issues.md 各条修复段 |

补充:我的抽取脚本 `data/extract_pi_training_data.py` 逐行迭代读 transcript(Python universal newlines),不受 8.1 的 splitlines 问题影响;那条只影响 zmh 的 parse_artifacts。

## 文档一致性(10)

wcy 侧文档引用的 `research_batch_p1.txt` 实际是 `research_batch_wcy.txt`,且该名对应两份不同内容的文件(docs/new_run 版 26 题、selected_tasks 版 36 题)。selected_tasks 在 zmh 仓库,重命名待同学;wcy docs 里的分析报告是历史快照,暂不改引用,在此备注。
