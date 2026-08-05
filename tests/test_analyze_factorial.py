from __future__ import annotations

import json

from harness.run import analyze_factorial as analysis


def _write_json(path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _run(tmp_path, arm: str, name: str) -> analysis.Run:
    run_dir = tmp_path / name
    origin = run_dir / "origin_log" / "ale-claw"
    suite = {"version": 1, "tests": [{"check": "output.rows"}]}
    _write_json(origin / "verifier_suite.json", suite)
    _write_json(
        origin / "verifier_meta.json",
        {
            "protocol": "public-verifier-v14",
            "status": "ready",
            "rounds": 1,
            "repairs": 0,
            "stop_reason": "pass",
            "agent_usage": {"input_tokens": 10, "output_tokens": 2, "duration_s": 1},
        },
    )
    _write_json(
        origin / "verifier_round_0.json",
        {
            "overall": "pass",
            "duration_s": 2,
            "checks": [
                {
                    "check": "output.rows",
                    "blocking": True,
                    "validation": {"source_status": "supported"},
                    "status": "pass",
                }
            ],
        },
    )
    return analysis.Run(
        endpoint="test",
        arm=arm,
        task="domain__task",
        run_dir=run_dir,
        mtime=1,
        data={"status": "completed", "score": 1, "agent": {"id": arm}},
    )


def test_verifier_analysis_audits_shared_spec_and_rounds(tmp_path) -> None:
    old_arms = analysis.ARMS
    analysis.ARMS = analysis.DESIGNS["verifier"]
    try:
        verifier = _run(tmp_path, "ale_claw_verifier", "verifier")
        combined = _run(tmp_path, "ale_claw_prep_verifier", "combined")
        runs = {
            (verifier.arm, verifier.task): verifier,
            (combined.arm, combined.task): combined,
        }

        audit = analysis.verifier_audit_rows(runs)
        checks = analysis.verifier_check_rows(runs)
        metrics = analysis._verifier_metrics(verifier)
        scores = analysis.score_rows(runs)
        behavior = [analysis.behavior_row(run) for run in runs.values()]
        summary = analysis.summarize(runs, behavior)
    finally:
        analysis.ARMS = old_arms

    assert audit[0]["suite_sha256_equal"] is True
    assert len(checks) == 2
    assert checks[0]["check"] == "output.rows"
    assert checks[0]["status"] == "pass"
    assert metrics["verifier_last_overall"] == "pass"
    assert metrics["verifier_protocol"] == "public-verifier-v14"
    assert metrics["verifier_builder_error"] is None
    assert metrics["verifier_error"] is None
    assert metrics["verifier_check_statuses"] == '{"pass": 1}'
    assert metrics["verifier_source_statuses"] == '{"supported": 1}'
    assert metrics["verifier_executor_duration_s"] == 2
    assert summary["verifier"]["agent_input_tokens_mean"] == 10
    assert summary["verifier"]["executor_duration_s_mean"] == 2
    assert scores[0]["verifier"] == 1
    assert scores[0]["prep_verifier"] == 1
    assert "skills" not in scores[0]


def test_output_drift_reads_shrinkage_across_snapshots() -> None:
    """A writer that deletes content to pass a check must be visible in the table."""
    grew = analysis._output_drift([
        {"snapshot_manifest": [{"path": "a.csv", "bytes": 100, "lines": 5}]},
        {"snapshot_manifest": [
            {"path": "a.csv", "bytes": 140, "lines": 7},
            {"path": "notes.md", "bytes": 20, "lines": 2},
        ]},
    ])
    assert grew["output_drift_steps"] == 1
    assert grew["output_drift_bytes"] == 60
    assert grew["output_drift_files"] == 1
    assert grew["output_shrank"] is False
    assert grew["output_dropped_files"] == "[]"

    shrank = analysis._output_drift([
        {"snapshot_manifest": [
            {"path": "a.csv", "bytes": 100, "lines": 5},
            {"path": "b.csv", "bytes": 40, "lines": 3},
        ]},
        {"snapshot_manifest": [{"path": "a.csv", "bytes": 70, "lines": 3}]},
    ])
    assert shrank["output_drift_bytes"] == -70
    assert shrank["output_drift_files"] == -1
    assert shrank["output_shrank"] is True
    assert json.loads(shrank["output_dropped_files"]) == ["b.csv"]

    unchanged = analysis._output_drift([
        {"snapshot_manifest": [{"path": "a.csv", "bytes": 100, "lines": 5}]},
        {"snapshot_manifest": [{"path": "a.csv", "bytes": 100, "lines": 5}]},
    ])
    assert unchanged["output_drift_steps"] is None
    assert analysis._output_drift([])["output_shrank"] is None


def test_verifier_analysis_reports_factorial_effects(tmp_path) -> None:
    old_arms = analysis.ARMS
    analysis.ARMS = analysis.DESIGNS["verifier"]
    try:
        runs = {}
        for arm, score in (
            ("ale_claw_base", 0.0),
            ("ale_claw_prep", 1.0),
            ("ale_claw_verifier", 2.0),
            ("ale_claw_prep_verifier", 4.0),
        ):
            run = _run(tmp_path, arm, arm)
            run.data["score"] = score
            runs[(arm, run.task)] = run
        behavior = [analysis.behavior_row(run) for run in runs.values()]
        scores = analysis.score_rows(runs)
        summary = analysis.summarize(runs, behavior)
    finally:
        analysis.ARMS = old_arms

    assert scores[0]["verifier_main_effect"] == 2.5
    assert scores[0]["prep_main_effect"] == 1.5
    assert scores[0]["verifier_prep_interaction"] == 1.0
    assert summary["factorial_effects"]["verifier_main_effect"]["mean"] == 2.5
    assert summary["factorial_effects"]["prep_main_effect"]["mean"] == 1.5
    assert summary["factorial_effects"]["verifier_prep_interaction"]["mean"] == 1.0


def test_exclude_tasks_matches_exact_slug(tmp_path) -> None:
    included = _run(tmp_path, "ale_claw_base", "included")
    excluded = analysis.Run(
        endpoint=included.endpoint,
        arm=included.arm,
        task="domain__excluded",
        run_dir=included.run_dir,
        mtime=included.mtime,
        data=included.data,
    )
    runs = {
        (included.arm, included.task): included,
        (excluded.arm, excluded.task): excluded,
    }

    filtered = analysis.exclude_tasks(runs, {"domain__excluded"})

    assert list(filtered) == [(included.arm, included.task)]


def test_verifier_repair_rows_report_resolved_and_new_failures(tmp_path) -> None:
    old_arms = analysis.ARMS
    analysis.ARMS = analysis.DESIGNS["verifier"]
    try:
        run = _run(tmp_path, "ale_claw_verifier", "repair")
        root = run.run_dir / "origin_log" / "ale-claw"
        _write_json(
            root / "verifier_round_0.json",
            {
                "iteration": 0,
                "overall": "fail",
                "snapshot_sha256": "a" * 64,
                "suite_sha256": "c" * 64,
                "checks": [
                    {"check": "a", "status": "fail", "blocking": True},
                    {"check": "b", "status": "pass", "blocking": False},
                ],
            },
        )
        _write_json(
            root / "verifier_round_1.json",
            {
                "iteration": 1,
                "overall": "fail",
                "snapshot_sha256": "b" * 64,
                "suite_sha256": "c" * 64,
                "checks": [
                    {"check": "a", "status": "pass", "blocking": True},
                    {"check": "b", "status": "fail", "blocking": True},
                ],
            },
        )
        rows = analysis.verifier_repair_rows({(run.arm, run.task): run})
    finally:
        analysis.ARMS = old_arms

    assert rows[0]["snapshot_changed"] is True
    assert rows[0]["suite_sha256_equal"] is True
    assert rows[0]["resolved_failures"] == "a"
    assert rows[0]["new_failures"] == "b"
    assert rows[0]["blocking_authority_changes"] == "b:False->True"




def test_prep_writer_analysis_detects_initial_prompt_inline_exposure(tmp_path) -> None:
    run = _run(tmp_path, "ale_claw_prep", "prep-v16-inline")
    root = run.run_dir / "origin_log" / "ale-claw"
    session = root / "openclaw_sessions" / "session-1"
    report = (
        "# Task-specific prep\n\n"
        "### D1. Runtime receipt [observation; evidence high]\n"
    )
    (root / "task_prep.md").write_text(report, encoding="utf-8")
    _write_json(
        root / "task_prep_meta.json",
        {"protocol": "task-prep-v16", "status": "completed"},
    )
    session.mkdir(parents=True, exist_ok=True)
    response = {"decision": "use", "deliverables": []}
    (session / "task-prep-runs.jsonl").write_text(
        json.dumps({"status": "complete", "result_text": json.dumps(response)})
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        root / "trajectories" / "turn" / "turn_000" / "0000_api_start.json",
        {
            "messages": [{
                "role": "user",
                "content": (
                    "## Task-specific prior research\n"
                    f"{report.strip()}"
                ),
            }],
        },
    )

    writer = analysis.prep_writer_rows({(run.arm, run.task): run})

    assert writer[0]["report_read_call"] is None
    assert writer[0]["report_inlined"] is True
    assert writer[0]["report_exposed"] is True


def test_v17_report_heading_retains_title_without_evidence_suffix() -> None:
    report = (
        "# Task-specific prep\n\n"
        "### D1. Runtime receipt [observation; evidence high]\n"
    )

    assert analysis._retained_prep_claims(report) == {"Runtime receipt"}






def test_prep_findings_are_parsed_in_the_shape_prep_actually_writes(tmp_path) -> None:
    """The analyzer must track the live protocol, not a superseded one.

    The version-gated parser this replaced kept compiling after version labels
    were dropped, but every gate evaluated false, so real findings were read
    with an obsolete branch and came out blank. A measurement channel that
    fails this way reports "the component produced nothing".
    """
    run = _run(tmp_path, "ale_claw_prep", "prep")
    root = run.run_dir / "origin_log" / "ale-claw"
    (root / "task_prep.md").write_text(
        "# Task-specific prep\n\n## Findings\n\n### 1. Official ordering\n"
        "- Observation: the published order is A > B\n",
        encoding="utf-8",
    )
    _write_json(root / "task_prep_meta.json", {"protocol_digest": "prep-abc123"})
    session = root / "openclaw_sessions" / "session-1"
    session.mkdir(parents=True, exist_ok=True)
    response = {
        "environment": {"status": "ready", "summary": "runtime works"},
        "attempt": {"step": "run the pipeline", "outcome": "broke"},
        "findings": [{
            "title": "Official ordering",
            "observation": "the published order is A > B",
            "writer_action": "encode this order",
            "sources": ["https://example.org/spec#order"],
            "do_not_infer": "does not authorize other orderings",
        }],
    }
    (session / "task-prep-runs.jsonl").write_text(
        json.dumps({"status": "complete", "result_text": json.dumps(response)}) + "\n",
        encoding="utf-8",
    )
    rows = analysis.prep_finding_rows({(run.task, run.arm): run})
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "Official ordering"
    assert row["claim"] == "the published order is A > B"
    assert row["writer_action"] == "encode this order"
    assert row["local_source"] == "https://example.org/spec#order"
    # a finding whose title appears in the staged report counts as retained
    assert row["retained"] is True
    assert row["filter_reason"] == ""
