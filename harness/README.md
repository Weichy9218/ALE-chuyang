# pi harness 干预原型

三个只给事实和控制、不给答案的 pi extension,加冒烟测试和一个假零分补丁。设计、消融、不泄露论证见 `../docs/harness_design.md`。

## 目录

```
harness/
  extensions/
    budget-guard.ts    预算护栏:轮末止损 + token 记账 + 耗尽后封锁工具调用
    action-guard.ts    动作前守卫:改前先读、重复失败命令拦截(一次性)
    fact-mirror.ts     事实反射:失败连击、缺文件、指标对照(现值 vs 公开阈值)
  smoke/
    mock_gateway.py    stdlib mock OpenAI 网关,脚本化驱动 pi
    run_smoke.sh       起 mock + 跑真实 pi(json 模式)+ 断言
    check_smoke.py     读 transcript 断言干预是否触发
  patches/
    pi_deployer_false_zero_guard.py   假零分补丁(system_issues.md 3.1),带自检
```

## 跑冒烟测试

```bash
bash smoke/run_smoke.sh guard    # 守卫 + 反射的完整触发路径,5 项断言
bash smoke/run_smoke.sh loop     # 预算硬止损,3 项断言
bash smoke/run_smoke.sh metric   # 指标对照反射,2 项断言
```

不烧真实网关额度。改 extension 后重跑当回归测试。

## 挂到 ale_run 做消融

三个 extension 由环境变量控制,ale_run 侧通过 pi 配置的 `extra_envs` 下发。要在真实评测里挂:

1. 把 `extensions/*.ts` 放进 pi 的 agent 目录 `extensions/` 子目录(pi deployer 写 models.json 到 `~/.pi/agent/`,extensions 放同级 `~/.pi/agent/extensions/`),或用 pi 的 `--extensions <dir>` flag(需在 deployer 的 `_build_argv` 加)。
2. 在 pi agent 配置 yaml 的 `config.extra_envs` 里设开关。

消融矩阵(同题同模型,只差开关):

| 配置 | extra_envs |
|---|---|
| 基线 | `PI_GUARD_BUDGET: off` `PI_GUARD_ACTION: off` `PI_GUARD_MIRROR: off` |
| 只止损 | `PI_GUARD_ACTION: off` `PI_GUARD_MIRROR: off` |
| 只守卫 | `PI_GUARD_BUDGET: off` `PI_GUARD_MIRROR: off` |
| 只反射 | `PI_GUARD_BUDGET: off` `PI_GUARD_ACTION: off` |
| 全开 | (全默认,不设 off) |

全部开关和阈值见各 extension 文件头注释。指标对照镜子要用 `PI_MIRROR_METRIC_SPEC`(JSON)显式配,阈值只能从任务公开规格抄——这是不泄露的前提。

## 假零分补丁

`patches/pi_deployer_false_zero_guard.py` 是不改 pi、只改 ale_run pi deployer 的最小修复。把 `detect_llm_error_stop` 拷进 `ale_run/agents/pi/deployer.py`,按文件末尾 PATCH 示意在 launch() 里插一段。带 5 条自检:`python3 patches/pi_deployer_false_zero_guard.py`。
