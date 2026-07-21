# 目标机 ALE 环境配置与使用（Linux CLI 优先）

面向 `ssh ubuntu@pgl.zgcagi.ac.cn -p 11015` 这台机器，把 ALE（`agents-last-exam`）
跑起来。当前已完成免 root 的全部配置；剩下只有 Docker 安装和镜像拉取需要你用 sudo 密码执行。

> 结论先行：Python 侧（仓库、venv、密钥、模型网关、24 个 CLI 题的数据）已经配好并验证。
> 你只需做两步 sudo 操作（装 Docker、拉镜像），就能跑 Linux CLI 题目。

---

## 1. 这台机器是什么

| 项 | 值 |
|---|---|
| 入口 | `ssh ubuntu@pgl.zgcagi.ac.cn -p 11015`（经 newt/Pangolin 隧道，出口 47.94.2.204 阿里云） |
| 主机名 / 用户 | `ubuntu-server` / `ubuntu` |
| 类型 | KVM 虚拟机（非物理机），已开启嵌套虚拟化（`/dev/kvm` 可用，`kvm_intel nested=Y`） |
| OS / 内核 | Ubuntu 24.04.4 LTS / 6.17 |
| CPU / 内存 | 64 vCPU（Xeon Platinum 8570）/ 125 GiB |
| 磁盘 | `/dev/sda2` 2.0T，可用约 1.6T |
| GPU | 无。GPU 类任务（Isaac Sim/Lab、GPU 加速 Blender/Unreal/DaVinci）跑不了 |
| sudo | 有，但需要密码。非交互 SSH 无法自动装系统包，装 Docker 必须你本人执行 |
| 出网 | 直连可用：HuggingFace、hf-mirror、GitHub、PyPI、Docker Hub 及国内镜像（daocloud / 1ms.run）均可达 |
| 已有 | `~/ale_win_dl/ale-win10.qcow2`（168G，ALE Windows 全 OS 镜像，之前手动 QEMU 启过） |

与当前 IDE 所在机（`batchcom`，有 4×A100-80G + Docker + 现成 93G 镜像 + 全量 task-data）相比：
目标机没有 GPU、原本没有 Docker、网络走隧道。**它的不可替代价值是嵌套 KVM 能跑 Windows / 全
OS 虚拟机任务；纯 Linux CLI 子集它也能跑，但相对 batchcom 是降配。** 本文档按你的优先级配 Linux CLI。

---

## 2. 已经配好的部分（免 root，无需你操作）

路径统一在 `~/ale/agents-last-exam`。

- **uv 0.11.28**：装在 `~/.local/bin`，已写入 `~/.bashrc` 的 PATH。
- **仓库代码**：从 batchcom 的 `agents-last-exam` rsync 过来（不含 `.venv`/`.logs`/全量 task-data）。
  - 额外补了 `ale_run/agents/pi/pyproject.toml`（空 marker）。原仓库 `pi` 自定义 agent 缺 packaging
    元数据，会让 `uv sync --all-packages` 报错；`pi` 只用标准库，补个空包即可，不影响 pi 配置本身。
- **Python 环境 `.venv`（5.7G）**：`uv sync --all-packages --extra dev` 建好（走清华 PyPI 镜像）。
  含 ale_claw 依赖（cua-agent、litellm、torch/torchvision 等）。`python -m ale_run` 与
  `import ale_run, cua_bench, litellm` 均通过。
- **密钥 `secret/.env`**：从 batchcom 拷入，含 gpt-5.6 网关配置：
  `OPENAI_API_BASE=<网关地址见 secret/.env 的 OPENAI_API_BASE>`，`NO_PROXY=*`。已验证网关从目标机可达，
  `GET /v1/models` 返回 200 且列出 `gpt-5.6-sol`。
- **CLI 题数据**：`selected_tasks/cli_nogui_24.txt` 里 24 个 Linux CLI 题的 task-data 已 rsync 到
  `~/ale/agents-last-exam/task-data/`（约 1.8G，其中 sec_10k、hg002 两题占大头）。
- **HF token**：见 `secret/.env` 的 `HF_TOKEN`（不在文档里写明文），配合 `HF_ENDPOINT=https://hf-mirror.com`
  用于后续按需下载全量数据或 qcow2 镜像。注：原文档此处曾明文写入 token，已按密钥卫生要求移除，旧 token 需吊销轮换。

验证记录：
```
uv run python -m ale_run --help      # 正常，子命令 run / list
uv run python -m ale_run list        # discoverable tasks (165)
GET <网关地址见 secret/.env 的 OPENAI_API_BASE>/models  -> 200, gpt-5.6-sol
```

---

## 3. 还需要你做的（要 sudo 密码）

只有两件事：装 Docker、拉镜像。ALE 的本地 Linux 沙箱由 Docker provider 提供，缺 Docker 跑不了。

> 已确认：目标机上**没有任何容器运行时**（docker/dockerd/podman/nerdctl/containerd/apptainer 全无，
> 无 docker.service、无 socket）。**免 root 的 rootless 方案也走不通**：rootless Docker/Podman 依赖
> `newuidmap`/`newgidmap`（`uidmap` 包，setuid-root），目标机没装，装它/给 setuid 都要 root。
> `/etc/subuid`、`/etc/subgid` 已给 ubuntu 配好，用户也在 sudo 组，只差 root 权限本身。
> 结论：装 Docker 这步绕不过 root，一旦有 sudo 约两分钟即可。

### 3.1 安装 Docker（一键脚本）

已把这步做成一键脚本，放在目标机 `~/ale/setup_docker.sh`（仓库副本
`docs/new_run/setup_docker.sh`）。有 sudo 时执行一次：

```bash
sudo bash ~/ale/setup_docker.sh
# 完成后退出重登（或 newgrp docker）让 docker 组生效
```

脚本内容：`apt install docker.io docker-buildx uidmap` → `systemctl enable --now docker` →
写国内镜像源 `daemon.json` → 把当前用户加进 docker 组。（apt 里就有 `docker.io 29.1.3`，
universe 已启用；想要官方最新 docker-ce 再自行加源，对 ALE 没必要。）

验证：`docker version` 且 `docker run --rm hello-world` 能跑通。

### 3.2 拉 ALE 镜像

镜像名 `agentslastexam/ale-ubuntu22-docker:latest`，约 93G。国内镜像源已由上面的脚本写进
`daemon.json`，直接拉即可：

```bash
docker pull agentslastexam/ale-ubuntu22-docker:latest
```

镜像 93G，即便走镜像源也要等一段时间，建议在 `tmux` 里拉。
（不拉也行：首次 `ale_run run` 会自动拉；但先手动拉完更好排查。）

> 关于“把 batchcom 的 93G tar 传过来 `docker load`”：不推荐。隧道实测约 1MB/s，93G 要 ~26 小时。
> tar 在 batchcom 的 `/home/dataset-local/zmh/ALE_TEST/ale-ubuntu22-docker.tar`，仅在你有更快
> 内网直连时才考虑。

---

## 4. 使用方式：跑 Linux CLI 题目

现成的运行配置 `gpt56_cli24_aleclaw.yaml`（agent = ale_claw + gpt-5.6-sol，环境 =
`local_docker_nogcs.yaml` 即 Docker provider，题目 = `selected_tasks/cli_nogui_24.txt` 的 24 题）：

```bash
cd ~/ale/agents-last-exam
tmux new -s ale
uv run python -m ale_run run gpt56_cli24_aleclaw.yaml
```

要点：
- 环境用 `local_docker_nogcs.yaml`：`task_data_source: local:task-data`（用本地已 staged 的数据），
  `output_path: local`，不需要 GCP key。
- 该 yaml 默认 `concurrency: 4`、`wall_time_s: 2400`。目标机 64 vCPU / 125G，并发 4 很宽裕，
  想更快可调大 `concurrency`（注意每题容器按任务卡的机型分 CPU/内存）。
- 结果落在 `~/ale/agents-last-exam/.logs/ale/gpt56_cli24_aleclaw/`：每个 run 有统一 trajectory、
  原始日志、`evaluate()` 打分（[0,1]）、产出物。

先跑 1 题冒烟（确认 Docker + 镜像 + 网关全链路通）再跑全量：临时复制一份只留 1 题的 task 列表，
把 yaml 的 `tasks:` 指过去、`concurrency` 改 1。也可参考仓库里已有的 smoke 配置
（如 `gpt56_smoke_aleclaw`、`local_docker_smoke.yaml`）。

---

## 5. 常见排查

- **`docker: permission denied`**：没重登，docker 组没生效。`newgrp docker` 或重新 SSH。
- **拉镜像卡住**：确认 `/etc/docker/daemon.json` 的 registry-mirrors 已生效并 `systemctl restart docker`。
- **模型调用失败**：`secret/.env` 里 `NO_PROXY=*` 是刻意的（目标机没有本地代理，必须直连网关）。
  网关 `/v1/models` 已验证 200；失败先看 run 日志里的 HTTP 报错。
- **磁盘**：`~` 已占 ~316G（主要是 win10 qcow2）。加上 93G 镜像 + 每题容器层，留意 `df -h /`。
- **某些 CLI 题需要容器内 Docker(DinD) 或 Apptainer**：Docker provider 不支持这几类，官方建议改用
  QEMU provider。若 24 题里某题因此失败，先跳过，或走第 6 节的 QEMU 路径。

---

## 6. 备选：QEMU/KVM 全 OS 路径（Windows 或 DinD/Apptainer 题）

目标机的真正强项。`configs/environments/qemu.yaml` 定义了 `ale-ubuntu22`（Linux）和
`ale-win10`（Windows）两个全 OS 快照，CPU-only，task-data 烤进 qcow2。

- 该 provider 仍需 **Docker + /dev/kvm**（它是“Docker 里套 QEMU”，runner 镜像
  `agentslastexam/ale-qemu:0.2.0`，体积小）。
- qcow2 基础镜像从 HF 拉（走 `HF_ENDPOINT=https://hf-mirror.com` + token）。win10 的已在
  `~/ale_win_dl/ale-win10.qcow2`。
- 适用：Windows 专属题、以及 Docker provider 跑不了的 DinD/Apptainer 题。
- 注意：之前 `~/ale_win_dl` 里是手写 `boot_win.sh` 直接起 QEMU，**没接进 `ale_run` 编排**。
  要正式评测，装好 Docker 后用 qemu.yaml 走 `ale_run`，不要用那套手动脚本。

Linux CLI 优先阶段用不到这条路；列在这里备查。

---

## 7. 关键路径与事实速查

| 项 | 值 |
|---|---|
| 仓库根 | `~/ale/agents-last-exam` |
| 运行命令 | `cd ~/ale/agents-last-exam && uv run python -m ale_run run gpt56_cli24_aleclaw.yaml` |
| CLI 运行配置 | `gpt56_cli24_aleclaw.yaml`（ale_claw × gpt-5.6-sol × Docker provider） |
| 环境配置 | `local_docker_nogcs.yaml`（`local:task-data`，无需 GCP key） |
| CLI 题表 | `selected_tasks/cli_nogui_24.txt`（24 题，已 staged 数据） |
| Docker 镜像 | `agentslastexam/ale-ubuntu22-docker:latest`（~93G，Hub / 国内镜像源拉） |
| 模型网关 | `<网关地址见 secret/.env 的 OPENAI_API_BASE>`，模型 `openai/gpt-5.6-sol`（已验证 200） |
| 结果目录 | `~/ale/agents-last-exam/.logs/ale/<run名>/` |
| venv | `~/ale/agents-last-exam/.venv`（uv 管理，`uv run ...` 或 `uv sync` 重建） |
| 你要做的 | ① `sudo apt-get install -y docker.io docker-buildx` + 加 docker 组；② 配镜像源并拉镜像 |

---

## 8. 重建 / 迁移速记

venv 坏了或要在别处重建：
```bash
cd ~/ale/agents-last-exam
export UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
uv sync --all-packages --extra dev
```
补 task-data（在 batchcom 上执行，把 CLI 题数据推到目标机）：
```bash
grep -vE '^\s*#|^\s*$' selected_tasks/cli_nogui_24.txt > /tmp/cli24.list
# 必须带 -r：--files-from 模式下 -a 不再隐含递归,漏了 -r 只会在目标端建空目录、
# 不拷 base/input 内容,题目会在 stage_inputs 阶段假失败(见 docs/system_issues.md 1.1)。
rsync -ar --files-from=/tmp/cli24.list -e 'ssh -p 11015' \
  task-data/ ubuntu@pgl.zgcagi.ac.cn:~/ale/agents-last-exam/task-data/
# 同步后逐题校验 input 非空:
#   while read t; do ssh -p 11015 ubuntu@pgl.zgcagi.ac.cn \
#     "test -n \"\$(ls -A ~/ale/agents-last-exam/task-data/$t/base/input 2>/dev/null)\" || echo MISSING $t"; done < /tmp/cli24.list
```
或在目标机用 HF 下全量：`download_ale_task_data_only.sh`（HF token 从 `secret/.env` 读，勿写进脚本）。
