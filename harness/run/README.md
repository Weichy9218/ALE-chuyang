# harness/run:运行控制面(唯一入口)

认知和设计看 `../COGNITION.md`。这份只讲怎么跑、API 怎么用、哪些东西被删了。

## 一、怎么跑

只有这一条路,三步:

```bash
# 1. 改这一个文件(选臂、prep/verifier 超参数、任务表、并行度)
vim harness/run/settings.yaml

# 2. 生成各臂预设 + 实验 yaml + 启动命令(在 stack 目录下跑)
python3 harness/run/launch.py --stack . --per-arm            # 只打印命令
python3 harness/run/launch.py --stack . --per-arm --launch   # 生成并直接起

# 3. 看结果(逐题 × 逐臂 + 每臂均分/满分数/全错数 + 对 base 的配对 Δ 和 t)
python3 harness/run/summarize.py .logs/ale/verifier_compare --baseline ale_claw_base
```

`--per-arm` 表示每个臂一个独立进程,`settings.run.concurrency` 是**每臂**并行度,四臂同时推进,共用一个输出根。不加 `--per-arm` 就是所有臂挤一个队列。

只跑没跑完的用 `--resume`(跳过已 `completed` 的 unit):

```bash
.venv/bin/python -m ale_run run exp_verifier_compare_base.yaml --resume
```

## 一点五、settings.yaml 里有什么

所有超参数只在这一个文件里,代码里不再有第二处。

| 块 | 控制什么 |
|------|----------|
| `arms` | 跑哪几个臂,从 `base` / `prep` / `verifier` / `prep_verifier` 里选任意子集 |
| `agent` | `model`、`max_turns`、`thinking_level`。**agent 运行时参数只有这一个地方**。`max_turns: 100000` 等于不设上限,COGNITION 明确禁止 turn / 时间上限,因为不等预算会凭空造出假效应 |
| `prep` | task-specific prep-agent 的多轮上限 `max_steps` 与 `timeout_s`；开关由四臂显式决定（当前代码默认开启，preset 仍逐臂显式写出） |
| `verifier` | Builder 的 `max_steps`、Writer 复核轮上限 `max_review_rounds`（旧名 `max_repairs` 仍兼容）、writer 预提交自检次数 `writer_checks`；Executor 只运行冻结脚本，开关由四臂显式决定 |
| `run` | `name`、`tasks`、`concurrency`(配 `--per-arm` 时是每臂)、`cleanup_mode`、`api_endpoints`、`output_root`、`wall_time_s` |

## 二、API 端点

三个端点都实测提供 `gpt-5.6-sol`,但**key 和 base 必须成对,不能混用**。

| 端点 | key 变量 | base 变量 | 说明 |
|------|----------|-----------|------|
| gpt_sub2api 网关 | `GPT_sub2api_apikey` | `GPT_sub2api_URL` | key 长 67,`sk-` 开头 |
| gpt_sub2api 网关 | `GPT_sub2api_apikey_2` | `GPT_sub2api_URL` | 和上面这个可互换 |
| boyue 网关 `apirx.boyuerichdata.com` | `ale_api_key` | `ale_url` | key 长 **51**,和上面两个**不通用** |

两个坑:

1. **不要假设 `ale_url` 是否已经带 `/v1`**。这个 secret 历史上两种形态都出现过；直接把根域名交给 OpenAI transport 会命中 HTML 页面，重复补 `/v1` 也会得到错误路径。`launch.py` 现在幂等生成 `BOYUE_OPENAI_BASE`，统一使用它。
2. **代理**。那个常年挂掉的 Clash(`127.0.0.1:7897`)**已经从 .env 里删掉了**,实测现在不带任何绕过手段的普通请求就能通(`trust_env=True` 直接 200)。现存的几处绕过(`launch.py` 的 `unset`、`boyueapi_client.py` 的 `trust_env=False`、pi deployer 剥离子进程代理)**不是死代码**:它们挡的是**环境自带**的代理(有些机器的 shell 里就有),留着是保险。别再往 .env 里加代理。

**轮转**:`settings.run.api_endpoints` 是一串 shell 前缀,一个臂用一个:

```yaml
api_endpoints: [OPENAI_API_KEY=$GPT_sub2api_apikey_2 OPENAI_API_BASE=$GPT_SUB2API_OPENAI_BASE OPENAI_BASE_URL=$GPT_SUB2API_OPENAI_BASE, OPENAI_API_KEY=$GPT_sub2api_apikey OPENAI_API_BASE=$GPT_SUB2API_OPENAI_BASE OPENAI_BASE_URL=$GPT_SUB2API_OPENAI_BASE, OPENAI_API_KEY=$ale_api_key OPENAI_API_BASE=$BOYUE_OPENAI_BASE OPENAI_BASE_URL=$BOYUE_OPENAI_BASE]
```

留空则所有臂都用 `secret/.env` 的默认值。正式 arm 对比必须留空或让每个臂使用完全
相同的 endpoint；按臂轮转会把 endpoint 与 intervention 混杂，`launch.py` 会明确警告。
多 endpoint 只适合不估计 arm effect 的吞吐运行。实测 API 不是瓶颈，不需要为正式实验轮转。

## 三、运行 config 的两条硬教训

**1. `cleanup_mode` 必须是 `delete`。** `keep` 会让每个 unit 留一个活沙箱,104 个 unit 跑完就是 104 个容器常驻,把机器吃干,后面的容器开不起来,雪崩。实测:24 路 + `keep` 那次 **102/104 全挂**,失败的 `error` 是 null,日志里是 208 次 `Waiting for Computer API Server to be ready`。产物在删容器之前就已经 pull 到 `.logs`,`delete` 不丢任何东西。

**2. 并行的天花板是"能同时开几个沙箱",不是 API 吞吐。** 每个 unit 要一整个 `ale-ubuntu22` 容器加一个 Computer API Server。实测:

| 配置 | 结果 |
|------|------|
| 8 路(合并队列) | 稳,104 单元约 332 分钟 |
| 12 路(4 臂 × 3)+ delete | 稳,容器恒定 12,内存 21G/125G,API 错误 0 |
| 24 路(4 臂 × 6)+ **keep** | 崩,102/104 失败 |

24 路那次开头 7 分钟是好的,是死容器堆到 104 之后才雪崩的。所以**大概率是 `keep` 的锅而不是 24 路本身**,但 delete 修好后没验证过 24 路。要往上试就先起 canary,看容器数是否稳定、`Waiting for Computer API Server` 是不是只有个位数。

## 四、文件

| 文件 | 是什么 |
|------|--------|
| `settings.yaml` | 唯一控制面,所有开关和超参数都在这 |
| `launch.py` | 唯一入口,读 settings 生成预设 + 实验 yaml + 启动命令 |
| `presets.py` | 帮助库,不是入口,没有 main |
| `summarize.py` | 读输出根,出逐题 × 逐臂表和配对 Δ |
| `invariant.txt` | 常驻反作弊后缀,被附加到每道题的描述末尾 |

## 五、已经删掉的,别再捡回来

- **`build_run_configs.py`**:它的 `main()` 会生成另一套预设(`ale_claw_skills`/`noskills` + `pi_*`),和 `launch.py` **写同名文件**,谁后跑谁悄悄覆盖谁。这是真会误导人的坑。帮助函数已并进 `presets.py`。
- **`patch_ale_claw_skills.py`**:它打的补丁(`skill_sources` + `_seed_skill_playbooks`)已经在 `ale_run/agents/ale_claw/config.py` 和 `deployer.py` 里了,再跑一次没有意义。
- **一次性实验 yaml**:`exp_harness_ablation` / `exp_harness_on` / `exp_harness_off` / `exp_genstrat_on` / `exp_prep_ab_off` / `exp_prep_ab_on` / `exp_domain_prep_smoke` / `exp_harness_compare`(合并版)。都是历史实验的一次性配置,已被 settings + launch 取代。
- **`ale_run/orchestration/domain_prep.py`**:旧的一次 completion general-notes 实现已删除。当前 prep 在 ALE Claw deployer 内复用真实 subagent tool loop。

## 六、不归这里管、故意没动的

- `configs/agents/` 里的 `codex` / `droid` / `gemini_cli` / `claude_code` / `openhands` / `cursor_cli` 等是仓库自带的**其他 harness 预设**,不是我们的冗余。
- `configs/environments/docker_nogcs_keep.yaml` 名字里的 `_keep` 是历史遗留。它只是 docker provider 的配置,和 cleanup 无关,cleanup 由实验级的 `cleanup_mode` 控制。没改名是因为仓库和正在跑的实验都引用它。
- `ale_run/executors/docker.py` 和 `orchestration/termination.py` 里还有 `BRAVE_API_KEY`。那是仓库文件,ale_claw 的 `web_search` 已经换成 Exa 主 + Firecrawl 备,这条对我们是死的,留着只是不去动别人的文件。
