"""The reviewer repair round must not silently regress the graded bundle.

Regression for the sec_10k A/B of 2026-08-04: one of three reviewer runs, in a
repair round, re-ran its extraction pipeline and overwrote `raw_extractions/`
from ~76 MB of verbatim 10-K source text with a 156 KB paraphrase. The audit's
five zero-discrepancy counters are blind to "verbatim source degraded to
summary", so the gate passed while a differently-graded requirement silently
broke and the score collapsed 0.685 -> 0.163.

The guard compares each repair round's post-snapshot against the pre-repair
snapshot on two locally-observable, grader-independent properties (total bytes,
file count); if the bundle shrinks past a ratio it rolls `output/` back to the
pre-repair snapshot and stops with stop_reason="repair_regressed". This test
pins the decision logic (`snapshot_regressed`, incl. the exact sec_10k numbers
and both thresholds) and the rollback mechanics (`restore_snapshot`) end to end.
"""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from ale_run.agents.ale_claw.verifier import ArtifactSnapshot
from ale_run.agents.ale_claw.verifier_runtime import (
    SNAPSHOT_REGRESSION_MIN_BYTE_RATIO,
    SNAPSHOT_REGRESSION_MIN_FILE_RATIO,
    _tree_hash,
    restore_snapshot,
    snapshot_regressed,
)

MB = 1024 * 1024


def _snap(total_bytes: int, file_count: int, *, path: str = "/x", src: str = "s") -> ArtifactSnapshot:
    return ArtifactSnapshot(
        path=path,
        sha256="a" * 64,
        source_sha256=src,
        file_count=file_count,
        total_bytes=total_bytes,
    )


# --------------------------------------------------------------------------- #
# Decision logic: snapshot_regressed                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name, current, baseline, expect_regressed",
    [
        # The real failure: 76 MB verbatim -> 156 KB paraphrase. MUST trip.
        ("sec_10k collapse 76MB->156KB", _snap(156 * 1024, 40), _snap(76 * MB, 40), True),
        # Healthy repair: output grew, files stable. MUST NOT trip.
        ("healthy repair grows", _snap(80 * MB, 42), _snap(76 * MB, 40), False),
        # Small legitimate shrink (reformatted a file, -10%). MUST NOT trip.
        ("minor shrink -10%", _snap(int(76 * MB * 0.90), 40), _snap(76 * MB, 40), False),
        # Byte ratio exactly at threshold is NOT below it -> no trip.
        ("bytes exactly 50%", _snap(76 * MB // 2, 40), _snap(76 * MB, 40), False),
        # Just under the byte threshold -> trip.
        ("bytes just under 50%", _snap(76 * MB // 2 - 1, 40), _snap(76 * MB, 40), True),
        # Lost >25% of files while bytes held (deleted artifacts). MUST trip.
        ("file loss 40->29", _snap(76 * MB, 29), _snap(76 * MB, 40), True),
        # File ratio exactly at threshold is NOT below it -> no trip.
        ("file count exactly 75%", _snap(76 * MB, 30), _snap(76 * MB, 40), False),
        # A zero/empty baseline (e.g. missing pre-snapshot) disables the guard.
        ("zero baseline no-op", _snap(156 * 1024, 40), _snap(0, 0), False),
    ],
)
def test_snapshot_regressed(name, current, baseline, expect_regressed):
    reason = snapshot_regressed(current, baseline)
    assert (reason is not None) is expect_regressed, f"{name}: reason={reason!r}"


def test_thresholds_are_what_the_postmortem_assumed():
    # 156 KB vs 76 MB is ~0.2% — trivially below either ratio; the guard would be
    # useless if these drifted up toward 1.0.
    assert SNAPSHOT_REGRESSION_MIN_BYTE_RATIO == 0.5
    assert SNAPSHOT_REGRESSION_MIN_FILE_RATIO == 0.75


# --------------------------------------------------------------------------- #
# Rollback mechanics: restore_snapshot (real cp + hash, local subprocess)     #
# --------------------------------------------------------------------------- #
@dataclass
class _Result:
    returncode: int
    stdout: str
    stderr: str


class _LocalInterface:
    """Runs the guard's shell commands locally so restore_snapshot exercises its
    real `cp -a` + tree-hash verification without Docker."""

    async def run_command(self, command: str) -> _Result:
        p = subprocess.run(command, shell=True, capture_output=True, text=True)
        return _Result(p.returncode, p.stdout, p.stderr)


def test_restore_snapshot_recovers_regressed_output(tmp_path: Path):
    async def scenario() -> None:
        iface = _LocalInterface()
        task_root = tmp_path / "task"
        output = task_root / "output"
        raw = output / "raw_extractions"
        raw.mkdir(parents=True)
        # Pre-repair bundle: a big verbatim evidence file + a small answer file.
        (raw / "verbatim_10k.txt").write_text("EVIDENCE\n" * 100_000)
        (output / "qa_answers.json").write_text('{"ok": true}\n')

        # Immutable snapshot = a cp -a of the pre-repair output (as the harness does).
        snap_dir = tmp_path / "snapshot"
        subprocess.run(f"cp -a {output} {snap_dir}", shell=True, check=True)
        src_hash = await _tree_hash(iface, str(output))
        pre = ArtifactSnapshot(
            path=str(snap_dir), sha256="a" * 64, source_sha256=src_hash,
            file_count=2, total_bytes=(raw / "verbatim_10k.txt").stat().st_size,
        )

        # A bad repair round collapses the verbatim evidence to a paraphrase.
        (raw / "verbatim_10k.txt").write_text("summary of evidence\n")
        post = ArtifactSnapshot(
            path=str(snap_dir), sha256="b" * 64, source_sha256="different",
            file_count=2, total_bytes=(raw / "verbatim_10k.txt").stat().st_size,
        )
        assert snapshot_regressed(post, pre) is not None  # guard trips

        # Rollback restores output/ byte-for-byte to the pre-repair state.
        await restore_snapshot(interface=iface, task_root=str(task_root), snapshot=pre)
        assert await _tree_hash(iface, str(output)) == src_hash
        assert (raw / "verbatim_10k.txt").read_text() == "EVIDENCE\n" * 100_000

    asyncio.run(scenario())
