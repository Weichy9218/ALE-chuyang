"""A reviewer repair round may only change the artifacts the audit named.

Follow-up to the sec_10k repair-regression post-mortem (2026-08-04): the byte
guard (`test_repair_regression_guard.py`) is a coarse net that only trips on a
catastrophic collapse. The allowlist reconcile is the fine net: after the writer
repairs in place, only the paths named by the audit's findings
(`ReviewerFinding.artifact`) survive; every other path is reverted to the
pre-repair snapshot. This bounds a whole-pipeline re-run's blast radius to the
named defects, so a re-run can't clobber an un-audited graded artifact even when
the total byte size barely moves (which is exactly what the byte guard misses).

Pins path normalization (`_normalize_allowlist_paths`) and the reconcile
mechanics (`reconcile_to_allowlist`) end to end with a real `cp -a` + tree-hash
against a local subprocess, no Docker.
"""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from ale_run.agents.ale_claw.verifier import ArtifactSnapshot
from ale_run.agents.ale_claw.verifier_runtime import (
    _normalize_allowlist_paths,
    _tree_hash,
    reconcile_to_allowlist,
)


# --------------------------------------------------------------------------- #
# Path normalization                                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        (["output/qa_answers.json"], ["qa_answers.json"]),
        (["./output/foo/bar.csv"], ["foo/bar.csv"]),
        (["/media/task/output/deep/x.json"], ["deep/x.json"]),
        (["qa_answers.json"], ["qa_answers.json"]),          # already relative
        (["raw_extractions"], ["raw_extractions"]),           # a directory prefix
        (["output/a", "output/a", "output/b"], ["a", "b"]),   # dedup + sort
        (["../secret", "output/../../etc/passwd"], []),       # escapes -> dropped
        (["", None, "   "], []),                               # empties -> dropped
        (["output/"], []),                                     # bare output -> nothing
    ],
)
def test_normalize_allowlist_paths(raw, expected):
    assert _normalize_allowlist_paths(raw) == expected


# --------------------------------------------------------------------------- #
# Reconcile mechanics (real cp + hash, local subprocess)                      #
# --------------------------------------------------------------------------- #
@dataclass
class _Result:
    returncode: int
    stdout: str
    stderr: str


class _LocalInterface:
    async def run_command(self, command: str) -> _Result:
        p = subprocess.run(command, shell=True, capture_output=True, text=True)
        return _Result(p.returncode, p.stdout, p.stderr)


def test_reconcile_keeps_named_reverts_collateral(tmp_path: Path):
    async def scenario() -> None:
        iface = _LocalInterface()
        task_root = tmp_path / "task"
        output = task_root / "output"
        raw = output / "raw_extractions"
        raw.mkdir(parents=True)
        # Pre-repair: a big verbatim evidence file (un-named) + the defective
        # answer file the audit flagged (named).
        (raw / "verbatim.txt").write_text("EVIDENCE\n" * 10_000)
        (output / "qa_answers.json").write_text('{"eps": 1.49}\n')

        snap_dir = tmp_path / "snapshot"
        subprocess.run(f"cp -a {output} {snap_dir}", shell=True, check=True)
        subprocess.run(f"chmod -R a-w {snap_dir}", shell=True, check=True)
        src_hash = await _tree_hash(iface, str(output))
        pre = ArtifactSnapshot(
            path=str(snap_dir), sha256="a" * 64, source_sha256=src_hash,
            file_count=2, total_bytes=0,
        )

        # A repair round that fixes the named file BUT also re-runs the pipeline:
        # it clobbers the verbatim evidence to a paraphrase and drops a new file.
        (output / "qa_answers.json").write_text('{"eps": 2.61}\n')       # named fix
        (raw / "verbatim.txt").write_text("summary of evidence\n")       # collateral
        (output / "scratch.tmp").write_text("junk\n")                    # collateral add

        result = await reconcile_to_allowlist(
            interface=iface,
            task_root=str(task_root),
            snapshot=pre,
            allowlist={"output/qa_answers.json"},
        )

        assert result["mode"] == "reconciled"
        assert result["kept"] == ["qa_answers.json"]
        # Named artifact keeps the writer's repaired value...
        assert (output / "qa_answers.json").read_text() == '{"eps": 2.61}\n'
        # ...collateral is reverted to the pre-repair verbatim evidence...
        assert (raw / "verbatim.txt").read_text() == "EVIDENCE\n" * 10_000
        # ...and the collateral new file is gone.
        assert not (output / "scratch.tmp").exists()
        # Output is writable again so the next repair round can edit it.
        assert (output / "qa_answers.json").stat().st_mode & 0o200

    asyncio.run(scenario())


def test_reconcile_directory_allowlist_keeps_subtree(tmp_path: Path):
    async def scenario() -> None:
        iface = _LocalInterface()
        task_root = tmp_path / "task"
        output = task_root / "output"
        tables = output / "tables"
        tables.mkdir(parents=True)
        (tables / "a.csv").write_text("old-a\n")
        (output / "report.md").write_text("original report\n")

        snap_dir = tmp_path / "snapshot"
        subprocess.run(f"cp -a {output} {snap_dir}", shell=True, check=True)
        subprocess.run(f"chmod -R a-w {snap_dir}", shell=True, check=True)
        src_hash = await _tree_hash(iface, str(output))
        pre = ArtifactSnapshot(
            path=str(snap_dir), sha256="a" * 64, source_sha256=src_hash,
            file_count=2, total_bytes=0,
        )

        # Writer edits inside the allowlisted directory (both an edit and an add)
        # and also clobbers a file outside it.
        (tables / "a.csv").write_text("fixed-a\n")
        (tables / "b.csv").write_text("new-b\n")
        (output / "report.md").write_text("mangled report\n")

        result = await reconcile_to_allowlist(
            interface=iface,
            task_root=str(task_root),
            snapshot=pre,
            allowlist={"tables"},          # whole subtree named
        )

        assert result["mode"] == "reconciled"
        assert (tables / "a.csv").read_text() == "fixed-a\n"     # kept
        assert (tables / "b.csv").read_text() == "new-b\n"       # kept (added)
        assert (output / "report.md").read_text() == "original report\n"  # reverted

    asyncio.run(scenario())


def test_reconcile_empty_allowlist_full_revert(tmp_path: Path):
    async def scenario() -> None:
        iface = _LocalInterface()
        task_root = tmp_path / "task"
        output = task_root / "output"
        output.mkdir(parents=True)
        (output / "a.txt").write_text("original\n")

        snap_dir = tmp_path / "snapshot"
        subprocess.run(f"cp -a {output} {snap_dir}", shell=True, check=True)
        subprocess.run(f"chmod -R a-w {snap_dir}", shell=True, check=True)
        src_hash = await _tree_hash(iface, str(output))
        pre = ArtifactSnapshot(
            path=str(snap_dir), sha256="a" * 64, source_sha256=src_hash,
            file_count=1, total_bytes=0,
        )

        # Writer touched only un-named files -> whole round reverts.
        (output / "a.txt").write_text("mangled\n")
        (output / "b.txt").write_text("junk\n")

        result = await reconcile_to_allowlist(
            interface=iface,
            task_root=str(task_root),
            snapshot=pre,
            allowlist=set(),
        )

        assert result["mode"] == "full_revert"
        assert (output / "a.txt").read_text() == "original\n"
        assert not (output / "b.txt").exists()
        assert await _tree_hash(iface, str(output)) == src_hash
        # Output writable after a full revert too.
        assert (output / "a.txt").stat().st_mode & 0o200

    asyncio.run(scenario())
