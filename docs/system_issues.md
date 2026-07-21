# ALE-Test 系统问题清单

本文是对整条链路(harness、ale_run 编排、task-data staging、模型路由、bootstrap、评测、密钥、镜像)的一次系统审计结果。由九个切面并行审计、每条发现再经独立对抗验证产出,共 56 条成立(41 条代码级确认、15 条方向成立待修正),2 条被验证反驳后剔除。下面按链路分组,先给高危,再归纳中低危。每条都落到 file:line,给复现、根因、影响、修复。

审计口径:只读静态审计加本地小复现,不碰远程机 pgl 上在跑的评测。凡标"代码级确认"的都在源码里亲眼核对过;涉及远程副本的推断标出。

## 0. 先做的三件事(不修会继续出错或扩大泄露)

1. **轮换 5 把凭据 + 1 个 sudo 密码**(见第 6 节)。`.env` 是 644、含 pgl 的 sudo 密码和 15+ 个 key,爆炸半径最大。两把网关 key 和两个 HF token 已随 `_spec.json`(139 份)和文档明文落盘,其中一个 HF token 和 sudo 密码已随文档 rsync 到远程机。
2. **堵住假零分主链路**(见第 3 节)。当前"基础设施失败"(网关 402、pi json 模式吞错、超时未杀进程)和"真做错拿 0 分"在 run.json 里不可区分,直接污染榜单。这是所有对跑结论和后续 harness 消融实验的地基,不堵,分数不可信。
3. **改 remote 的 rsync 命令**(见第 1 节)。`env.md` 第 8 节的同步命令实际拷 0 字节,是"13 题假失败"的直接原因。

## 1. task-data staging

### 1.1【高危】rsync --files-from 把 task-data 同步成空壳,远程题目在 stage_inputs 假失败

- **复现**:本地 rsync 3.2.7 实测(临时目录 `/tmp/claude-1000/rsync-verify`):建 `task-data/<域>/<题>/base/{input,reference}` 小树,清单每行一个题目目录,跑 `env.md:186` 原样命令 `rsync -a --files-from=list task-data/ dst/`,结果 `find dst -type f` 为 0,目标端只建出题目那一层空目录,`total size is 0`;加 `-r` 后 base/input、base/reference 全部拷到。
- **根因**:`docs/archive/harness-general-prep-2026-07/env.md:186`。rsync 一旦用 `--files-from`,会隐含 `-r`,但同时**取消 `-a` 对 `-r` 的隐含**——即 `-a` 不再意味着递归。清单里每行是目录(如 `business_finance/american_option_pricing_ls`,无末尾斜杠),只被非递归地"创建目录本身",其下内容全不拷。
- **影响**:远程机走 `local_docker_nogcs.yaml` 的 `task_data_source: local:task-data`,`local_host.py:70` 检查 `input/` 目录不存在 → 抛 RuntimeError → `lifecycle.py:257` 的 stage_inputs 阶段冒泡到 `:545` 记 status=failed。凡需 host 拷入 input 的题(cli_nogui_24 全 24 题都需要,input 文件数 3 到 113 不等)整批假失败。与已知的 13 题假失败吻合,也和 env.md 第 2 节"24 题数据已 rsync 约 1.8G"自相矛盾(按第 8 节命令实拷 0 字节)。
- **修复**:命令补显式递归 `rsync -ar --files-from=... task-data/ ...:.../task-data/`(实测加 `-r` 后文件数正确);或改用整机重下脚本 `download_ale_task_data_only.sh`。同步后逐题 `test -d task-data/<域>/<题>/<变体>/input` 且非空校验。

### 1.2【中危】两处取数后端对"目录在但内容缺"不校验,静默拿空数据开跑

- **根因**:`local_host.py` 的 `stage_input` 只校验 `input/` 目录存在、不校验非空;`gsbucket.stage_input` 在 GCS 上 input 前缀不存在时静默 `mkdir` 空目录后 continue。
- **影响**:部分同步、空目录的题不报错就开跑,agent 面对空输入,结果是"真做错"的假象,与 1.1 的假失败一起模糊了"数据问题"和"能力问题"的边界。
- **修复**:两个后端 stage 后都加"input 非空"断言,空则显式报 staging 失败而非放行。

## 2. 模型路由

### 2.1【高危】未注册模型静默掉进为 Qwen-VL 写的兜底循环,不发原生工具调用

- **复现**:gpt-5.6-sol 接 ale_claw,前若干题每题 30 轮只发 0 到 1 次工具调用,空说话然后道歉,全 0 分。
- **根因**:三层叠加。cua 的 `agent/loops/generic_vlm.py:250` 用 `@register_agent(models=r"(?i).*", priority=-100)` 兜底任何模型;它把工具 schema 写进 system 文本、`api_kwargs` 不含 `tools` 键、靠 `<tool_call>` 文本正则解析,非 Qwen 模型永远不会输出这种格式。专用循环的正则都覆盖不到 gpt-5.6:`openai.py:180` 要求末位数字是 4(`gpt-?5\.?4`),vendored unified_loop 原注册 `openrouter/.*` 锚定串首、不匹配配置里的 `openai/gpt-5.6-sol`。`agent.py:383` 的 "No agent config found" fail-fast 因兜底恒匹配成了死代码。
- **影响**:修复前 10 个 run 假零分(gpt56_batch_aleclaw 6、dbg 2、smoke 1、diag 1),其中至少 4 题修复后拿到 0.5 到 1.0。结构上任何新模型名(gpt-5.7、换 gateway 别名)都会无告警复发。
- **修复**:index.html 记录的一行修复(`unified_loop.py:529` 注册正则加 `.*gpt-5\.6.*`)是点补丁,且当前只在未提交的工作区改动里。结构性修复:去掉 generic_vlm 的 `.*` 注册,改成 `(?i).*(qwen|vlm).*` 显式 opt-in;或在找到 priority<0 的 catch-all 且模型名不在显式白名单时 fail-fast。再给主循环加护栏:前 3 轮无任何 function_call 即判 failed,而非跑满预算记 completed。

## 3. 假零分:基础设施失败被记成合法 0 分

这是全审计影响最广的一类,四条同源,合起来是一条完整的污染链。核心是:agent 或框架出故障(网关配额、进程未被杀、退出码骗人),run.json 照样写一个 0.0 分,和"真做错"不可区分,且 `--resume` 把这些假零分当终态永不重跑。

### 3.1【高危】pi --mode json 把 LLM 层错误吞成退出码 0,记 completed + 0 分

- **根因**:pi 源码 `packages/coding-agent/src/modes/print-mode.ts:129-146` 的 `stopReason==="error" → exitCode=1` 检查**只在 `mode==="text"` 分支**;`--mode json`(ale_run 固定用,`deployer.py:291`)下 session.prompt() 正常 resolve,exitCode 恒为 0。`deployer.py:273` 只看 `exit_code==0` 判 completed,parse_artifacts 也不检查最后一条 assistant 的 stopReason。已在 pi 源码逐行确认。
- **影响**:任何整段 API 故障(配额 402、网关 5xx 重试耗尽、finish_reason null)被记成合法 0 分。历史 apihy 402 的 13 题假零分即由此产生(rerun 显示至少 4 题实际能拿约 3.9 分),机制至今未堵;当前 gpt56 的 pi 批次里任何网关故障都会再次以 completed/0.0 落盘。叠加 `cli.py:22` 的 `_RESUME_DONE_STATUSES={completed,timeout}`,这些假零分在 resume 下永不重跑。
- **修复**:deployer 侧不改 pi 也能堵:`launch()` 在 proc 退出后倒序扫 transcript.jsonl 找最后一条 assistant 的 message_end,若 stopReason 属于 {error, aborted} 就改判 status=failed 并把 errorMessage 写进 AgentRunResult.error,这样 lifecycle 会记 failed、resume 会重跑。上游更根本的修法是把 print-mode.ts:129 的检查移出 text 分支,json 模式同样 exitCode=1。这条已在附录给出可直接用的 deployer 补丁片段。

### 3.2【高危】墙钟超时时进程不被杀,evaluate 与仍在跑的 agent 竞争工作区

- **根因**:`lifecycle.py:327-334` 外层 `asyncio.wait_for(timeout_s)` 与传给 executor 的内层 timeout **同值**,没给 setup 和优雅 kill 留裕量,外层必然先触发;触发后 `:335-340` 只合成 `status=timeout`,不杀任何进程/容器。次生:即便 executor 的 kill 触发,也只 kill 单个 entry pid,而 entry 是 setsid 会话组长,pi 子进程成孤儿继续跑;`deployer.py:255-267` 的 terminate/kill 也只针对 pi 单 pid 而非进程组(尽管 start_new_session=True 本可用 killpg)。所以 `sandbox.py` 的 kill 与 `docker.py` 的 `docker rm -f` 全成死代码。
- **影响**:所有超时 run(现网 25 个,gpt56_full_pi 占 5 个)在评分时 agent 仍在改文件,分数在竞态下测得、不可复现;pi 继续烧 token 直到容器销毁;executor 精心写的超时诊断永远拿不到。
- **修复**:`lifecycle.py:327` 的 wait_for 超时加宽为 `timeout_s + 裕量`(如 +600s),让 executor 内层的正规 terminate 路径先触发;并在外层 TimeoutError 分支补硬清理:SandboxExecutor 暴露 `kill -TERM -- -<pid>` 组信号,DockerExecutor 记录容器名并 `docker rm -f`,evaluate 前确保 agent 已死。

### 3.3【高危】failed/timeout 后 evaluate 照跑、分数照写,汇总不过滤 status 且重复计数

- **根因**:`lifecycle.py:428-447` 对任何 status 都无条件跑 evaluate();`:505-525` 状态提升时不清 score;`_build_run_meta`(`:1010-1038`)无条件写 score。下游 `summarize_qwen35_docker_support_full.py:15-29` 不过滤 status、不按 (task,variant) 取最新时间戳去重。
- **影响**:分数汇总两个方向都失真——把 failed 带 0.0 计入拉低均值,或(若只看 completed)把基础设施失败静默剔除虚增均值。多时间戳重复计数使重跑过的批次统计直接错。历史日志里已有 82 例 failed/timeout 带分数的 run。
- **修复**:三处。status=failed 时把 run.json 的 score 置 null 或加 `score_valid=false` 字段(timeout 可保留部分分但必须带 termination.category);汇总脚本只统计 completed 且按 (agent,model,task,variant) 取最新时间戳;resume 语义改为仅当 timeout 且轨迹里有实际 agent 步数才视为终态,否则重跑。注意方案的一个坑(验证员指出):`trajectory.finalize(reward=score)` 在 `lifecycle.py:490` 发生于状态提升之前,只改 505-525 不彻底,得同步处理 trajectory 的 reward 或把状态判定提前。

### 3.4【中危】run.json 故障归因字段系统性失真

- **根因**:agent 墙钟超时被记成 `phase=evaluation`,termination.category 因异常类型被抹掉、且模式表缺 `wall-budget` 项恒为 None。
- **影响**:即便人工查日志,也无法从 run.json 快速区分"超时"和"评测阶段崩",给归因加噪。
- **修复**:补全 termination 模式表,超时单独归 `wall-budget` 类,phase 记 agent 而非 evaluation。

## 4. ale_claw bootstrap 与宿主依赖

### 4.1【高危】ensure_node_npm 在无 Node 宿主上走 sudo 装 Node,sudo 要密码时挂 180 秒后崩溃

- **根因**:`ale_run/agents/_bootstrap.py:147-152` 执行 `curl ... | sudo -E bash - && sudo apt-get install -y nodejs`,跑在 `subprocess.run(..., timeout=180)` 里。sudo 向 /dev/tty 要密码,而 stdout/stderr 被捕获、操作者看不到提示,进程一直等输入;180 秒(形参默认加调用处显式各一个)后抛 TimeoutExpired,root 身份的 sudo 孙进程还杀不掉。
- **影响**:该题记 failed、0 分,且不缓存:每个 unit 重走一遍,24 题 CLI 集合共烧 72 分钟全失败。ensure_npm 是同一函数的包装,claude_code/codex/gemini_cli/pi/openclaw 的 deployer 在无 node 环境同样中招。
- **修复**:安装命令前先 `sudo -n true`(超时 5 秒)探测非交互 sudo,不可用立即 raise 并说明宿主缺 node、sudo 不可非交互。更彻底:去掉 sudo 依赖,从 nodejs.org 下官方 linux-x64 tar.xz 解压到 `~/.local` 并把 bin 前置 PATH,零 root。

### 4.2【高危】容器内 python3 指向 cua-server 的 3.14 venv,根因在镜像 entrypoint.sh 的 PATH 前置

- **根因**:镜像 `entrypoint.sh:15` 把 `/opt/cua-server/.venv/bin` 前置到 PID 1 的 PATH。agent 的命令经 vm_mcp_server 桥发给 cua-server,cua-server 起的 shell 继承 PID 1 环境,于是 `python3` 解析到 3.14 venv(无 pip、无 numpy/scipy),而 `/usr/bin/python3` 是 3.10 且科学包齐全。该 PATH 还漏了 `/usr/sbin`。
- **影响**:镜像上所有 Python 计算类任务、所有经 cua-server 执行命令的 agent 都成立;好的情况浪费约 8 步试错(见 analysis.md 的 Ising 轨迹),差的直接超时或放弃。
- **修复**:镜像层根治——`entrypoint.sh:15` 去掉 venv bin 前缀(第 119 行本就用绝对路径 exec venv python,cua-server 自身不受影响),补上 `/usr/sbin`,重烤镜像。不重烤的缓解:vm_mcp_server 的 run_command 把命令包成 `env PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin bash -c '...'`(桥随 ale_run 部署,改了即生效)。**注意**:这条环境事实是干净的、可注入的——它是"环境事实前置",不是答案,正好是 harness 干预(见 harness_design.md 2.3)的合规注入内容。

### 4.3【中危】install() 的 API key 断言对 gpt-5.6 网关不对症;VM 可达性检查形同虚设

- **根因**:`AleClawDeployer.install()` 的 key 断言三选一即通过,不校验模型实际要的 OPENAI_API_KEY 和 base URL;`launch()` 第 1 步丢弃 `check_status()` 返回值。
- **修复**:断言按实际路由的模型校验对应 key;check_status 返回值要判、不可达即 fail。

## 5. 评测与参考答案隔离

### 5.1【正面结论】时序隔离在代码层面成立

审计确认项目声称的干净基线属实:参考答案只在 agent 输出 DONE 之后、evaluate 之前才 staged 进容器;容器无宿主机 bind-mount;评测脚本 just-in-time 写入;pi/ale_claw 的文件工具都被限定在容器内。数据侧的独立复核也印证了这点——抽取脚本对 146 次 attempt 做行为级泄露审计(核查工具调用参数有没有触碰 `base/reference`),真实命中为零(见 data_construction.md 4.3)。agent 运行期确实没读过答案。

### 5.2【高危】参考答案本身无任何自动校验,已发现一处拼写错误使正确答案被判错

- **复现**:pcap_enterprise_triage 题的 reference 把恶意域名 taktlat.xyz 写成 tactlat.xyz(差一个字母),而 scorer 用精确相等,正确解题的 agent 封顶 0.55、passed 恒 False。
- **根因**:数据管线(`loader.py`、`local_host.py`)只搬运不校验,没有一步把 reference 里的 IOC/域名/数值与 input 交叉核对;各题 scorer 又用精确匹配,任何录入错字都把正确答案判错。
- **影响**:至少 pcap 一题确认,评分与真实能力反相关。因无系统性校验,同类错误在 56GB task-data 中数量未知,直接污染榜单可信度。
- **修复**:立即改该题 reference 的 5 处域名。管线加 reference 自动校验:对有 input 侧可核对物(pcap/csv/pdf)的题做 IOC/域名/数值一致性检查;引入 checksum/manifest 和回归测试(把 reference 自身当输出跑 scorer 应得满分——pcap 这条会立刻暴露 reference 对 pcap 不自洽)。

### 5.3【低危】个别题 input 里预填了 scorer 校验的答案

- **根因**:healthcare_bias_audit 题 input 里的 `audit_answers.json` 模板已预填 scorer 精确校验的两个分类答案。
- **影响**:这类题存在从 input 直接抄答案的捷径,不测真实能力。属出题问题,不是 harness 泄露。
- **修复**:出题侧把答案字段从 input 模板清空。

## 6. 密钥卫生(整体不及格)

框架自身的 `_secrets.json` 防线是好的,run.json/trajectory/transcript 实测无泄露。但有几条旁路把凭据落盘。**这一节的修复是全清单最紧急的,应先做。**

### 6.1【高危】.env 权限 644,含远程机 sudo 密码 + 15 个 key

- **根因**:`/home/dataset-local/wcy/ALE-Test/.env` 模式 644,由 `llm/env_utils.py:8` 消费,把远程 sudo 密码和普通 API 配置混放。
- **影响**:本机是多用户机,任何本地账户读一个文件就同时拿到 pgl 的 root(sudo 密码 + SSH 免密可达)+ 全部网关/搜索/沙箱计费 key + HF token。单点爆炸半径最大。
- **修复**:立即 `chmod 600`;在 pgl 换 ubuntu 的 sudo 密码;轮换文件内全部 key;sudo 密码从项目 .env 拆到单独 600 文件或凭据管理器。

### 6.2【高危】pi 的 api_key 明文进 _spec.json,139 份落盘宿主 .logs

- **根因**:`sandbox.py:739` 的 `_config_to_kwargs` 序列化 config 全部标量字段(含 `PiConfig.api_key`,由 yaml 的 `${env:OPENAI_API_KEY}` 在宿主解析成明文),写进 `_spec.json`;gather 排除表 `_secrets.py:27` 只排 `_secrets.json`/`_env`,不排 `_spec.json`,于是被回收到 `.logs`。直接违反注释声明的"_spec.json 必须 keyless"。`docker.py` 有同构路径。config.py:42 的设计注释还明说 key 随 config 走"以免改 env 白名单"——与 _secrets 约定矛盾。
- **影响**:泄露 2 把网关 key(haoxiang gpt-5.6 的 32 份 + apihy qwen 的 107 份)。远程机若跑 pi 配置同样泄露。
- **修复**:`_config_to_kwargs` 对字段名含 key/token/secret/password 的做掩码(复用 `termination.py` 的 redact_config);api_key 改走 `_secrets.json` 通道(`pi/deployer.py:104` 本就支持 api_key_env 回退,把 OPENAI_API_KEY 加进 `lifecycle.py:746` 的白名单即可)。批量清洗存量 139 份 _spec.json。轮换两把 key。

### 6.3【高危】两个 HF token 明文进文档,一个已随文档 rsync 到远程

- **根因**:`docs/archive/harness-general-prep-2026-07/env.md:48` 曾把 HF token 完整值写进交接文档(644);`download_ale_task_data_only.sh` 硬编码第二枚独立 HF token,且同类脚本已复制到远程机。
- **影响**:token 至少存在于本机文档、本机 .env、远程副本三处。远程副本存在系文档自述推断(未碰远程机核实)。
- **修复**:吊销两枚 token;文档里改写成"见 secret/.env";新 token 只落 600 文件;下次登远程时清理远程副本。

### 6.4【中低危】仓库里硬编码 key、key 以环境变量暴露给被测 agent

- `configs/agents/pi_qwen35_apihy.yaml` 硬编码 apihy key(644,即 .logs 泄露的同一把)。修:删掉、改 `${env:...}`、轮换。
- 网关 key 以环境变量形态暴露给容器内被测 agent 及其 bash 子进程,恶意任务/模型可外传。修:key 只给 harness 进程,不进 agent 可见的容器环境(需 executor 层区分 harness env 和 agent env)。

## 7. Docker 环境与镜像分发

### 7.1【高危】93G 镜像是单个 92GB layer,这才是镜像源拉不动的根因

- **根因**:`ale_run/environments/images/ale_ubuntu22_docker.py` 把镜像做成 VM rootfs 一次性导出 = 单 squash 层。单层导致:docker pull 的多层并行下载完全失效,全程串行拉一个 92GB blob;中途 RST/stall 只能整块重试,国内 pull-through 镜像多不支持 Range 续传,一断就从 0;`docker.1ms.run`/`docker.m.daocloud.io` 是 Hub 透明缓存,对 agentslastexam 冷门 namespace 无缓存、回源又对单 blob 设限,于是表现为 403/not-found/stall。
- **影响**:所有走 docker provider 的 99 道题在国内首次 provision 时自动 pull 会失败或挂死,整批无法起跑。
- **修复**:构建侧重分层(基础系统 + apt + 科学栈 + 运行时多层),让 pull 可并行、可按层续传、可被镜像源分别缓存。短期不改构建则走 7.2 的 tar 或 HF qcow2 通道。

### 7.2【高危】"隧道 26h、别传 tar"的结论论证不足,应改分发方案排序

- **根因**:`env.md:98-100` 只用"raw 体积÷单流吞吐"估时,忽略了 tar 可 zstd 压约 2.5x、rsync `--partial` 可断点续传、多流可绕单流上限。相比之下 docker pull 的单 92GB blob 不可续传,在丢包隧道上更可能永远拉不完——结论反而应是"传 tar 优于走 registry"。
- **影响**:误导运维放弃唯一可行且已具备的通道(batchcom 已有 `ale-ubuntu22-docker.tar` 和已 load 的镜像),反复尝试注定失败的镜像源 pull。
- **修复**:优先级——① 有更快内网直连则 zstd 压 tar(约 40G)后 `rsync --partial` 传再 `docker load`;② 只有隧道也同样 zstd+rsync,约 40G@1MB/s≈11h 且可续传,优于 26h 也优于不可续传的 pull;③ 走 QEMU 用 HF 多分片 qcow2(hf-mirror 可达、分片可续传);④ 私有 registry(但镜像仍单 blob,只在两端带宽稳时才优于 rsync)。命令:`zstd -T0 -3 x.tar` 后 `rsync -P --append-verify`,落地 `zstd -d | docker load`。

### 7.3【中危】容器内代理未清、镜像层缺陷无统一补丁挂点

- Docker provider 不在容器层消除镜像里烤死的代理,容器内任何联网命令继承指向不存在端口的 proxy;只有 pi agent 自己的子进程会清(config.py 的 clear_proxy)。修:provider 起容器时统一清代理 env。
- 镜像默认 python3 指 3.14、diffusers 缺 DiTTransformer2DModel 等缺陷,没有"每题跑 agent 前在容器内统一打补丁"的框架挂点。修:给 BaseTaskSetup 加一个每题前置的容器内 setup hook,把这类环境补丁集中处理。

## 8. pi deployer 轨迹解析

除第 3.1 的假零分外,还有几处会静默损坏轨迹(影响训练数据质量):

### 8.1【中危】splitlines 切 NDJSON 会撕碎含 Unicode 行界的事件

- **根因**:`parse_artifacts` 用 `str.splitlines()` 切 transcript,消息内含 U+2028/U+2029/NEL(0x85) 等 Unicode 行界时整条 JSON 被从中间切开、解析失败丢弃。
- **影响**:轨迹静默缺事件,agent 输出里只要出现这些字符(自然语言、某些数据里常见)就丢步。做训练数据时这是静默的数据损坏。
- **修复**:改用 `split("\n")` 只按真正的换行切,或按字节读。

### 8.2【中危】只消费 message_end,超时/被杀 run 丢掉最后一轮

- **根因**:parse_artifacts 只消费 message_end 重建轨迹,超时/被杀 run 的进行中最后一轮(message_update 部分内容和进行中工具输出)完全丢失;compaction 事件及其 LLM 调用的 usage 也不可见。
- **影响**:恰恰是失控长任务(最该分析的)的收尾轨迹缺失;usage 统计漏掉 compaction 的开销。
- **修复**:超时 run 额外消费最后一段 message_update 重建部分轨迹;把 compaction 事件的 usage 计入。

### 8.3【中低危】其他解析缺口

- stopReason=error 的 errorMessage 不解析,错误步 message=None,原因只能翻原始 transcript(与 3.1 同源)。
- 每条 pi 轨迹开头 instruction 用户步重复两次(lifecycle 预置一步 + parse_artifacts 又消费 pi 回显的同文本)。
- usage 的 cacheWrite token 被双重丢弃(pi 的 input 已减去 cacheWrite,Python 又不写 cache_creation_tokens)。

## 9. 编排层其他

### 9.1【高危】停机信号无人消费,批次无法优雅中止

- **根因**:`lifecycle.py:97-123` 把 SIGINT/SIGTERM 接到 `event.set()`,但 `runner.py:104` 的 gather 从不监听该事件,注释宣称的消费逻辑没写。
- **影响**:跑一半想停,Ctrl-C/kill 无效,只能 kill -9;而 kill -9 跳过 `env.close_async` 的 finally,每个在跑 unit 的 ale-* 容器(4-16 vCPU / 15-60GB)全部泄漏,侵蚀下一批容量,诱发下一批 env_start 就绪超时(与 gpt56_full_aleclaw 5 题 env_start 崩溃同型)。
- **修复**:在 Runner.run 里 `asyncio.wait({gather_task, shutdown_event.wait()}, return_when=FIRST_COMPLETED)`,事件触发时 cancel gather,让每个 unit 走 CancelledError→finally 清理容器;或删掉自定义 handler 走既有 KeyboardInterrupt 分支。

### 9.2【中危】容器就绪检测无并发感知,资源配额只下发不核算

- 就绪检测:concurrency=N 时 N 个重容器同时 docker run 形成 thundering herd,固定 360s×3 的就绪预算在高并发下不够,失败 unit 还占着并发槽最长约 33 分钟。这正是"并发 6 崩 5 题、降到 4 才清零"的根因。
- 资源配额:并发信号量是纯计数,不感知每题声明的 vcpus/memory,16 vCPU 任务和 4 vCPU 任务占同一个槽,宿主容量不够时既不排队也不报错,退化成就绪超时或 OOM。
- 修:就绪预算按并发数放大或做启动限流;信号量改为按声明资源加权的准入控制。

### 9.3【中危】评测实际天花板 3300s 而非声称的 7200s

- **根因**:detached `run_command` 的 `_DETACHED_TIMEOUT_S` 仍按旧值口径设为 3300,而 `_EVAL_TIMEOUT_S=7200`,注释也已过期。
- **影响**:重型评测(>3300s)会被 detached 层提前砍断,与配置声称的 7200s 不符。
- **修复**:两个超时对齐,detached 层放宽到 eval 超时以上。

## 10. 文档与代码一致性

大部分核心技术声明经核对准确:pi 三钩子行号(types.ts:213/267/281、agent-loop.ts:248/621/722)、index.html 的 unified_loop.py:529、pi 0.404/gpt_claw 0.399 均分(用附带脚本复算得 0.4035/0.3989)、cli_nogui_24(24)/gpt56_full(25) 计数、并发 4/wall_time 2400 全部通过。不一致集中在清单文件名:

- 【中危】文档四处引用的 `selected_tasks/research_batch_p1.txt` 在仓库不存在,实际清单现存于 `docs/harness/results/latest/tasks.txt`。
- 【中危】`research_batch_wcy.txt` 曾对应两份内容不同的文件；当前 26 题事实源已迁移为 `docs/harness/results/latest/tasks.txt`，历史副本留在 archive。
- 【低危】`hf://` task_data_source 是未实现桩,配置里启用会每题 staging 直接崩;`config_loader` 文档说环境 yaml 在 `configs/environments/`,但主推的 `local_docker_nogcs.yaml` 在仓库根。
- 修:统一清单文件名,给两份 wcy 批次改不同名;文档引用改到实际路径;hf:// 桩要么实现要么在选择时报明确错误。

## 附:被验证反驳的 2 条(不列为问题)

- "ale_claw 只关了 web_search、web_fetch 仍开着导致网络出口未封"——反驳成立:该框架的既定策略是"评测允许联网"(多处代码明写 web 工具 intentionally ENABLED),web_fetch 还带 SSRF guard,不算漏洞。
- "gpt-5.6 在两套 harness 里 context window 是 200k vs 128k 的分裂"——反驳成立:`secret/.env:9` 已设 `CONTEXT_WINDOW_OVERRIDE=128000`,两套已对齐 128k,不存在分裂。

## 附:验证方法与产物

- 审计由九切面并行、逐条对抗验证产出,原始记录在工作流 journal;高危条目均代码级确认。
- 假零分链(3.1)的 deployer 补丁、rsync 修复(1.1)、python3 PATH 缓解(4.2)都是不改远程、不动在跑评测就能落地的改动,建议先在本机验证再同步。
- 涉及远程副本的两条(6.3 的远程 HF token、6.1 的 sudo 密码)标了推断来源,按铁律未登远程核实,处置时一并清理远程副本。
