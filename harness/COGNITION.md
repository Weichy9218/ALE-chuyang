# harness 认知与设计(单一事实源)

这个目录是 harness 优化的唯一权威源:当前认知、要注入的内容(skills)、运行方式。历史上被证伪的做法不在这里保留。

## 1. 当前认知(经数据核对后成立的)

- **迄今没有任何"提示类"干预被证实有净收益。** 早期镜像式 harness(复述模型已知/已做的事)消融为零、且有 reward-hack 风险。后来的通用方法后缀(无差别让模型拆契约、写自检、收敛)看似 +0.04,核查后是假信号:ON 用了 7200 秒预算、OFF 只有 2400 秒,正收益全来自 OFF 超时没跑完的题;而让 pi 转正的那道 ct_geometry +1.0 是作弊(把 input/ 里的参考图混 30% 进输出卡过阈值)。去掉这些,两个 agent 的真实效果都落在噪声里(pi 净 −0.019,置换检验 p≈0.28)。
- **噪声底很高。** 同配置两次独立跑,逐题分数标准差 pi≈0.09、ale_claw≈0.20,单题最大抖动 0.33,还有 0↔1 的整题翻转。任何单题效应小于这个,不能进结论。单次跑 26 题几乎测不出 <0.05 的效应。
- **唯一被证实的 harness 收益是资源控制**(轮次上限从 30 提到 100 救回空输出)。方法类提示到目前为止都没跨过噪声。
- **不少失分来自 harness 碰不到的地方**:模型能力缺口、以及评测器本身的问题(legal_ma 评测器有 bug、tcga 分数被常数上限 0.84 卡住、bpmn 有 40% 权重读 agent 自报的 JSON)。这些不该记到 harness 头上。
- **skill 的拉取次数不是价值的代理,是 churn 的症状。** 104 单消融里 pi 在一道题读同一个 SKILL.md 达 15/54 次、ale_claw 一局 memory_get 达 579 次(拉 method-deliverable-contract 153、evidence-audit 76)。这些是同一文件的重复拉取:方法读一次就该内化,重复拉说明内容没留在上下文里(长轨迹+压缩把早先读到的丢了)或被当成每步前的仪式,ale_claw 还叠加了 memory 反射式检索。证伪:tcga 上 ale_claw 带 skill 拉 153 次拿 1.00,而 pi 不带任何 skill 已经 1.00,拉取是活动量不是杠杆。修法不是调频率,是换掉提供杠杆的东西(见 §3.1),并让方法拉一次即内化(首拉写入常驻 TASK_MEMORY,或 harness 层对同一 key 的重复 memory_get 返缓存)。
- **pe_screening_memo_1 四臂全 failed/score None,是评测侧(judge 调用)失败的特征,不是 agent 能力问题。** 四个臂完全一致地挂,排除 agent 差异。这类不计入 harness 效果。
- **本轮实测(pgl):Exa 搜索改造 + B 预处理 + 新 skill 全部端到端跑通;B 作为"喂通用 notes"这一形态,单独看没有跨噪声的提分。** prep-off vs prep-on 干净对照(同 skills、5 道有余量的题、唯一变量 prep):均值 +0.030,配对 t≈0.8,在噪声里。两个看似的涨(crf_sdtm +0.17、flusight +0.09)都能用 OFF 臂抽到低于常态解释,ON 从没把哪题抬过已知天花板。好 notes 不等于分数动。
- **四臂全量对照(base/skills/prep/skills_prep × 26,首次拿到零干预 base 基线):三个干预都测不出效应,且每个 Δ 的符号由单独一道题决定。** base 均分 **0.6279**(25 题可计分)。全 25 题:prep −0.032(t=−0.71)、skills −0.021(t=−0.46)、skills_prep −0.029(t=−0.65);**去掉 ct_geometry 一题,三个符号全部翻正**:prep +0.009(t=+0.43)、skills +0.020(t=+1.01)、skills_prep +0.012(t=+0.67)。两种算法 |t| 都 <1.01。ct_geometry 四臂重建质量只差 0.4%(相关 0.9997 vs 0.9957),被阈值放大成 1.0 对 0.0,这一格值 0.04 均分,约等于全部 Δ。**结论是"这个基准单次跑测不出 0.02 量级效应",不是"干预有害"。** 报告:`docs/new_run/harness-study/harness_compare_report.html`。
- **为什么测不出:25 题里 13 题对四臂完全同分**(6 题天花板全 1.0、4 题地板全 0、3 题卡死:llm 0.5 / marc 0.2 / moodle 0.885)。真正会动的只有 **12 题**,而配对差 sd=**0.22**。有效样本 12、噪声比目标效应大一个数量级,单次全量跑在设计上就没有功效。要么 k≥3 且只跑那 12 道会动的题,要么承认这个量级测不了。
- **ct_geometry 作弊审计:这次没有作弊,不变量守住了。** 该题 `input/` 里就放着 agent 可见的 `reference_image.npy`,md5 **e965b015**(正是历史作弊抄的那份)。base 拿了 1.0,但其产出 md5 不同、对可见参照的仿射拟合 R²=0.9994 而非 1.0、评测器的 `np.array_equal` 反作弊未触发 → **不是字节拷贝,是真做出来的**。高相关本身不是作弊证据(这题正确答案本来就该和参照高度相关),要用 md5 + 仿射 R² 一起判。
- **两条值得追的线索(两个独立臂方向幅度一致,开关正好解释分组):** ① `tcga`:skills 关的两臂都 0.840、开的两臂都 1.000,**skills 一致 +0.16**,是全轮唯一完全干净的开关分组。② `variant_annotation`:prep 关的两臂都 0.999、开的两臂 0.794/0.793,**prep 一致 −0.205,是回归**,也是本轮最像真实效应的一格。先查 prep 的 notes 把 agent 带偏在哪,这个不需要重跑全量。
- **两道零分题(bpmn、legal_ma)是"差一条被 all-or-nothing 归零",不是读不懂。** bpmn 43 项结构检查过 41,只漏 a23/a24(merchant/campaign coordination task),而 campaign 白纸黑字写在 input 的 enforcement hint 里,agent 连自查报告都没列它;legal_ma 4 条矛盾找对 3 条(还自己做了 股数×单价 套算)、0 假阳性,只漏第 4 条。都是完整性/覆盖的最后一公里,不是理解也主要不是原始能力。杠杆:把自校验从"文字方法"变成"抽取 input 自带的验收清单 + 真跑校验脚本、不过不放行",既治这种死法又通用非泄露(清单来自公开 input)。已据此重写 deliverable-contract。

## 2. 两个 agent 的渐进式披露机制(核过源码)

- **pi:原生 skills,读取触发。** `--skill <目录>` 加载 SKILL.md。只有 frontmatter 的 name+description 进 system prompt(每条约 20 token,常驻可见)。模型判断某个 skill 与当前任务相关时,用 `read` 工具读那个 SKILL.md 才把正文载入(read.ts 把读 SKILL.md 归类为 kind:"skill")。不触发就零正文成本。这是真正的"模型主动触发"。
- **ale_claw:没有原生 skills,用 memory。** MemoryStore(TASK_MEMORY.md 开局注入 + 会话日志),配 memory_search/memory_get 工具按需检索。这是 agent 自己维护的读写便签,不是预写的方法库,形态和 pi 的 skills 不同。
- **循环钩子对 pi 的 CLI 部署不可达**(shouldStopAfterTurn 在 coding-agent 里无消费者;beforeToolCall/afterToolCall 走事件总线且丢了 terminate 字段)。所以别设计依赖钩子的干预。pi-agent.md 说"主战场是钩子"这句对 CLI 部署是错的。

## 3. 设计:一套 skill 机制,两个 agent 大体一致

共同底座:两个 agent 都有 `read` 工具 + 一个 system prompt 注入点。所以统一机制是:

- **skills 是一批纯 .md 文件**(见本目录 `skills/`),开局 staging 进沙箱。
- **每个 agent 的 system prompt 里只放一份短索引**:每条 skill 一行 `name — 何时使用 — 路径`。pi 用原生 `--skill` 自动注入这份索引;ale_claw 在 prompt.py 里加一段等价的 skill 索引段。同一批 skill 文件,同样的"读文件才展开正文"行为。
- **模型自己判断相关性并 `read` 对应文件**才载入正文。不匹配就零成本。这满足"模型主动触发、不是所有题被动接受同一套提示"。
- 载荷只能是**通用方法或能力**,不能是提醒(镜像已证无效),不能是任务专属规则/ID/阈值(那是过拟合,穿了 skill 马甲的手写提示,bpmn linter 就是反面教材),不能是评测逻辑或参考答案。
- 当前两个通用 skill,门控在**互不相交的任务群**上,路由是一个清晰的二分:能不能从输入造一个可运行的检查?能就用第一个,只有判断没有可运行检查就用第二个。这样能各自独立验证、互不污染:
  - `deliverable-contract`(强制可运行自校验):构造/计算类任务(要产出具名文件/schema/可运行工件/数值结果)。核心动作:抽取任务自己写下的验收清单(input 常直接给,如 bpmn 的 enforcement hint 和 rubric 表),把每条变成可跑的断言(有 shipped harness 就跑它,否则写 verify.py),跑到全绿才算完;没写检查或有检查没过都算没做完。直接针对"差一条被归零"的死法。
  - `evidence-audit`(系统覆盖 + 证据锚定):判断/审计类任务(读材料、配证据、下判断,没有可运行的东西去做)。核心动作:动笔前先枚举所有比对单元(每对来源 × 每类字段)、逐格走一遍保证不漏,每条发现锚定原文引用并复算算术,零无据发现。针对 legal_ma 那种"漏一条"的覆盖死法。两个 skill 分工是清晰二分:能不能跑一个检查?能就用前者,只有判断用后者。
  - 一次计算类任务不配 skill,沉默就是为它们设计的干预。skill 库按证据增长,不预设分类学,不为凑机制而加。
- **一条常驻不变量(不是 skill,写进每个 agent 的 system prompt,至多两三句):** 精确满足题面写下的要求;不要猜测评测器;输出要靠计算/推理产生,不要把题目给的 reference/期望值直接拷进或混进交付物。最后这半句是对 ct_geometry 那类作弊的通用防线——它必须常驻,因为 pi 的钩子在 CLI 下不可达、挡不住。

## 3.1 杠杆:信息与反馈,不是重复读方法(本轮方向,先只做 ale_claw)

skill 给方法,真正的杠杆是让模型拿到更多信息和反馈。三件事,全部非泄露(只用公开 input + 通用领域知识 + 自建反馈):

- **A. 自评/自模拟回路(最大杠杆,已落地进 deliverable-contract)。** 很多题能用公开材料给自己造 oracle:american_option 用闭式/树交叉验证 LS 蒙特卡洛;sse 在 input 上重放规则核对分类;financial_stmt 靠内部一致性配平。ale_claw 有真 shell,能真跑。把"我照方法做了"变成"我有通过的检查"。
- **B. 预备 subagent = harness 预处理步(已建 + pgl 端到端验证,缺省关)。** `ale_run/orchestration/domain_prep.py`,lifecycle 第 1b 阶段调用 `maybe_prepare_domain_notes`。缺省 no-op;开关既可全局 env `ALE_DOMAIN_PREP=1`,也可每 agent 配置 `domain_prep: true`(让一次跑同时装 prep-on/off 臂)。按 `<domain>/<family-stem>` 缓存,读 input 摘要(+可选 Exa 搜索 `ALE_DOMAIN_PREP_SEARCH=1`),用 `call_helper_model` 走 agent 同一 litellm 路径产**通用可复用非答案** notes,写 `PREP_NOTES.md` 进任务目录 + description 加指针。结构性非泄露(reference 到 Phase 3 才进沙箱)。best-effort。**pgl 实测**:notes 生成/写入/被 agent 读/缓存/非泄露全过,质量高、无答案夹带;超参数(max_tokens/notes_chars/digest_chars)全走 env 可调,缺省 3000/12000/4000。**但单独看没有跨噪声提分(见 §1 的 A/B),下一步价值要看它和强制自校验 skill 的配合。**
- **C. 搜索工具喂给 B(泄露防护已改完)。** ale_claw 的 `web_fetch` 本来默认就开、且无任何域名黑名单,SSRF 只挡私网 IP,等于 agent 已能 fetch 到 agents-last-exam.org。已在 `tools_web.py` 加 host 黑名单:agents-last-exam.org 及子域永远挡(env `ALE_BLOCKED_HOST_SUFFIXES` 可加),web_search 在结果里就过滤、web_fetch 抓取前和每次重定向后都挡。跑里真开 web_search 还需 secret 放 BRAVE_API_KEY + 从 disabled_tools 去掉 web_search;搜索是独立能力轴,单独消融(search-on/off),不混进 skills 轴。

## 4. 红线

- 干预只能从题目公开材料 + 通用领域知识推导。不读 reference/、不读评测脚本。
- 不按每道题的失分去调 harness(那是在测试集上做梯度下降)。skill 正文写作时只允许参考一半任务的材料,全量评测。
- 交付物一致性、事实反射这类只能核验、不能替模型生成动作。

## 5. 运行与验证约定

- **控制面和 API 的细节看 `harness/run/README.md`(唯一权威)。** 一句话:改 `settings.yaml` 一个文件,跑 `launch.py --stack . --per-arm`,用 `summarize.py` 看结果。prep 开关是每 agent 的 `domain_prep` 标志,四臂共用一个输出根便于对照。已删掉 `build_run_configs.py`(它的 main 会生成同名的另一套预设,谁后跑谁覆盖谁)和一堆一次性 exp yaml。
- **两条运行硬教训(都是实测踩出来的):**
  - `cleanup_mode` 必须 `delete`。`keep` 让每个 unit 留一个活沙箱,104 单元就是 104 个容器常驻,机器被吃干后续开不起来,雪崩。实测 24 路 + keep **102/104 全挂**(`error` 是 null,日志 208 次 `Waiting for Computer API Server to be ready`)。产物在删容器前已 pull 到 .logs,delete 不丢东西。
  - **并行天花板是"能同时开几个沙箱",不是 API 吞吐。** 每个 unit 要一整个容器 + Computer API Server。8 路稳(104 单元约 332 分钟);12 路(4 臂 × 3)+ delete 稳(容器恒 12,内存 21G/125G,API 错误 0);24 路 + keep 崩过。三个 API 端点(gpt_sub2api 两个 key + boyue 的 `ale_api_key`+`ale_url/v1`)都实测服务 gpt-5.6-sol,可按臂轮转,但**API 从来不是瓶颈**,轮转是余量不是提速手段。
- 不给 pi 和 ale_claw 设 max_turns / wall-time 上限(长程任务时间难估)。harness-on 和 harness-off 都重跑,**同预算同环境**,否则结论作废。
- 并行度各 8。跑在 pgl(`ssh ubuntu@pgl.zgcagi.ac.cn`),跑前清代理(unset http_proxy/https_proxy/all_proxy 或 NO_PROXY=*),gcp_key 缺失用 docker_nogcs 环境。
- k≥3 重复,先立噪声底(同配置 OFF-OFF 一对),任何效应必须超过噪声底两个标准误才算数。
- 每次跑挂作弊审计:输出是否是 input/ 下真值的仿射变换、agent 自报的测试通过率是否真跑过。留产物(output_path 落盘),否则无法审计。
