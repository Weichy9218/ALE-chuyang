from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from agent.tools.base import BaseTool

from ale_run.agents.ale_claw.config import AleClawConfig
from ale_run.agents.ale_claw.deployer import (
    _stage_prep_bundle,
)
from ale_run.agents.ale_claw.verifier_runtime import stage_verifier_report
from ale_run.agents.ale_claw.task_prep import (
    MAX_PREP_ARTIFACT_BYTES,
    MAX_PREP_FINDINGS,
    MAX_PREP_REPORT_CHARS,
    PREP_TOOL_NAMES,
    TaskPrepResult,
    build_prep_digest,
    build_task_prep_system_prompt,
    collect_prep_artifacts,
    normalize_prep_bundle,
    prep_protocol_digest,
)
from ale_run.agents.ale_claw.harness.subagent.subagent_session import (
    _filter_tools,
    _rewind_kept_index_to_tool_call_boundary,
)
from ale_run.agents.ale_claw.harness.subagent.subagent_registry import SubagentRegistry
from ale_run.agents.ale_claw.harness.subagent.subagent_session import GeneralSubagentSession


@dataclass
class _CommandResult:
    stdout: str
    returncode: int = 0


class _StageInterface:
    def __init__(self) -> None:
        self.dirs: list[str] = []
        self.writes: list[tuple[str, str, bool]] = []

    async def create_dir(self, path: str) -> None:
        self.dirs.append(path)

    async def write_text(self, path: str, content: str, *, append: bool) -> None:
        self.writes.append((path, content, append))


class _ArtifactInterface:
    def __init__(self, content: str, *, returncode: int = 0) -> None:
        self.content = content
        self.returncode = returncode
        self.commands: list[str] = []

    async def run_command(self, command: str) -> _CommandResult:
        self.commands.append(command)
        return _CommandResult(
            str(len(self.content.encode("utf-8"))) + "\n",
            returncode=self.returncode,
        )

    async def read_text(self, path: str) -> str:
        return self.content


class _CommandRecorder:
    def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.commands: list[str] = []

    async def run_command(self, command: str) -> SimpleNamespace:
        self.commands.append(command)
        return SimpleNamespace(
            stdout=self.stdout, stderr=self.stderr, returncode=self.returncode
        )


class _Tool(BaseTool):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__()

    @property
    def description(self) -> str:
        return self.name

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def call(self, params, **kwargs):
        return self.name


def _payload(**overrides) -> str:
    value = {
        "environment": {
            "status": "ready",
            "summary": "The staged wrapper needs Python 3.10; 3.14 is ambient.",
            "commands": ["/usr/bin/python3.10 software/run.py --check"],
            "blocked_reason": "",
        },
        "contract": [
            {
                "requirement": "Write output/report.json with a top-level rows array.",
                "locator": "task_prompt",
                "check": "jq -e '.rows | type == \"array\"' report.json",
                "note": "The prompt names rows, not records.",
            },
        ],
        "findings": [
            {
                "title": "Consequence ranking",
                "observation": "Ensembl release 113 ranks missense above 5_prime_UTR.",
                "writer_action": "Order transcript selection by that rank table.",
                "sources": ["https://ensembl.org/info/consequences.html"],
                "do_not_infer": "It does not choose which transcript to report.",
            },
        ],
        "artifacts": [
            {"path": "rank.tsv", "purpose": "The 11 observed terms with ranks."}
        ],
    }
    value.update(overrides)
    return json.dumps(value)




def test_prep_budgets_must_be_positive() -> None:
    with pytest.raises(ValueError, match="task_specific_prep_max_steps"):
        AleClawConfig(task_specific_prep_max_steps=0)
    with pytest.raises(ValueError, match="task_specific_prep_timeout_s"):
        AleClawConfig(task_specific_prep_timeout_s=0)


def test_prep_metadata_records_a_content_digest_not_a_version_label() -> None:
    metadata = TaskPrepResult(status="empty").metadata()

    assert metadata["protocol_digest"] == prep_protocol_digest()
    assert metadata["protocol_digest"].startswith("prep-")
    assert metadata["report_sha256"] is None


def test_prep_metadata_audits_report_without_embedding_it() -> None:
    result = TaskPrepResult(
        status="completed",
        report="# Task-specific prep\n",
        artifacts={"artifacts/rank.tsv": "term\trank\n"},
        environment_status="ready",
        finding_count=1,
        dropped=["finding:empty_observation"],
    )
    metadata = result.metadata()

    assert "report" not in metadata
    assert metadata["report_chars"] == len(result.report)
    assert metadata["artifact_manifest"][0]["path"] == "artifacts/rank.tsv"
    assert metadata["environment_status"] == "ready"
    assert metadata["dropped"] == ["finding:empty_observation"]






def test_empty_response_produces_no_report() -> None:
    bundle = normalize_prep_bundle(json.dumps(
        {"environment": {}, "contract": [], "findings": [], "artifacts": []}
    ))

    assert bundle.report == ""
    assert bundle.artifact_paths == []












def test_unsafe_artifact_paths_are_dropped() -> None:
    bundle = normalize_prep_bundle(_payload(artifacts=[
        {"path": "../escape.py", "purpose": "no"},
        {"path": "notes.docx", "purpose": "no"},
        {"path": "tools/resolver.py", "purpose": "yes"},
    ]))

    assert bundle.artifact_paths == ["tools/resolver.py"]
    assert len(bundle.dropped) == 2


def test_declared_artifact_is_collected_with_a_bounded_size() -> None:
    interface = _ArtifactInterface("term\trank\nmissense\t1\n")

    artifacts, dropped = asyncio.run(collect_prep_artifacts(
        interface=interface,
        scratch_dir="/tmp/prep",
        artifact_paths=["rank.tsv"],
        os_type="linux",
    ))

    assert artifacts == {"artifacts/rank.tsv": "term\trank\nmissense\t1\n"}
    assert dropped == []
    assert "/tmp/prep/rank.tsv" in interface.commands[0]


def test_oversized_or_missing_artifact_is_dropped_not_fatal() -> None:
    oversized, dropped = asyncio.run(collect_prep_artifacts(
        interface=_ArtifactInterface("x" * (MAX_PREP_ARTIFACT_BYTES + 1)),
        scratch_dir="/tmp/prep",
        artifact_paths=["big.py"],
        os_type="linux",
    ))

    assert oversized == {}
    assert dropped == ["artifact:too_large:big.py"]

    missing, missing_drops = asyncio.run(collect_prep_artifacts(
        interface=_ArtifactInterface("ok", returncode=1),
        scratch_dir="/tmp/prep",
        artifact_paths=["gone.py"],
        os_type="linux",
    ))

    assert missing == {}
    # A missing declared file records what is actually on disk alongside it,
    # so the audit trail can tell a wrong declared path from a never-written
    # file.
    assert missing_drops[0] == "artifact:missing:gone.py"
    assert missing_drops[1].startswith("scratch:contents:")
    assert len(missing_drops) == 2



def test_artifact_with_binary_content_is_rejected() -> None:
    artifacts, dropped = asyncio.run(collect_prep_artifacts(
        interface=_ArtifactInterface("payload\x00binary\n"),
        scratch_dir="/tmp/prep",
        artifact_paths=["checker.py"],
        os_type="linux",
    ))

    assert artifacts == {}
    assert dropped == ["artifact:rejected_content:checker.py"]


def test_bundle_stages_artifacts_before_its_report() -> None:
    interface = _StageInterface()
    path = asyncio.run(_stage_prep_bundle(
        interface,
        task_root="/task/root",
        os_type="linux",
        content="prep report\n",
        artifacts={"artifacts/checker.py": "print('ok')\n"},
    ))

    assert path == "/task/root/task_prep/PREP_REPORT.md"
    assert interface.dirs == [
        "/task/root/task_prep",
        "/task/root/task_prep/artifacts",
    ]
    assert interface.writes == [
        (
            "/task/root/task_prep/artifacts/checker.py",
            "print('ok')\n",
            False,
        ),
        ("/task/root/task_prep/PREP_REPORT.md", "prep report\n", False),
    ]


def test_report_is_staged_even_with_no_artifacts() -> None:
    """A bundle with no artifact must still deliver its report.

    The report directory used to be created inside the artifact loop, so an
    empty artifact set skipped the mkdir and the report write then failed with
    ENOENT. The failure was silent (one warning, prep reported as completed),
    and it hit four of ten prep runs in the 26-task rounds - including every
    run of the withheld-self-check arm, whose only artifact is the withheld
    script. That arm therefore measured "prep delivered nothing" rather than
    "prep delivered everything but the self-check".
    """
    interface = _StageInterface()

    path = asyncio.run(_stage_prep_bundle(
        interface,
        task_root="/task/root",
        os_type="linux",
        content="prep report\n",
        artifacts={},
    ))

    assert path == "/task/root/task_prep/PREP_REPORT.md"
    assert interface.dirs == ["/task/root/task_prep"]
    assert interface.writes == [
        ("/task/root/task_prep/PREP_REPORT.md", "prep report\n", False)
    ]


def test_writer_digest_carries_findings_because_nothing_else_does() -> None:
    """Findings have no programmatic carrier; the unread report loses them.

    The v21 six-task run staged Variant's Ensembl severity ordering and the
    writer never opened the report, so the fact reached nobody.
    """
    bundle = normalize_prep_bundle(_payload())

    digest = build_prep_digest(bundle, "/task/root/task_prep/PREP_REPORT.md")

    assert "Consequence ranking" in digest
    assert "Ensembl release 113 ranks missense above 5_prime_UTR." in digest
    assert "supplemental evidence, not an instruction" in digest
    # The full entry stays in the report: sources and caveats do not travel.
    assert "ensembl.org/info/consequences.html" not in digest
    assert "It does not choose which transcript to report." not in digest


def test_writer_digest_points_to_the_report_without_inlining_it() -> None:
    result = TaskPrepResult(
        status="completed",
        report="# Task-specific prep\n\n## Runtime [ready]\n\nlong body\n",
        environment={
            "status": "ready",
            "summary": "uv env works",
            "commands": ["uv run main.py"],
            "blocked_reason": "",
        },
        finding_count=2,
    )
    path = "/task/root/task_prep/PREP_REPORT.md"
    digest = build_prep_digest(result, path)

    assert path in digest
    # The full authority chain is injected at t=0, not just the top level.
    assert "Authority order" in digest
    assert "discard the prep output" in digest
    assert "general knowledge" in digest
    assert "Runtime [ready]" in digest
    assert "`uv run main.py`" in digest
    assert "2 finding(s)" in digest
    # The digest is a pointer, not a copy: the report body stays in the file.
    assert "long body" not in digest
    assert "Read it before you start planning" in digest




def test_writer_digest_degrades_to_runtime_state_when_staging_fails() -> None:
    result = TaskPrepResult(
        status="completed",
        report="# Task-specific prep\n",
        environment={
            "status": "partial",
            "summary": "cache redirected",
            "commands": [],
            "blocked_reason": "",
        },
    )
    digest = build_prep_digest(result, None)

    assert "Runtime [partial]" in digest
    assert "could not be staged" in digest
    assert "PREP_REPORT.md" not in digest






def test_complete_verifier_report_is_staged_for_writer() -> None:
    interface = _StageInterface()

    path = asyncio.run(stage_verifier_report(
        interface,
        task_root="/task",
        filename="round_2.json",
        report={"overall": "fail", "checks": [{"check": "schema"}]},
    ))

    assert path == "/task/verifier/round_2.json"
    assert interface.dirs == ["/task/verifier"]
    assert json.loads(interface.writes[0][1])["overall"] == "fail"


def test_verifier_review_round_limit_is_bounded() -> None:
    with pytest.raises(ValueError, match="between 1 and 3"):
        AleClawConfig(verifier_max_review_rounds=0)
    with pytest.raises(ValueError, match="between 1 and 3"):
        AleClawConfig(verifier_max_review_rounds=4)


def test_prep_tool_policy_is_separate_from_normal_subagents() -> None:
    tools = [_Tool("read"), _Tool("exec"), _Tool("web_search"), _Tool("memory_get")]

    assert [tool.name for tool in _filter_tools(tools)] == ["memory_get"]
    prep_names = [tool.name for tool in _filter_tools(tools, PREP_TOOL_NAMES)]
    assert prep_names == ["read", "exec", "web_search"]
    assert "memory_get" not in prep_names


def test_compaction_keeps_tool_call_with_retained_result() -> None:
    messages = [
        {"role": "user", "content": "research"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-1", "type": "function", "function": {"name": "read"}},
                {"id": "call-2", "type": "function", "function": {"name": "exec"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "first"},
        {"role": "tool", "tool_call_id": "call-2", "content": "second"},
        {"role": "assistant", "content": "continue"},
    ]

    assert _rewind_kept_index_to_tool_call_boundary(messages, 3) == 1
    assert _rewind_kept_index_to_tool_call_boundary(messages, 4) == 4


def test_prep_session_executes_allowed_tool(tmp_path, monkeypatch) -> None:
    read_tool = _Tool("read")
    exec_tool = _Tool("exec")
    monkeypatch.setattr(read_tool, "call", lambda params, **kwargs: "x" * 200)
    monkeypatch.setattr(exec_tool, "call", lambda params, **kwargs: "y" * 200)
    read_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="read", arguments="{}"),
    )
    exec_call = SimpleNamespace(
        id="call-2",
        function=SimpleNamespace(name="exec", arguments="{}"),
    )
    responses = iter([
        SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(
                content="", tool_calls=[read_call, exec_call]
            ))],
        ),
        SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content="researched", tool_calls=None))],
        ),
    ])

    calls = []

    async def _completion(**kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr("litellm.acompletion", _completion)
    registry = SubagentRegistry(max_concurrent=1)
    session = GeneralSubagentSession(
        run_id="prep-test",
        task="prepare the public task",
        model="openai/test",
        tools=[read_tool, exec_tool, _Tool("memory_get")],
        registry=registry,
        summary_model="openai/test",
        parent_session_dir=tmp_path,
        allowed_tool_names=PREP_TOOL_NAMES,
        max_tool_result_chars_per_turn=80,
        system_prompt="prep system",
        api_key="solver-key",
        api_base="https://solver.example/v1",
    )

    assert asyncio.run(session.run()) == "researched"
    assert [item["role"] for item in session._messages] == [
        "system", "user", "assistant", "tool", "tool", "assistant"
    ]
    assert len(session._messages[3]["content"]) == 40
    assert len(session._messages[4]["content"]) == 40
    assert "truncated 200 chars" in session._messages[3]["content"]
    assert "truncated 200 chars" in session._messages[4]["content"]
    assert session.llm_turns == 2
    assert session.tool_call_count == 2
    assert session.tool_call_counts == {"read": 1, "exec": 1}
    assert all(call["api_key"] == "solver-key" for call in calls)
    assert all(call["api_base"] == "https://solver.example/v1" for call in calls)


def test_prep_is_enabled_by_default_with_a_budget_for_real_work() -> None:
    config = AleClawConfig(model="m")
    assert config.task_specific_prep is True
    # Prep now runs the task's core step rather than only reading it, so the
    # budget is sized for work, not for a skim.
    assert config.task_specific_prep_max_steps == 50


def test_attempt_is_parsed_with_its_verbatim_breakage() -> None:
    bundle = normalize_prep_bundle(json.dumps({
        "attempt": {
            "step": "run the annotation pipeline over the sample records",
            "outcome": "broke",
            "command": "python3 software/run.py --in input/records.tsv",
            "breakage": "KeyError: 'variant_allele' at run.py:212",
            "writer_action": "index frequencies by the submitted allele",
        }
    }))
    assert bundle.attempt["outcome"] == "broke"
    assert "KeyError" in bundle.attempt["breakage"]
    assert "## Core step attempt [broke]" in bundle.report
    assert "KeyError: 'variant_allele'" in bundle.report


def test_attempt_needs_a_step_and_a_known_outcome() -> None:
    no_step = normalize_prep_bundle(json.dumps({
        "environment": {"status": "ready", "summary": "fine"},
        "attempt": {"outcome": "broke", "step": ""},
    }))
    assert no_step.attempt == {}
    assert "attempt:empty_step" in no_step.dropped

    bad_outcome = normalize_prep_bundle(json.dumps({
        "environment": {"status": "ready", "summary": "fine"},
        "attempt": {"step": "run it", "outcome": "exploded"},
    }))
    assert bad_outcome.attempt == {}
    assert "attempt:unknown_outcome" in bad_outcome.dropped


def test_any_single_section_is_enough_for_a_report() -> None:
    only_env = normalize_prep_bundle(json.dumps(
        {"environment": {"status": "ready", "summary": "python3.11 works"}}
    ))
    assert only_env.report
    only_attempt = normalize_prep_bundle(json.dumps(
        {"attempt": {"step": "build the table", "outcome": "completed"}}
    ))
    assert only_attempt.report
    only_finding = normalize_prep_bundle(json.dumps(
        {"findings": [{"title": "t", "observation": "an exact fact"}]}
    ))
    assert only_finding.report


def test_one_bad_entry_does_not_discard_the_bundle() -> None:
    bundle = normalize_prep_bundle(json.dumps({
        "environment": {"status": "ready", "summary": "ok"},
        "findings": [
            {"title": "good", "observation": "a real fact"},
            {"title": "bad", "observation": ""},
        ],
        "attempt": {"step": "x", "outcome": "nonsense"},
    }))
    assert bundle.finding_count == 1
    assert "finding:empty_observation" in bundle.dropped
    assert "attempt:unknown_outcome" in bundle.dropped
    assert bundle.report


def test_report_is_bounded_and_announces_its_own_truncation() -> None:
    bundle = normalize_prep_bundle(json.dumps({
        "environment": {"status": "ready", "summary": "x" * 5_000},
        "findings": [
            {"title": f"f{i}", "observation": "y" * 1_200} for i in range(6)
        ],
    }))
    assert len(bundle.report) <= MAX_PREP_REPORT_CHARS


def test_digest_carries_runtime_breakage_and_findings() -> None:
    result = TaskPrepResult(
        status="completed",
        environment={"status": "ready", "summary": "python3.11", "commands": ["run.sh"],
                     "blocked_reason": ""},
        attempt={"step": "parse the records", "outcome": "broke", "command": "run.sh",
                 "breakage": "SchemaError: column missing", "writer_action": "check the header"},
        findings=[{"title": "ordering", "observation": "official order is A > B"}],
        finding_count=1,
    )
    digest = build_prep_digest(result, "task_prep/PREP_REPORT.md")
    assert "python3.11" in digest
    assert "Core step [broke]" in digest
    assert "SchemaError" in digest
    assert "official order is A > B" in digest
    assert "task_prep/PREP_REPORT.md" in digest
    # Prep's prescription never travels at t=0, and an unresolved breakage is
    # framed as one observation, not an agenda (the variant anchoring case).
    assert "check the header" not in digest
    assert "not a ranking of your priorities" in digest


def test_prep_never_advertises_a_contract_or_a_self_check() -> None:
    """Contract and schema conformance belong to the verifier now."""
    prompt = build_task_prep_system_prompt("/task")
    lowered = prompt.lower()
    assert "self_check" not in lowered
    assert "deliverable contract" not in lowered
    assert "core mechanical step" in lowered


def test_entries_beyond_the_caps_are_recorded_not_silently_sliced() -> None:
    findings = [
        {"title": f"fact {i}", "observation": f"value {i}"} for i in range(8)
    ]
    bundle = normalize_prep_bundle(json.dumps({"findings": findings}))
    assert bundle.finding_count == MAX_PREP_FINDINGS
    assert any(
        f"beyond the {MAX_PREP_FINDINGS} cap" in note for note in bundle.dropped
    )


def test_empty_prep_yields_no_digest_at_all() -> None:
    """Ready-with-nothing and not_needed inject nothing: announcing "a prep
    agent worked here" without content only sets an agenda at turn zero."""
    for status in ("not_needed", "ready", ""):
        result = TaskPrepResult(
            status="completed",
            report="# Task-specific prep\n",
            environment={"status": status, "summary": "nothing to do",
                         "commands": [], "blocked_reason": ""},
        )
        assert build_prep_digest(result, "task_prep/PREP_REPORT.md") == ""
    # Partial and blocked runtimes are real constraints and always travel.
    for status, reason in (("partial", ""), ("blocked", "docker unavailable")):
        result = TaskPrepResult(
            status="completed",
            report="# Task-specific prep\n",
            environment={"status": status, "summary": "state", "commands": [],
                         "blocked_reason": reason},
        )
        assert build_prep_digest(result, "task_prep/PREP_REPORT.md") != ""


def test_prompt_permits_silence_and_forbids_framing() -> None:
    """The three structural fixes live in the charter: an empty result is
    legitimate, findings are facts not frames, and an unsolved breakage is
    an observation, not an agenda."""
    prompt = build_task_prep_system_prompt("/task")
    assert "an empty result is\na successful prep" in prompt.replace("  ", " ") or \
        "an empty result is" in prompt
    assert "not_attempted` with a one-line reason" in prompt
    assert "is not a finding" in prompt
    assert "not an agenda for the\nwriter" in prompt or "not an agenda" in prompt
    assert "repro script" in prompt
    assert "Do not rank the writer's priorities" in prompt
