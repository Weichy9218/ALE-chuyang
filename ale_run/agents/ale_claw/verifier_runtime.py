"""Read-only output snapshots for the reviewer arm.

What survives here is the snapshot infrastructure the ``reviewer`` arm depends
on: an immutable, hashed copy of ``output/`` per audit round, the
repair-regression guard (``snapshot_regressed`` + ``restore_snapshot``), and the
allowlist reconcile (``reconcile_to_allowlist``) that bounds a repair round to
the artifacts the audit named. The frozen-test-suite executor that used to live
here (candidate/final suites, sandboxed checker runs) was part of the retired
``verifier`` arm and has been removed; only ``ArtifactSnapshot`` is still shared
from ``verifier.py``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shlex
from pathlib import PurePosixPath
from typing import Any

from .verifier import ArtifactSnapshot

logger = logging.getLogger(__name__)

MAX_SNAPSHOT_MANIFEST_FILES = 400
# Repair-regression guard (reviewer arm). A repair round mutates the whole
# output/ bundle, but the audit only re-derives the fields it chose; anything
# outside that slice can silently regress. The cheapest way for a writer to
# "satisfy" a mechanical finding is to shrink or drop an artifact, which is
# exactly what a hidden delivery rubric punishes (sec_10k: raw evidence went
# 76 MB verbatim -> 156 KB paraphrase, 0.685 -> 0.163). These bounds trigger a
# rollback only on catastrophic, unambiguous loss, so ordinary field edits
# (which barely move total bytes) never false-positive.
SNAPSHOT_REGRESSION_MIN_BYTE_RATIO = 0.5
SNAPSHOT_REGRESSION_MIN_FILE_RATIO = 0.75


async def stage_verifier_report(
    interface: Any,
    *,
    task_root: str,
    filename: str,
    report: dict[str, Any],
) -> str | None:
    """Expose one complete audit result to the Writer inside the task VM."""
    report_dir = task_root.rstrip("/") + "/verifier"
    report_path = f"{report_dir}/{filename}"
    try:
        await interface.create_dir(report_dir)
        await interface.write_text(
            report_path,
            json.dumps(report, indent=2, ensure_ascii=True) + "\n",
            append=False,
        )
    except Exception as exc:  # reporting must not abort the writer
        logger.warning("could not stage audit report at %s: %s", report_path, exc)
        return None
    return report_path


async def _tree_hash(interface: Any, path: str) -> str:
    quoted = shlex.quote(path)
    command = (
        f"if [ -L {quoted} ]; then "
        f"printf 'link %s\\n' \"$(readlink -- {quoted})\" | sha256sum | awk '{{print $1}}'; "
        f"elif [ -d {quoted} ]; then cd {quoted} && "
        "fh=$(find . -type f -print0 | sort -z | xargs -0 -r sha256sum | "
        "sha256sum | awk '{print $1}') && "
        "ph=$(find . -printf '%y %P -> %l\\n' | sort | sha256sum | awk '{print $1}') && "
        "printf '%s %s\\n' \"$fh\" \"$ph\" | sha256sum | awk '{print $1}'; "
        f"elif [ -f {quoted} ]; then sha256sum {quoted} | sha256sum | awk '{{print $1}}'; "
        "else printf 'missing\\n' | sha256sum | awk '{print $1}'; fi"
    )
    result = await interface.run_command(command)
    value = str(getattr(result, "stdout", "") or "").strip()
    if getattr(result, "returncode", 1) != 0 or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RuntimeError(f"could not hash {path}")
    return value


async def snapshot_output(
    *,
    interface: Any,
    task_root: str,
    os_type: str,
    iteration: int | str,
) -> ArtifactSnapshot:
    """Copy ``output/`` into an immutable snapshot directory.

    ``iteration`` names the snapshot: post-DONE review rounds use 0, 1, ...;
    writer-triggered pre-submission checks use ``writer1``, ``writer2``, ... so
    the two families can never collide.
    """
    if os_type.lower() != "linux":
        raise RuntimeError("verifier requires Linux")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", str(iteration)):
        raise ValueError(f"invalid snapshot iteration label: {iteration!r}")
    token = hashlib.sha256(task_root.encode()).hexdigest()[:12]
    snapshot = f"/tmp/ale-verifier-{token}/snapshot-{iteration}"
    rejected_symlinks = f"{snapshot}-rejected-symlinks.txt"
    output = task_root.rstrip("/") + "/output"
    source_sha256 = await _tree_hash(interface, output)
    command = (
        f"rm -rf {shlex.quote(snapshot)} && rm -f {shlex.quote(rejected_symlinks)} && "
        f"mkdir -p {shlex.quote(snapshot)} && : > {shlex.quote(rejected_symlinks)} && "
        f"if [ -L {shlex.quote(output)} ]; then "
        f"printf '. -> %s\\n' \"$(readlink -- {shlex.quote(output)})\" > {shlex.quote(rejected_symlinks)}; "
        f"elif [ -d {shlex.quote(output)} ]; then cp -a {shlex.quote(output)}/. {shlex.quote(snapshot)}/; "
        f"elif [ -e {shlex.quote(output)} ]; then cp -a {shlex.quote(output)} {shlex.quote(snapshot)}/; fi && "
        f"cd {shlex.quote(snapshot)} && "
        f"find . -type l -printf '%P -> %l\\n' | sort >> {shlex.quote(rejected_symlinks)} && "
        "find . -type l -delete && "
        f"chmod -R a-w {shlex.quote(snapshot)} {shlex.quote(rejected_symlinks)} && "
        "n=$(find . -type f | wc -l) && "
        "b=$(find . -type f -printf '%s\\n' | awk '{s+=$1} END{print s+0}') && "
        "fh=$(find . -type f -print0 | sort -z | xargs -0 -r sha256sum | "
        "sha256sum | awk '{print $1}') && "
        "ph=$(find . -printf '%y %P -> %l\\n' | sort | sha256sum | awk '{print $1}') && "
        "h=$(printf '%s %s\\n' \"$fh\" \"$ph\" | sha256sum | awk '{print $1}') && "
        "printf '%s %s %s\\n' \"$h\" \"$n\" \"$b\""
    )
    result = await interface.run_command(command)
    if getattr(result, "returncode", 1) != 0:
        raise RuntimeError(
            f"could not snapshot output: {str(getattr(result, 'stderr', '') or '').strip()}"
        )
    parts = str(getattr(result, "stdout", "") or "").strip().split()
    if len(parts) != 3 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
        raise RuntimeError(f"invalid snapshot receipt: {parts!r}")
    if await _tree_hash(interface, output) != source_sha256:
        raise RuntimeError("writer output changed while snapshotting")
    return ArtifactSnapshot(
        path=snapshot,
        sha256=parts[0],
        source_sha256=source_sha256,
        file_count=int(parts[1]),
        total_bytes=int(parts[2]),
        rejected_symlinks_path=rejected_symlinks,
    )


def snapshot_regressed(
    current: ArtifactSnapshot, baseline: ArtifactSnapshot
) -> str | None:
    """Reason string if ``current`` catastrophically lost content vs ``baseline``.

    Read-only comparison of two snapshot receipts. Returns None when the change
    is within bounds. Only a large collapse trips it, so a writer that legitimately
    edited a few field values (leaving total size roughly intact) is never flagged;
    a writer that deleted files or replaced verbatim evidence with a summary is.
    """
    if baseline.total_bytes > 0 and (
        current.total_bytes < baseline.total_bytes * SNAPSHOT_REGRESSION_MIN_BYTE_RATIO
    ):
        return (
            f"output shrank from {baseline.total_bytes} to {current.total_bytes} bytes "
            f"(< {SNAPSHOT_REGRESSION_MIN_BYTE_RATIO:.0%} of pre-repair size)"
        )
    if baseline.file_count > 0 and (
        current.file_count < baseline.file_count * SNAPSHOT_REGRESSION_MIN_FILE_RATIO
    ):
        return (
            f"output lost files: {baseline.file_count} -> {current.file_count} "
            f"(< {SNAPSHOT_REGRESSION_MIN_FILE_RATIO:.0%} of pre-repair count)"
        )
    return None


async def restore_snapshot(
    *, interface: Any, task_root: str, snapshot: ArtifactSnapshot
) -> None:
    """Deterministically restore ``output/`` from an immutable snapshot copy.

    Used by the reviewer arm to roll back a repair round that regressed the
    bundle: the snapshot is a read-only ``cp -a`` of the pre-repair output, so
    clearing output/ and copying it back reproduces that exact state. Verifies
    the restored tree hash matches the snapshot receipt; raises on mismatch so
    the caller can fail-open (keep the writer's last output) rather than grade a
    half-restored tree.
    """
    output = task_root.rstrip("/") + "/output"
    q_out = shlex.quote(output)
    q_snap = shlex.quote(snapshot.path)
    command = (
        f"chmod -R u+w {q_out} 2>/dev/null; "
        f"mkdir -p {q_out} && find {q_out} -mindepth 1 -delete && "
        f"cp -a {q_snap}/. {q_out}/"
    )
    result = await interface.run_command(command)
    if getattr(result, "returncode", 1) != 0:
        raise RuntimeError(
            f"could not restore snapshot: {str(getattr(result, 'stderr', '') or '').strip()}"
        )
    if await _tree_hash(interface, output) != snapshot.source_sha256:
        raise RuntimeError("restored output does not match snapshot source hash")


def _normalize_allowlist_paths(allowlist: Any) -> list[str]:
    """Map ``ReviewerFinding.artifact`` strings to safe, output/-relative paths.

    A finding names its artifact however the auditor phrased it: ``output/foo.json``,
    ``./output/foo``, an absolute ``/media/.../output/foo``, or a bare ``foo``. We
    strip any leading run of segments up to and including the last ``output/`` and
    normalize the rest. Anything that would escape ``output/`` (a ``..`` segment,
    an empty result) is dropped rather than trusted. Returns a sorted, de-duped
    list; directory prefixes are kept as-is so a whole subtree can be allowlisted.
    """
    out: set[str] = set()
    for raw in allowlist or ():
        if not raw:
            continue
        text = str(raw).strip().replace("\\", "/")
        marker = "output/"
        idx = text.rfind(marker)
        if idx != -1:
            text = text[idx + len(marker):]
        parts = [seg for seg in text.split("/") if seg not in ("", ".")]
        if not parts or any(seg == ".." for seg in parts):
            continue
        out.add("/".join(parts))
    return sorted(out)


async def reconcile_to_allowlist(
    *,
    interface: Any,
    task_root: str,
    snapshot: ArtifactSnapshot,
    allowlist: Any,
) -> dict[str, Any]:
    """Bound a repair round's blast radius to the artifacts the audit named.

    After the writer repairs in place, keep ONLY the allowlisted paths from the
    new ``output/`` and revert every other path to the pre-repair ``snapshot``.
    The allowlist is the set of ``finding.artifact`` paths the audit asked the
    writer to fix, so anything else the writer touched (a whole-pipeline re-run
    that regenerated an un-audited artifact — sec_10k ``raw_extractions/``) is
    discarded. This is a strictly finer net than ``snapshot_regressed``'s
    catastrophic-loss guard and composes with it.

    Mechanics: stash the allowlisted paths aside, fully restore ``output/`` from
    the immutable snapshot (reusing ``restore_snapshot``, whose tree-hash check
    still holds because at that instant ``output/`` equals the snapshot), then
    copy the stashed paths back over the restored tree and re-enable writes (the
    snapshot copy is read-only, but the loop may run another repair round). A
    directory allowlist entry carries its whole subtree. Returns an audit record
    (``mode`` + the normalized allowlist + the paths actually preserved); the
    caller logs it and fails open on any raised error (keeping the writer output).
    """
    output = task_root.rstrip("/") + "/output"
    q_out = shlex.quote(output)
    rels = _normalize_allowlist_paths(allowlist)
    if not rels:
        # Nothing groundable to keep (no named artifacts, or all escaped output/):
        # the writer changed only un-named files, so revert the whole round.
        await restore_snapshot(interface=interface, task_root=task_root, snapshot=snapshot)
        await interface.run_command(f"chmod -R u+w {q_out} 2>/dev/null; true")
        return {"mode": "full_revert", "allowlist": [], "kept": []}

    stash = snapshot.path.rstrip("/") + ".reconcile-stash"
    q_stash = shlex.quote(stash)

    # 1. Stash the allowlisted paths that currently exist in the repaired output/,
    #    echoing each one actually stashed so we know exactly what to copy back.
    stash_cmds = [f"rm -rf {q_stash}", f"mkdir -p {q_stash}"]
    for rel in rels:
        src = shlex.quote(f"{output}/{rel}")
        dst = shlex.quote(f"{stash}/{rel}")
        parent = shlex.quote(str(PurePosixPath(f"{stash}/{rel}").parent))
        stash_cmds.append(
            f"if [ -e {src} ]; then mkdir -p {parent} && cp -a {src} {dst} "
            f"&& printf '%s\\n' {shlex.quote(rel)}; fi"
        )
    stash_result = await interface.run_command("; ".join(stash_cmds))
    if getattr(stash_result, "returncode", 1) != 0:
        raise RuntimeError(
            "could not stash allowlisted paths: "
            f"{str(getattr(stash_result, 'stderr', '') or '').strip()}"
        )
    kept = [
        line.strip()
        for line in str(getattr(stash_result, "stdout", "") or "").splitlines()
        if line.strip()
    ]

    # 2. Full revert to the pre-repair snapshot (hash-verified: at this instant
    #    output/ equals the snapshot, so restore_snapshot's check passes).
    await restore_snapshot(interface=interface, task_root=task_root, snapshot=snapshot)

    # 3. Copy the stashed allowlisted paths back over the restored tree, drop the
    #    stash, and re-enable writes so the next repair round can edit output/.
    #    The restore left output/ read-only (it carries the snapshot's a-w bits),
    #    so make it writable FIRST, or the per-path `rm -rf` fails on the parent.
    back_cmds: list[str] = [f"chmod -R u+w {q_out} 2>/dev/null; true"]
    for rel in kept:
        src = shlex.quote(f"{stash}/{rel}")
        dst = shlex.quote(f"{output}/{rel}")
        parent = shlex.quote(str(PurePosixPath(f"{output}/{rel}").parent))
        back_cmds.append(
            f"rm -rf {dst}; mkdir -p {parent} && cp -a {src} {dst}"
        )
    back_cmds.append(f"rm -rf {q_stash}")
    back_cmds.append(f"chmod -R u+w {q_out} 2>/dev/null; true")
    back_result = await interface.run_command("; ".join(back_cmds))
    if getattr(back_result, "returncode", 1) != 0:
        raise RuntimeError(
            "could not restore allowlisted paths after reconcile: "
            f"{str(getattr(back_result, 'stderr', '') or '').strip()}"
        )
    return {"mode": "reconciled", "allowlist": rels, "kept": kept}


async def snapshot_manifest(
    interface: Any, snapshot: ArtifactSnapshot
) -> list[dict[str, Any]]:
    """Per-file size and line count of one immutable snapshot.

    Recorded on every snapshot so the analyzer can see what a writer did after
    a signal arrived: whether the next output grew, shrank, or lost files.
    Deleting content is the cheapest way to pass a mechanical check, and it is
    exactly what the hidden rubric tends to punish, so the direction of change
    is the reading that matters. Cheap and read-only; failure yields [].
    """
    quoted = shlex.quote(snapshot.path)
    command = (
        f"cd {quoted} && find . -type f -printf '%P\\n' | sort | "
        f"head -n {MAX_SNAPSHOT_MANIFEST_FILES} | "
        "while IFS= read -r f; do "
        "printf '%s\\t%s\\t%s\\n' \"$(wc -c < \"$f\")\" \"$(wc -l < \"$f\")\" \"$f\"; "
        "done"
    )
    try:
        result = await interface.run_command(command)
    except Exception as exc:  # noqa: BLE001 - a manifest is diagnostics only
        logger.warning("could not read snapshot manifest: %s", exc)
        return []
    if getattr(result, "returncode", 1) != 0:
        return []
    entries: list[dict[str, Any]] = []
    for line in str(getattr(result, "stdout", "") or "").splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        try:
            entries.append({
                "path": parts[2],
                "bytes": int(parts[0]),
                "lines": int(parts[1]),
            })
        except ValueError:
            continue
    return entries
