#!/usr/bin/env bash
# One-shot Docker setup for ALE on this machine.
#
# Everything else (uv, repo, .venv, secrets, task-data under /home/ubuntu/ale)
# is already configured. This is the ONLY step that needs root.
#
# Run once, as root:
#     sudo bash /home/ubuntu/ale/setup_docker.sh
#
# The ALE user that must end up in the docker group is `ubuntu` (default).
# To target a different user:  sudo ALE_USER=someuser bash setup_docker.sh
#
# After it finishes, that user logs out/in (or runs `newgrp docker`), then:
#     docker pull agentslastexam/ale-ubuntu22-docker:latest   # ~93G, use tmux
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run as root, e.g.  sudo bash $0" >&2
  exit 1
fi

ALE_USER="${ALE_USER:-ubuntu}"
if ! id "${ALE_USER}" >/dev/null 2>&1; then
  echo "ERROR: user '${ALE_USER}' does not exist. Pass ALE_USER=<name>." >&2
  exit 1
fi

echo "[1/5] apt install docker.io + docker-buildx + uidmap"
apt-get update
apt-get install -y docker.io docker-buildx uidmap

echo "[2/5] enable + start docker"
systemctl enable --now docker

echo "[3/5] registry mirrors (CN) -> /etc/docker/daemon.json"
mkdir -p /etc/docker
if [[ -f /etc/docker/daemon.json ]]; then
  cp -a /etc/docker/daemon.json "/etc/docker/daemon.json.bak.$(date +%s 2>/dev/null || echo prev)" 2>/dev/null || true
  echo "  (existing daemon.json backed up)"
fi
cat > /etc/docker/daemon.json <<'JSON'
{ "registry-mirrors": ["https://docker.1ms.run", "https://docker.m.daocloud.io"] }
JSON
systemctl restart docker

echo "[4/5] add '${ALE_USER}' to docker group"
usermod -aG docker "${ALE_USER}"

echo "[5/5] verify"
docker version || true
docker run --rm hello-world || echo "  (hello-world pull may fail if the mirror is slow; not fatal)"

echo
echo "DONE. Now, as user '${ALE_USER}' (after re-login or 'newgrp docker'):"
echo "  docker pull agentslastexam/ale-ubuntu22-docker:latest   # ~93G, use tmux"
echo "  cd ~/ale/agents-last-exam && uv run python -m ale_run run gpt56_cli24_aleclaw.yaml"
