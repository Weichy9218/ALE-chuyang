#!/usr/bin/env bash
# Build the `ale-ubuntu22-docker` container image from the `ale-ubuntu22` GCE
# sandbox VM, without rebuilding any packages: a container only needs the
# userspace rootfs (the kernel is the host's), so we export the VM's root
# filesystem and import it as a single layer, then bake a container entrypoint.
#
# Phases (resumable — a present rootfs tar is reused unless ALE_FORCE_EXPORT=1):
#   1. export   ssh <vm> tar(/) | zstd            -> $WORKDIR/rootfs.tar.zst
#   2. import   zstd -dc | docker import                  -> $IMAGE-base
#   3. finalize run base, bake entrypoint + cleanup, commit -> $IMAGE
#   4. smoke    boot it the way the provider does, poll cua-server /status
#
# Config via env (defaults target the dev-ubuntu22 box in us-west2-a):
#   ALE_BUILD_VM / ALE_BUILD_ZONE / ALE_BUILD_SSH_USER / ALE_BUILD_SSH_KEY
#   ALE_BUILD_IMAGE   final tag (default ale-ubuntu22-docker:latest)
#   ALE_BUILD_WORKDIR scratch dir for the rootfs tar (needs ~100GB free)
#   ALE_FORCE_EXPORT=1   re-export even if the tar exists
#   ALE_KEEP_VM=1        do not stop the VM afterwards even if we started it
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VM="${ALE_BUILD_VM:-dev-ubuntu22}"
ZONE="${ALE_BUILD_ZONE:-us-west2-a}"
SSH_USER="${ALE_BUILD_SSH_USER:-weichenzhang}"
SSH_KEY="${ALE_BUILD_SSH_KEY:-$HOME/.ssh/google_compute_engine}"
IMAGE="${ALE_BUILD_IMAGE:-ale-ubuntu22-docker:latest}"
BASE="${IMAGE%%:*}:base"
WORKDIR="${ALE_BUILD_WORKDIR:-$HOME/.cache/ale-docker-build}"
TAR="$WORKDIR/rootfs.tar.zst"

SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o ConnectTimeout=20 -o ServerAliveInterval=30 -o ServerAliveCountMax=20)

log() { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
die() { printf '\nFATAL: %s\n' "$*" >&2; exit 1; }

mkdir -p "$WORKDIR"

# --- VM lifecycle: ensure it is RUNNING, remember whether we started it -------
started=0
status="$(gcloud compute instances describe "$VM" --zone "$ZONE" --format='value(status)' 2>/dev/null || true)"
[ -n "$status" ] || die "VM $VM not found in zone $ZONE"
if [ "$status" != "RUNNING" ]; then
  log "starting $VM (was $status)"
  gcloud compute instances start "$VM" --zone "$ZONE" >/dev/null
  started=1
fi
IP="$(gcloud compute instances describe "$VM" --zone "$ZONE" \
       --format='value(networkInterfaces[0].accessConfigs[0].natIP)')"
[ -n "$IP" ] || die "no external IP for $VM"

restore_vm() {
  if [ "$started" = 1 ] && [ "${ALE_KEEP_VM:-0}" != 1 ]; then
    log "stopping $VM (restore prior state)"
    gcloud compute instances stop "$VM" --zone "$ZONE" >/dev/null || true
  fi
}
trap restore_vm EXIT

# wait for SSH. Prime the key via `gcloud compute ssh` first: it propagates
# our public key to the instance (metadata / OS Login) and waits for sshd, so
# the subsequent raw ssh (used for a clean binary tar stream) can connect.
log "priming SSH on $SSH_USER@$IP"
for _ in $(seq 1 40); do
  gcloud compute ssh "$VM" --zone "$ZONE" --command true >/dev/null 2>&1 && break
  sleep 5
done
ssh "${SSH_OPTS[@]}" "$SSH_USER@$IP" true 2>/dev/null \
  || gcloud compute ssh "$VM" --zone "$ZONE" --command true >/dev/null 2>&1 \
  || die "cannot SSH to $VM ($SSH_USER@$IP)"

# --- build-on-VM mode --------------------------------------------------------
# ALE_BUILD_ON_VM=1: import + finalize + smoke (+ optional push) ALL on the VM,
# so the ~37GB rootfs never crosses the network — the slow SSH transfer the
# default mode pays. Requires docker on the VM. Same scripts/excludes as the
# default path, so it produces an identical image.
#   ALE_PUSH_IMAGE=1   also docker push $IMAGE FROM the VM (Hub token piped over
#                      stdin transiently; the image is captured before login, so
#                      the credential is never baked).
if [ "${ALE_BUILD_ON_VM:-0}" = 1 ]; then
  log "build-on-VM on $VM: import+finalize+smoke (rootfs stays on the VM)"
  for f in export_rootfs.sh entrypoint.sh cleanup.sh; do
    ssh "${SSH_OPTS[@]}" "$SSH_USER@$IP" "cat > /tmp/ale-build-$f" < "$HERE/$f"
  done
  ssh "${SSH_OPTS[@]}" "$SSH_USER@$IP" 'bash -s' "$IMAGE" "$BASE" <<'VMBUILD'
set -euo pipefail
IMAGE="$1"; BASE="$2"
vlog(){ printf '\n[VM] === %s ===\n' "$*"; }
vlog "import: raw tar | docker import (no network)"
docker rmi -f "$BASE" 2>/dev/null || true
ALE_EXPORT_RAW=1 bash /tmp/ale-build-export_rootfs.sh | docker import - "$BASE"
rc="$(cat /tmp/ale_export_tar.rc 2>/dev/null || echo 99)"
case "$rc" in 0|1) ;; *) echo "FATAL tar exit $rc"; exit 1;; esac
vlog "finalize: entrypoint + cleanup -> commit $IMAGE"
cid="$(docker run -d --user 0 "$BASE" sleep infinity)"
docker exec "$cid" mkdir -p /dockerstartup
docker cp /tmp/ale-build-entrypoint.sh "$cid:/dockerstartup/entrypoint.sh"
docker cp /tmp/ale-build-cleanup.sh "$cid:/root/cleanup.sh"
docker exec "$cid" bash /root/cleanup.sh
docker commit --change 'USER user' --change 'WORKDIR /home/user' \
  --change 'ENV HOME=/home/user' \
  --change 'ENV PATH=/home/user/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
  --change 'CMD ["/bin/bash"]' "$cid" "$IMAGE" >/dev/null
docker rm -f "$cid" >/dev/null
echo "committed $IMAGE ($(docker image inspect "$IMAGE" --format '{{.Size}}' | numfmt --to=iec))"
vlog "smoke: boot + poll cua /status"
sid="$(docker run -d --rm -p 0:5000 --shm-size=2g --entrypoint /dockerstartup/entrypoint.sh "$IMAGE" --wait)"
hp="$(docker inspect --format '{{(index (index .NetworkSettings.Ports "5000/tcp") 0).HostPort}}' "$sid")"
ok=; for _ in $(seq 1 30); do r="$(curl -s -m 4 http://localhost:$hp/status 2>/dev/null || true)"; [ -n "$r" ] && { ok="$r"; break; }; sleep 3; done
docker rm -f "$sid" >/dev/null 2>&1 || true
[ -n "$ok" ] || { echo "FATAL cua not ready"; exit 1; }
echo "cua-server /status: $ok"
VMBUILD
  if [ "${ALE_PUSH_IMAGE:-0}" = 1 ]; then
    log "push $IMAGE FROM $VM (transient Hub login)"
    auth="$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.docker/config.json")))["auths"]["https://index.docker.io/v1/"]["auth"])')"
    creds="$(printf '%s' "$auth" | base64 -d)"; huser="${creds%%:*}"; htok="${creds#*:}"
    printf '%s' "$htok" | ssh "${SSH_OPTS[@]}" "$SSH_USER@$IP" \
      "docker login -u '$huser' --password-stdin >/dev/null && docker push '$IMAGE' && docker logout >/dev/null && echo PUSHED_FROM_VM"
  fi
  log "DONE (on-VM): built $IMAGE on $VM"
  exit 0
fi

# --- phase 1: export rootfs --------------------------------------------------
if [ -s "$TAR" ] && [ "${ALE_FORCE_EXPORT:-0}" != 1 ]; then
  log "phase 1 export: reusing $TAR ($(du -h "$TAR" | cut -f1)) — set ALE_FORCE_EXPORT=1 to redo"
else
  log "phase 1 export: $SSH_USER@$IP rootfs -> $TAR"
  ssh "${SSH_OPTS[@]}" "$SSH_USER@$IP" 'bash -s' < "$HERE/export_rootfs.sh" > "$TAR"
  rc="$(ssh "${SSH_OPTS[@]}" "$SSH_USER@$IP" 'cat /tmp/ale_export_tar.rc 2>/dev/null || echo 99')"
  case "$rc" in
    0|1) echo "tar exit $rc (ok)";;
    *)   die "tar exit $rc (fatal) — see /tmp/ale_export_tar.err on $VM";;
  esac
  echo "exported $(du -h "$TAR" | cut -f1) compressed"
fi

# --- phase 2: docker import --------------------------------------------------
# Out-of-range owners were already clamped to root on the VM (export_rootfs.sh),
# so this is a plain stream — no Python remap pass needed.
log "phase 2 import: $TAR -> docker image $BASE"
docker rmi -f "$BASE" 2>/dev/null || true
zstd -dc "$TAR" | docker import - "$BASE"

# --- phase 3: bake entrypoint + cleanup, commit ------------------------------
log "phase 3 finalize: bake entrypoint + cleanup -> commit $IMAGE"
cid="$(docker run -d --user 0 "$BASE" sleep infinity)"
cleanup_build() { docker rm -f "$cid" >/dev/null 2>&1 || true; }
trap 'cleanup_build; restore_vm' EXIT

docker exec "$cid" mkdir -p /dockerstartup
docker cp "$HERE/entrypoint.sh" "$cid:/dockerstartup/entrypoint.sh"
docker cp "$HERE/cleanup.sh"     "$cid:/root/cleanup.sh"
docker exec "$cid" bash /root/cleanup.sh

docker commit \
  --change 'USER user' \
  --change 'WORKDIR /home/user' \
  --change 'ENV HOME=/home/user' \
  --change 'ENV PATH=/home/user/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
  --change 'CMD ["/bin/bash"]' \
  "$cid" "$IMAGE" >/dev/null
cleanup_build
trap restore_vm EXIT
echo "committed $IMAGE ($(docker image inspect "$IMAGE" --format '{{.Size}}' | numfmt --to=iec))"

# --- phase 4: smoke — boot it exactly as the docker provider does ------------
log "phase 4 smoke: boot $IMAGE, poll cua-server /status"
sid="$(docker run -d --rm -p 0:5000 --shm-size=2g \
         --entrypoint /dockerstartup/entrypoint.sh "$IMAGE" --wait)"
smoke_clean() { docker rm -f "$sid" >/dev/null 2>&1 || true; }
trap 'smoke_clean; restore_vm' EXIT
hp="$(docker inspect --format '{{(index (index .NetworkSettings.Ports "5000/tcp") 0).HostPort}}' "$sid")"
ok=
for _ in $(seq 1 30); do
  r="$(curl -s -m 4 "http://localhost:$hp/status" 2>/dev/null || true)"
  [ -n "$r" ] && { ok="$r"; break; }
  sleep 3
done
smoke_clean
trap restore_vm EXIT
[ -n "$ok" ] || die "cua-server did not become ready"
echo "cua-server /status: $ok"

log "DONE: built $IMAGE"
