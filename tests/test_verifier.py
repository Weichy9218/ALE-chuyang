from __future__ import annotations

import asyncio
import base64
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from ale_run.agents.ale_claw.verifier import (
    AgentUsage,
    MAX_SOURCE_QUOTE_CHARS,
    VerificationResult,
    build_feedback_prompt,
    build_suite_system_prompt,
    build_test_suite,
    finalize_suite,
    lint_candidate_suite,
    lint_frozen_suite,
    locate_suite_sources,
    parse_disputes,
)
from ale_run.agents.ale_claw.verifier_runtime import (
    _overall,
    _tree_hash,
    execute_test_suite,
    preflight_suite,
    snapshot_output,
    stage_test_suite,
)
from ale_run.agents.ale_claw.verifier_sandbox import _CREATE_RULESET, _CREATE_VERSION, _syscall


TASK_PROMPT = (
    "Write output/submission.csv. Output schema: Columns: id, score, status.\n"
    "Produce an accurate future forecast."
)

CHECKER = """import csv
import json
import os
from pathlib import Path

path = Path(os.environ['VERIFIER_OUTPUT']) / 'submission.csv'
if path.is_file():
    with path.open(newline='', encoding='utf-8') as handle:
        columns = next(csv.reader(handle), [])
else:
    columns = []
required = ['id', 'score', 'status']
missing = [name for name in required if name not in columns]
status = 'fail' if missing else 'pass'
print(json.dumps({
    'status': status,
    'observed': 'missing: ' + ','.join(missing) if missing else 'all required columns present',
    'evidence': 'parsed header: ' + ','.join(columns),
}, sort_keys=True))
"""


def _b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def _candidate(script: str = CHECKER) -> dict:
    return {
        "reason": "the public output schema is executable",
        "tests": [{
            "check": "schema.required_columns",
            "sources": [{
                "path": "task_prompt",
                "locator": "lines:1-1",
                "quote": "Columns: id, score, status",
            }],
            "requirement": "the final CSV contains all required columns",
            "interpretation": "submission.csv must contain id, score, and status",
            "expected": "header contains id, score, status",
            "execution_mode": "public_recompute",
            "execution_reason": "the public CSV schema can be checked deterministically",
            "script": script,
            "fixtures": {
                "valid": [{
                    "path": "submission.csv",
                    "encoding": "utf8",
                    "content": "id,score,status\n",
                }],
                "invalid": [{
                    "path": "submission.csv",
                    "encoding": "utf8",
                    "content": "id,score\n",
                }],
            },
            "blocking": True,
        }],
        "unverifiable": [{
            "check": "quality.future_accuracy",
            "sources": [{
                "path": "task_prompt",
                "locator": "lines:2-2",
                "quote": "Produce an accurate future forecast.",
            }],
            "expected": "accurate future forecast",
            "reason": "future truth is unavailable before submission",
        }],
    }


def _preflight(candidate: dict, reproducible: bool = True) -> list[dict]:
    return [{
        "check": test["check"],
        "environment_healthy": True,
        "checker_reproducible": reproducible,
        "valid_status": "pass" if reproducible else "error",
        "invalid_status": "fail" if reproducible else "error",
        "environment": {"healthy": True, "evidence": "isolated probe passed"},
        "evidence": "valid passed twice; invalid failed twice",
    } for test in candidate["tests"]]


@dataclass
class _CommandResult:
    stdout: str
    stderr: str
    returncode: int


class _ShellInterface:
    async def run_command(self, command: str) -> _CommandResult:
        result = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            check=False,
        )
        return _CommandResult(result.stdout, result.stderr, result.returncode)


def _locate(candidate: dict, task_root: Path) -> dict:
    return asyncio.run(locate_suite_sources(
        interface=_ShellInterface(),
        task_root=str(task_root),
        task_prompt=TASK_PROMPT,
        candidate=lint_candidate_suite(candidate),
    ))


def _require_landlock() -> None:
    try:
        _syscall(_CREATE_RULESET, 0, 0, _CREATE_VERSION)
    except OSError:
        pytest.skip("the local kernel does not expose Landlock; pgl does")


def _frozen(candidate: dict, task_root: Path) -> dict:
    located = _locate(candidate, task_root)
    return lint_frozen_suite(finalize_suite(located, _preflight(located)))


def test_candidate_schema_hashes_scripts_and_fixtures() -> None:
    candidate = lint_candidate_suite(_candidate())

    test = candidate["tests"][0]
    assert len(test["script_sha256"]) == 64
    assert test["script_path"] == "checks/schema.required_columns.py"
    assert test["command"] == ["python3", "schema.required_columns.py"]
    assert test["fixtures"]["valid"][0]["content"] == "id,score,status\n"
    assert test["sources"][0]["path"] == "task_prompt"


def test_identical_fixtures_drop_only_that_test() -> None:
    value = _candidate()
    value["tests"][0]["fixtures"]["invalid"] = value["tests"][0]["fixtures"]["valid"]

    candidate = lint_candidate_suite(value)

    assert candidate["tests"] == []
    assert candidate["unverifiable"][0]["check"] == "quality.future_accuracy"
    assert any("fixtures are identical" in reason for reason in candidate["dropped"])


def test_lint_quarantines_bad_tests_and_keeps_good_ones() -> None:
    value = _candidate()
    broken = json.loads(json.dumps(value["tests"][0]))
    broken["check"] = "schema.broken_twin"
    broken["expected"] = ""
    value["tests"].append(broken)

    candidate = lint_candidate_suite(value)

    assert [test["check"] for test in candidate["tests"]] == [
        "schema.required_columns"
    ]
    assert any("schema.broken_twin" in reason for reason in candidate["dropped"])


def test_missing_envelope_fields_are_defaulted_not_fatal() -> None:
    """A packaging slip must not cost the writer the whole verify tool.

    The v18 six-task run lost the SEC suite to a builder response whose top
    level lacked these keys, while its tests were fine.
    """
    value = _candidate()
    value.pop("reason")
    value.pop("unverifiable")

    candidate = lint_candidate_suite(value)

    assert [test["check"] for test in candidate["tests"]] == [
        "schema.required_columns"
    ]
    assert candidate["unverifiable"] == []
    assert candidate["reason"]
    assert any("missing reason" in note for note in candidate["dropped"])


def test_suite_with_no_usable_item_still_fails() -> None:
    value = _candidate()
    value["tests"][0]["expected"] = ""
    value["unverifiable"] = []

    with pytest.raises(ValueError, match="no usable test"):
        lint_candidate_suite(value)


def test_binary_fixtures_use_explicit_base64() -> None:
    value = _candidate()
    value["tests"][0]["fixtures"] = {
        "valid": [{
            "path": "submission.csv",
            "encoding": "base64",
            "content": _b64("id,score,status\n"),
        }],
        "invalid": [{
            "path": "submission.csv",
            "encoding": "base64",
            "content": _b64("id,score\n"),
        }],
    }

    candidate = lint_candidate_suite(value)

    assert candidate["tests"][0]["fixtures"]["valid"][0]["content"] == _b64(
        "id,score,status\n"
    )
    value["tests"][0]["fixtures"]["valid"][0]["content"] = "not base64"
    relinted = lint_candidate_suite(value)
    assert relinted["tests"] == []
    assert any("invalid base64" in reason for reason in relinted["dropped"])


def test_checker_result_preserves_structured_observation_and_evidence() -> None:
    from ale_run.agents.ale_claw.verifier_runtime import _normalize_script_result

    value = {
        "status": "fail",
        "observed": {"missing": ["status"]},
        "evidence": ["submission.csv#header"],
    }

    result = _normalize_script_result({
        "returncode": 0,
        "stdout": json.dumps(value),
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
    })

    assert result["observed"] == {"missing": ["status"]}
    assert result["evidence"] == ["submission.csv#header"]


def test_overall_reports_coverage_never_a_verdict() -> None:
    executed = {"execution": {"reproducible": True, "runs": [{}, {}]}}
    assert _overall([
        {"requested_blocking": True, "blocking": False, "status": "fail", **executed},
        {"requested_blocking": True, "blocking": False, "status": "error",
         "execution": None},
    ]) == "measured"
    assert _overall([
        {"requested_blocking": True, "blocking": False, "status": "error",
         "execution": None},
    ]) == "error"
    assert _overall([
        {"requested_blocking": False, "blocking": False, "status": "unverifiable",
         "execution": None},
    ]) == "unverifiable"


def test_source_is_located_and_hashed_before_freeze(tmp_path: Path) -> None:
    located = _locate(_candidate(), tmp_path)

    source = located["tests"][0]["sources"][0]
    assert source["located"] is True
    assert len(source["sha256"]) == 64
    assert located["unverifiable"][0]["sources"][0]["located"] is True


def test_multiple_sources_include_whole_file_hashes(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    data = input_dir / "profiles.parquet"
    data.write_bytes(b"opaque-public-data")
    value = _candidate()
    value["tests"][0]["sources"].append({
        "path": "input/profiles.parquet",
        "locator": "file",
        "quote": "",
    })

    located = _locate(value, tmp_path)

    assert len(located["tests"][0]["sources"]) == 2
    assert located["tests"][0]["sources"][1]["located"] is True
    assert len(located["tests"][0]["sources"][1]["sha256"]) == 64


def test_json_pointer_compares_structured_quotes(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "schema.json").write_text(
        '{"required": ["id", "score", "status"]}\n', encoding="utf-8"
    )
    value = _candidate()
    value["tests"][0]["sources"] = [{
        "path": "input/schema.json",
        "locator": "/required",
        "quote": '[\n  "id",\n  "score",\n  "status"\n]',
    }]

    located = _locate(value, tmp_path)

    assert located["tests"][0]["sources"][0]["located"] is True


def test_duplicate_sources_drop_the_test() -> None:
    value = _candidate()
    value["tests"][0]["sources"].append(value["tests"][0]["sources"][0].copy())

    candidate = lint_candidate_suite(value)

    assert candidate["tests"] == []
    assert any("duplicate sources" in reason for reason in candidate["dropped"])


def test_unique_quote_relocates_a_wrong_line_locator(tmp_path: Path) -> None:
    """The quote is the fact; a uniquely-wrong line number is corrected."""
    value = _candidate()
    value["tests"][0]["sources"][0]["locator"] = "lines:2-2"

    located = _locate(value, tmp_path)

    source = located["tests"][0]["sources"][0]
    assert source["located"] is True
    assert source["locator"] == "lines:1-1"
    assert "corrected from lines:2-2" in source["locate_evidence"]


def test_out_of_range_locator_relocates_when_quote_is_unique(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "spec.md").write_text(
        "# Spec\nEvery producer appears once.\n", encoding="utf-8"
    )
    value = _candidate()
    value["tests"][0]["sources"] = [{
        "path": "input/spec.md",
        "locator": "lines:90-90",
        "quote": "Every producer appears once.",
    }]

    located = _locate(value, tmp_path)

    source = located["tests"][0]["sources"][0]
    assert source["located"] is True
    assert source["locator"] == "lines:2-2"


def test_repeated_quote_does_not_relocate(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "spec.md").write_text(
        "rule: keep ids\nrule: keep ids\n", encoding="utf-8"
    )
    value = _candidate()
    value["tests"][0]["sources"] = [{
        "path": "input/spec.md",
        "locator": "lines:90-90",
        "quote": "rule: keep ids",
    }]

    located = _locate(value, tmp_path)

    assert located["tests"][0]["sources"][0]["located"] is False


def test_source_quote_has_a_bounded_audit_size() -> None:
    value = _candidate()
    value["tests"][0]["sources"][0]["quote"] = "x" * (MAX_SOURCE_QUOTE_CHARS + 1)

    candidate = lint_candidate_suite(value)

    assert candidate["tests"] == []
    assert any(
        str(MAX_SOURCE_QUOTE_CHARS) in reason for reason in candidate["dropped"]
    )


def test_task_prompt_citation_resolves_to_public_input_file(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "task_prompt.md").write_text(
        "File-only public requirement.\n", encoding="utf-8"
    )
    value = _candidate()
    value["tests"][0]["sources"] = [{
        "path": "task_prompt",
        "locator": "lines:1-1",
        "quote": "File-only public requirement.",
    }]

    located = _locate(value, tmp_path)

    source = located["tests"][0]["sources"][0]
    assert source["path"] == "input/task_prompt.md"
    assert source["located"] is True


def test_zero_authority_never_grants_blocking() -> None:
    candidate = lint_candidate_suite(_candidate())
    for collection in (candidate["tests"], candidate["unverifiable"]):
        for item in collection:
            for source in item["sources"]:
                source.update({
                    "sha256": "a" * 64,
                    "located": True,
                    "locate_evidence": "located",
                })

    frozen = lint_frozen_suite(finalize_suite(candidate, _preflight(candidate)))

    test = frozen["tests"][0]
    # The builder asked for hard authority; the freeze records the request and
    # refuses the grant: every check is advisory.
    assert test["requested_blocking"] is True
    assert test["blocking"] is False
    assert test["validation"]["sources_located"] is True
    assert test["validation"]["checker_reproducible"] is True


def test_freeze_records_unlocated_sources_and_flaky_checkers() -> None:
    candidate = lint_candidate_suite(_candidate())
    candidate["tests"][0]["sources"].extend([
        {
            "path": "input/profiles.parquet",
            "locator": "file",
            "quote": "",
            "sha256": "b" * 64,
            "located": False,
            "locate_evidence": "file missing",
        },
    ])
    for source in candidate["tests"][0]["sources"][:1]:
        source.update({
            "sha256": "a" * 64,
            "located": True,
            "locate_evidence": "located",
        })

    unlocated = finalize_suite(candidate, _preflight(candidate))
    flaky = finalize_suite(candidate, _preflight(candidate, False))

    validation = lint_frozen_suite(unlocated)["tests"][0]["validation"]
    assert validation["sources_located"] is False
    assert lint_frozen_suite(flaky)["tests"][0]["validation"][
        "checker_reproducible"
    ] is False


def test_fixture_preflight_and_full_suite_rerun(tmp_path: Path) -> None:
    _require_landlock()
    (tmp_path / "input").mkdir()
    output = tmp_path / "output"
    output.mkdir()
    (output / "submission.csv").write_text("id,score,status\n", encoding="utf-8")
    located = _locate(_candidate(), tmp_path)
    candidate_suite = asyncio.run(stage_test_suite(
        interface=_ShellInterface(), task_root=str(tmp_path), manifest=located,
    ))
    audit_manifest = json.loads(
        (Path(candidate_suite.path) / "manifest.json").read_text()
    )
    assert "script" not in audit_manifest["tests"][0]
    assert audit_manifest["tests"][0]["fixtures"]["valid"][0] == {
        "path": "fixtures/schema.required_columns/valid/submission.csv",
        "encoding": "utf8",
    }
    preflight = asyncio.run(preflight_suite(
        interface=_ShellInterface(), task_root=str(tmp_path), suite=candidate_suite,
    ))
    assert preflight[0]["environment_healthy"] is True
    assert preflight[0]["checker_reproducible"] is True

    manifest = lint_frozen_suite(finalize_suite(located, preflight))
    suite = asyncio.run(stage_test_suite(
        interface=_ShellInterface(), task_root=str(tmp_path), manifest=manifest,
    ))
    assert not (Path(suite.path) / "manifest.json").exists()
    first_snapshot = asyncio.run(snapshot_output(
        interface=_ShellInterface(), task_root=str(tmp_path), os_type="linux", iteration=0,
    ))
    first = asyncio.run(execute_test_suite(
        interface=_ShellInterface(),
        task_root=str(tmp_path),
        task_prompt=TASK_PROMPT,
        suite=suite,
        snapshot=first_snapshot,
    ))
    assert first.overall == "measured"
    assert [check["status"] for check in first.checks] == ["pass", "unverifiable"]

    (output / "submission.csv").write_text("id,score\n", encoding="utf-8")
    second_snapshot = asyncio.run(snapshot_output(
        interface=_ShellInterface(), task_root=str(tmp_path), os_type="linux", iteration=1,
    ))
    second = asyncio.run(execute_test_suite(
        interface=_ShellInterface(),
        task_root=str(tmp_path),
        task_prompt=TASK_PROMPT,
        suite=suite,
        snapshot=second_snapshot,
    ))
    assert second.overall == "measured"
    assert [item["check"] for item in second.review_items] == [
        "schema.required_columns"
    ]
    assert second.failure_signature == ()
    assert "analysis" not in second.checks[0]
    assert second.checks[0]["execution"]["reproducible"] is True
    assert len(second.checks[0]["execution"]["runs"]) == 2
    assert second.checks[0]["execution"]["runs"][0]["returncode"] == 0
    assert second.coverage == {
        "covered": ["schema.required_columns"],
        "uncovered": ["quality.future_accuracy"],
    }

def test_observed_difference_surfaces_as_advisory_review_item(tmp_path: Path) -> None:
    """A located check executes; its difference is advisory, never blocking."""
    _require_landlock()
    (tmp_path / "input").mkdir()
    output = tmp_path / "output"
    output.mkdir()
    (output / "submission.csv").write_text("id,score\n", encoding="utf-8")
    manifest = _frozen(_candidate(), tmp_path)
    assert manifest["tests"][0]["blocking"] is False
    suite = asyncio.run(stage_test_suite(
        interface=_ShellInterface(), task_root=str(tmp_path), manifest=manifest,
    ))
    snapshot = asyncio.run(snapshot_output(
        interface=_ShellInterface(), task_root=str(tmp_path), os_type="linux", iteration=0,
    ))

    result = asyncio.run(execute_test_suite(
        interface=_ShellInterface(),
        task_root=str(tmp_path),
        task_prompt=TASK_PROMPT,
        suite=suite,
        snapshot=snapshot,
    ))

    check = result.checks[0]
    assert check["status"] == "fail"
    assert check["blocking"] is False
    assert check["execution"] is not None
    assert [item["check"] for item in result.review_items] == [
        "schema.required_columns"
    ]
    assert result.needs_review is True
    assert result.hard_mismatches == []
    assert result.overall == "measured"

    feedback = build_feedback_prompt(result, report_path="/task/verifier/round_0.json")
    assert "ADVISORY REVIEW ITEM" in feedback
    assert "Authority: advisory" in feedback


def test_unlocated_source_check_stays_unrun(tmp_path: Path) -> None:
    (tmp_path / "input").mkdir()
    output = tmp_path / "output"
    output.mkdir()
    (output / "submission.csv").write_text("id,score\n", encoding="utf-8")
    value = _candidate()
    value["tests"][0]["sources"][0]["quote"] = "this text is nowhere in the prompt"
    manifest = _frozen(value, tmp_path)
    assert manifest["tests"][0]["validation"]["sources_located"] is False
    suite = asyncio.run(stage_test_suite(
        interface=_ShellInterface(), task_root=str(tmp_path), manifest=manifest,
    ))
    snapshot = asyncio.run(snapshot_output(
        interface=_ShellInterface(), task_root=str(tmp_path), os_type="linux", iteration=0,
    ))

    result = asyncio.run(execute_test_suite(
        interface=_ShellInterface(),
        task_root=str(tmp_path),
        task_prompt=TASK_PROMPT,
        suite=suite,
        snapshot=snapshot,
    ))

    assert result.checks[0]["status"] == "unverifiable"
    assert result.checks[0]["execution"] is None
    assert result.needs_review is False


def test_source_change_after_freeze_is_executor_error(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source_file = input_dir / "schema.txt"
    source_file.write_text("anchor\nrequired status\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    (output / "submission.csv").write_text("id,score,status\n", encoding="utf-8")
    value = _candidate()
    value["tests"][0]["sources"] = [{
        "path": "input/schema.txt",
        "locator": "lines:1-2",
        "quote": "required status",
    }]
    manifest = _frozen(value, tmp_path)
    suite = asyncio.run(stage_test_suite(
        interface=_ShellInterface(), task_root=str(tmp_path), manifest=manifest,
    ))
    snapshot = asyncio.run(snapshot_output(
        interface=_ShellInterface(), task_root=str(tmp_path), os_type="linux", iteration=0,
    ))
    source_file.write_text("anchor\nchanged requirement\n", encoding="utf-8")

    result = asyncio.run(execute_test_suite(
        interface=_ShellInterface(),
        task_root=str(tmp_path),
        task_prompt=TASK_PROMPT,
        suite=suite,
        snapshot=snapshot,
    ))
    assert result.overall == "error"
    assert "public source changed" in result.error


def test_snapshot_omits_symlinks_without_dereferencing(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("outside\n", encoding="utf-8")
    (output / "outside-link").symlink_to(target)

    snapshot = asyncio.run(snapshot_output(
        interface=_ShellInterface(), task_root=str(tmp_path), os_type="linux", iteration=0,
    ))

    assert snapshot.file_count == 0
    assert asyncio.run(_tree_hash(_ShellInterface(), snapshot.path)) == snapshot.sha256
    assert Path(snapshot.rejected_symlinks_path).read_text() == f"outside-link -> {target}\n"


def test_process_sandbox_blocks_unlisted_files_and_network(tmp_path: Path) -> None:
    _require_landlock()
    from ale_run.agents.ale_claw import verifier_sandbox

    for name in ("input", "software", "output", "checks", "scratch"):
        (tmp_path / name).mkdir()
    (tmp_path / "output" / "allowed.txt").write_text("ok", encoding="utf-8")
    forbidden = tmp_path / "forbidden.txt"
    forbidden.write_text("secret", encoding="utf-8")
    probe = tmp_path / "checks" / "probe.py"
    probe.write_text(
        "import os, pathlib, socket\n"
        "assert (pathlib.Path(os.environ['VERIFIER_OUTPUT']) / 'allowed.txt').read_text() == 'ok'\n"
        f"try:\n    pathlib.Path({str(forbidden)!r}).read_text()\n"
        "except PermissionError:\n    pass\nelse:\n    raise AssertionError('filesystem escape')\n"
        "try:\n    socket.socket()\n"
        "except PermissionError:\n    pass\nelse:\n    raise AssertionError('network escape')\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "python3", str(Path(verifier_sandbox.__file__)),
            *(str(tmp_path / name) for name in ("input", "software", "output", "checks", "scratch")),
            "--", "python3", "probe.py",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_process_sandbox_can_execute_pgl_uv(tmp_path: Path) -> None:
    _require_landlock()
    uv = Path("/home/user/.local/bin/uv")
    if not uv.is_file():
        pytest.skip("uv is installed at this path in the pgl task image")
    from ale_run.agents.ale_claw import verifier_sandbox

    for name in ("input", "software", "output", "checks", "scratch"):
        (tmp_path / name).mkdir()
    result = subprocess.run(
        [
            "python3", str(Path(verifier_sandbox.__file__)),
            *(str(tmp_path / name) for name in ("input", "software", "output", "checks", "scratch")),
            "--", "uv", "--version",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("uv ")


def test_feedback_is_source_first_and_supports_natural_disputes() -> None:
    result = VerificationResult(
        overall="fail",
        suite_sha256="a" * 64,
        snapshot_sha256="b" * 64,
        checks=[{
            "check": "schema.required_columns",
            "sources": [{
                "path": "input/schema.json",
                "locator": "/required_columns",
                "quote": '["id", "score", "status"]',
                "sha256": "c" * 64,
            }],
            "requirement": "required columns",
            "interpretation": "final header includes all three names",
            "command": ["python3", "required_columns.py"],
            "expected": "three required columns",
            "execution_mode": "public_recompute",
            "execution_reason": "the public schema is directly parseable",
            "requested_blocking": True,
            "blocking": True,
            "status": "fail",
            "observed": "status is missing",
            "evidence": "parsed id,score",
            "execution": None,
        }],
    )

    feedback = build_feedback_prompt(result, report_path="/task/verifier/round_0.json")
    assert feedback.index("INPUT DETAIL TO RECHECK") < feedback.index("OBSERVED FAILURE")
    assert "Source 1 SHA-256" in feedback
    assert "repair_hint" not in feedback
    assert "hypothesis" not in feedback
    assert "Do not modify output immediately" in feedback
    assert "Complete report: /task/verifier/round_0.json" in feedback
    assert parse_disputes(
        "VERIFIER_DISPUTE schema.required_columns: prompt says otherwise",
        {"schema.required_columns"},
    ) == {"schema.required_columns"}


def _advisory_check(**overrides):
    check = {
        "check": "topology.producers",
        "sources": [{
            "path": "input/spec.md",
            "locator": "lines:1-4",
            "quote": "every producer appears once",
            "sha256": "c" * 64,
        }],
        "requirement": "each producer appears exactly once",
        "interpretation": "count producers in the diagram",
        "command": ["python3", "topology.producers.py"],
        "expected": "no duplicate producers",
        "execution_mode": "public_recompute",
        "execution_reason": "the diagram is public",
        "validation": {"sources_located": True, "checker_reproducible": True,
                       "environment_healthy": True},
        "requested_blocking": True,
        "blocking": False,
        "status": "fail",
        "observed": "producer P3 appears twice",
        "evidence": "parsed diagram nodes",
        "execution": {"reproducible": True, "runs": [{}, {}]},
    }
    check.update(overrides)
    return check


def test_advisory_observation_reaches_writer_and_drives_review() -> None:
    result = VerificationResult(
        overall="pass",
        suite_sha256="a" * 64,
        snapshot_sha256="b" * 64,
        checks=[_advisory_check()],
    )

    assert result.needs_review is True
    assert [c["check"] for c in result.review_items] == ["topology.producers"]
    assert result.hard_mismatches == []

    feedback = build_feedback_prompt(result, report_path="/task/verifier/round_0.json")
    assert "ADVISORY REVIEW ITEM" in feedback
    assert "Authority: advisory" in feedback
    assert parse_disputes(
        "VERIFIER_DISPUTE topology.producers: partial checker",
        {"topology.producers"},
    ) == {"topology.producers"}


def test_advisory_feedback_flags_simulation_evidence() -> None:
    simulated = _advisory_check(execution_mode="simulation")
    result = VerificationResult(
        overall="measured",
        suite_sha256="a" * 64,
        snapshot_sha256="b" * 64,
        checks=[simulated],
    )

    feedback = build_feedback_prompt(result, report_path="/r.json")

    assert "comes from a simulation" in feedback
    assert "the verifier holds no authority over your output" in feedback


def test_execution_errors_and_coverage_gaps_do_not_force_review() -> None:
    result = VerificationResult(
        overall="error",
        suite_sha256="a" * 64,
        snapshot_sha256="b" * 64,
        checks=[
            _advisory_check(check="broken.checker", status="error", blocking=False,
                            execution=None, observed="checker crashed"),
            _advisory_check(check="future.quality", status="unverifiable",
                            blocking=False, execution=None,
                            observed="no public oracle"),
        ],
    )

    assert result.needs_review is False
    assert [c["check"] for c in result.execution_errors] == ["broken.checker"]
    assert [c["check"] for c in result.coverage_gaps] == ["future.quality"]
    categories = result.metadata()["categories"]
    assert categories["execution_errors"] == ["broken.checker"]
    assert categories["coverage_gaps"] == ["future.quality"]
    assert result.metadata()["needs_review"] is False


def test_builder_prompt_anchors_checks_in_the_contract() -> None:
    builder = build_suite_system_prompt("/task", "seed")

    assert "Yes, No, Unknown" in builder
    assert "maps to that label" in builder
    assert "missing facts" in builder.lower()
    assert "exactly pass, fail, or unverifiable" in builder
    # Contract-first: exact stated names, checks named after obligations,
    # breadth of contract coverage over depth on one item.
    assert "deliverable contract" in builder
    assert "letter-for-letter" in builder
    assert "contract.submission_csv.required_columns" in builder
    assert "advisory measurement" in builder


def test_builder_alone_produces_one_frozen_suite(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    async def fresh(**kwargs):
        calls.append(kwargs["label"])
        return json.dumps(_candidate()), AgentUsage(llm_turns=1)

    (tmp_path / "input").mkdir()
    monkeypatch.setattr("ale_run.agents.ale_claw.verifier._run_fresh_agent", fresh)
    kwargs = {
        "interface": _ShellInterface(),
        "os_type": "linux",
        "task_id": "domain/task/base",
        "task_root": str(tmp_path),
        "task_prompt": TASK_PROMPT,
        "model": "openai/test",
        "summary_model": "openai/test",
        "tools": [],
        "registry": None,
        "parent_session_dir": tmp_path,
        "max_steps": 3,
    }

    result = asyncio.run(build_test_suite(**kwargs))

    assert result.status == "ready"
    assert result.suite.sha256 == result.suite.manifest["suite_sha256"]
    assert result.suite.path == ""
    # No auditor session: the freeze is mechanical under zero authority.
    assert calls == ["verifier-builder"]


def test_unlocatable_source_gets_one_mechanical_repair_round(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []

    async def fresh(**kwargs):
        calls.append(kwargs["label"])
        if kwargs["label"] == "verifier-builder":
            broken = _candidate()
            broken["tests"][0]["sources"][0]["quote"] = "Columns: id, score, WRONG"
            return json.dumps(broken), AgentUsage(llm_turns=1)
        assert kwargs["label"] == "verifier-builder-locate-repair"
        assert "LOCATE FAILURES" in kwargs["task"]
        assert "Columns: id, score, WRONG" in kwargs["task"]
        return json.dumps(_candidate()), AgentUsage(llm_turns=1)

    (tmp_path / "input").mkdir()
    monkeypatch.setattr("ale_run.agents.ale_claw.verifier._run_fresh_agent", fresh)

    result = asyncio.run(build_test_suite(
        interface=_ShellInterface(),
        os_type="linux",
        task_id="domain/task/base",
        task_root=str(tmp_path),
        task_prompt=TASK_PROMPT,
        model="openai/test",
        summary_model="openai/test",
        tools=[],
        registry=None,
        parent_session_dir=tmp_path,
        max_steps=3,
    ))

    assert result.status == "ready"
    assert calls == ["verifier-builder", "verifier-builder-locate-repair"]
    source = result.suite.manifest["tests"][0]["sources"][0]
    assert source["located"] is True
    assert result.suite.manifest["tests"][0]["requested_blocking"] is True
    assert result.suite.manifest["tests"][0]["blocking"] is False
