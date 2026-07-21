"""Writer-triggered pre-submission verification (the `verify` tool)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ale_run.agents.ale_claw import verifier_precheck
from ale_run.agents.ale_claw.config import AleClawConfig
from ale_run.agents.ale_claw.verifier import (
    ArtifactSnapshot,
    FrozenTestSuite,
    VerificationResult,
    build_feedback_prompt,
)
from ale_run.agents.ale_claw.verifier_precheck import WriterVerifyTool
from ale_run.agents.ale_claw.verifier_runtime import snapshot_output


def _suite() -> FrozenTestSuite:
    return FrozenTestSuite(
        path="",
        sha256="a" * 64,
        manifest={"tests": [{"check": "schema.columns"}], "unverifiable": []},
    )


def _hard_fail_result() -> VerificationResult:
    return VerificationResult(
        overall="fail",
        suite_sha256="a" * 64,
        snapshot_sha256="b" * 64,
        checks=[{
            "check": "schema.columns",
            "sources": [{
                "path": "input/schema.json",
                "locator": "/required_columns",
                "quote": '["id", "score", "status"]',
                "sha256": "c" * 64,
            }],
            "requirement": "required columns",
            "interpretation": "final header includes all three names",
            "command": ["python3", "schema.columns.py"],
            "expected": "three required columns",
            "execution_mode": "public_recompute",
            "execution_reason": "the public schema is directly parseable",
            "requested_blocking": True,
            "blocking": True,
            "status": "fail",
            "observed": "status is missing",
            "evidence": "parsed id,score",
            "execution": {"reproducible": True, "runs": [{}, {}]},
        }],
    )


def _tool(tmp_path: Path, *, max_calls: int = 2) -> WriterVerifyTool:
    return WriterVerifyTool(
        interface=object(),
        os_type="linux",
        task_root="/task/root",
        task_prompt="PUBLIC TASK",
        max_calls=max_calls,
        work_dir=tmp_path,
    )


def _patch_runtime(monkeypatch, *, result: VerificationResult, staged: list):
    async def fake_stage_test_suite(*, interface, task_root, manifest):
        staged.append(manifest)
        return FrozenTestSuite(path="/tmp/suite", sha256="a" * 64, manifest=manifest)

    async def fake_snapshot_output(*, interface, task_root, os_type, iteration):
        return ArtifactSnapshot(
            path=f"/tmp/snapshot-{iteration}",
            sha256="d" * 64,
            source_sha256="e" * 64,
            file_count=3,
        )

    async def fake_execute_test_suite(**kwargs):
        return result

    async def fake_stage_verifier_report(interface, *, task_root, filename, report):
        return f"{task_root}/verifier/{filename}"

    async def fake_snapshot_manifest(interface, snapshot):
        return [{"path": "submission.csv", "bytes": 120, "lines": 4}]

    monkeypatch.setattr(
        verifier_precheck, "snapshot_manifest", fake_snapshot_manifest
    )

    monkeypatch.setattr(verifier_precheck, "stage_test_suite", fake_stage_test_suite)
    monkeypatch.setattr(verifier_precheck, "snapshot_output", fake_snapshot_output)
    monkeypatch.setattr(verifier_precheck, "execute_test_suite", fake_execute_test_suite)
    monkeypatch.setattr(
        verifier_precheck, "stage_verifier_report", fake_stage_verifier_report
    )


def test_writer_checks_config_bounds() -> None:
    assert AleClawConfig().verifier_writer_checks == 2
    assert AleClawConfig(verifier_writer_checks=0).verifier_writer_checks == 0
    with pytest.raises(ValueError, match="verifier_writer_checks"):
        AleClawConfig(verifier_writer_checks=9)
    with pytest.raises(ValueError, match="verifier_writer_checks"):
        AleClawConfig(verifier_writer_checks=-1)


def test_verify_is_unavailable_until_the_frozen_suite_is_bound(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    first = tool.call({})
    assert first["success"] is False
    assert "still being built" in first["error"]

    tool.mark_unavailable("builder error: no public oracle")
    second = tool.call({})
    assert second["success"] is False
    assert "builder error: no public oracle" in second["error"]
    assert tool.calls_used == 0


def test_verify_runs_the_frozen_suite_and_reports_pre_submission(
    tmp_path: Path, monkeypatch
) -> None:
    staged: list = []
    _patch_runtime(monkeypatch, result=_hard_fail_result(), staged=staged)
    tool = _tool(tmp_path)
    tool.bind_suite(_suite())

    outcome = tool.call({})

    assert outcome["success"] is True
    text = outcome["output"]
    assert "PRE-SUBMISSION VERIFICATION RUN 1/2" in text
    assert "INPUT DETAIL TO RECHECK" in text
    assert "pre-submission measurement" in text
    assert "Do not modify output immediately" not in text
    assert "Complete report: /task/root/verifier/writer_check_1.json" in text
    assert tool.calls_used == 1
    assert tool.records[0]["iteration"] == "writer1"
    assert tool.records[0]["phase"] == "pre_submission"

    record_path = tmp_path / "verifier_writer_check_1.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["overall"] == "fail"
    assert record["categories"]["hard_mismatches"] == ["schema.columns"]
    assert record["snapshot_manifest"] == [
        {"path": "submission.csv", "bytes": 120, "lines": 4}
    ]


def test_verify_stages_once_and_enforces_the_call_budget(
    tmp_path: Path, monkeypatch
) -> None:
    staged: list = []
    _patch_runtime(monkeypatch, result=_hard_fail_result(), staged=staged)
    tool = _tool(tmp_path, max_calls=2)
    tool.bind_suite(_suite())

    assert tool.call({})["success"] is True
    assert tool.call({})["success"] is True
    assert len(staged) == 1

    exhausted = tool.call({})
    assert exhausted["success"] is False
    assert "no verification runs remain" in exhausted["error"]
    assert tool.calls_used == 2
    assert (tmp_path / "verifier_writer_check_2.json").is_file()


def test_verify_call_never_raises(tmp_path: Path, monkeypatch) -> None:
    async def broken_stage_test_suite(**kwargs):
        raise RuntimeError("staging exploded")

    monkeypatch.setattr(
        verifier_precheck, "stage_test_suite", broken_stage_test_suite
    )
    tool = _tool(tmp_path)
    tool.bind_suite(_suite())

    outcome = tool.call({})
    assert outcome["success"] is False
    assert "staging exploded" in outcome["error"]
    assert tool.calls_used == 0


def test_pre_submission_feedback_swaps_only_the_instruction() -> None:
    result = _hard_fail_result()
    post = build_feedback_prompt(result, report_path="/r.json")
    pre = build_feedback_prompt(result, report_path="/r.json", pre_submission=True)

    assert "Do not modify output immediately" in post
    assert "pre-submission measurement" not in post
    assert "pre-submission measurement" in pre
    assert "Do not modify output immediately" not in pre
    for text in (post, pre):
        assert "INPUT DETAIL TO RECHECK" in text
        assert "VERIFIER_DISPUTE" in text
    assert "an all-pass result does not mean the task is complete" in pre


def test_snapshot_labels_are_validated() -> None:
    with pytest.raises(ValueError, match="snapshot iteration label"):
        asyncio.run(snapshot_output(
            interface=object(),
            task_root="/task/root",
            os_type="linux",
            iteration="../escape",
        ))


