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
    MAX_PREP_CONTRACT_ITEMS,
    MAX_PREP_REPORT_CHARS,
    PREP_TOOL_NAMES,
    TaskPrepResult,
    build_prep_digest,
    build_task_prep_system_prompt,
    collect_prep_artifacts,
    normalize_prep_bundle,
    preflight_self_check,
    prep_scratch_dir,
    withhold_self_check,
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


def test_prep_is_enabled_by_default() -> None:
    config = AleClawConfig()

    assert config.task_specific_prep is True
    assert config.task_specific_prep_max_steps == 30
    assert config.task_specific_prep_timeout_s == 1800
    assert config.task_specific_prep_self_check is True
    assert config.writer_self_review_hint is False


def test_prep_budgets_must_be_positive() -> None:
    with pytest.raises(ValueError, match="task_specific_prep_max_steps"):
        AleClawConfig(task_specific_prep_max_steps=0)
    with pytest.raises(ValueError, match="task_specific_prep_timeout_s"):
        AleClawConfig(task_specific_prep_timeout_s=0)


def test_prep_metadata_records_protocol() -> None:
    metadata = TaskPrepResult(status="empty").metadata()

    assert metadata["protocol"] == "task-prep-v23"
    assert metadata["report_sha256"] is None


def test_prep_metadata_audits_report_without_embedding_it() -> None:
    result = TaskPrepResult(
        status="completed",
        report="# Task-specific prep\n",
        artifacts={"artifacts/rank.tsv": "term\trank\n"},
        environment_status="ready",
        contract_items=7,
        finding_count=1,
        dropped=["finding:empty_observation"],
    )
    metadata = result.metadata()

    assert "report" not in metadata
    assert metadata["report_chars"] == len(result.report)
    assert metadata["artifact_manifest"][0]["path"] == "artifacts/rank.tsv"
    assert metadata["environment_status"] == "ready"
    assert metadata["contract_items"] == 7
    assert metadata["dropped"] == ["finding:empty_observation"]


def test_prep_protocol_prepares_runtime_contract_and_facts() -> None:
    prompt = build_task_prep_system_prompt("/task/root")

    assert "You run in the writer's sandbox before the writer starts" in prompt
    assert "Make the runtime work" in prompt
    assert "Compile the deliverable contract" in prompt
    assert "not a grading rubric" in prompt
    assert "Never read, write, lint, score, or check the writer's `output/`" in prompt
    assert "A runnable self-check script" in prompt
    assert "should reference the deliverable paths under `output/`" in prompt
    assert prep_scratch_dir("/task/root") in prompt


def test_report_carries_runtime_contract_findings_and_artifacts() -> None:
    bundle = normalize_prep_bundle(_payload())

    assert bundle.environment_status == "ready"
    assert bundle.contract_items == 1
    assert bundle.finding_count == 1
    assert bundle.artifact_paths == ["rank.tsv"]
    assert bundle.dropped == []
    assert "## Runtime [ready]" in bundle.report
    assert "`/usr/bin/python3.10 software/run.py --check`" in bundle.report
    assert "## Deliverable contract checklist" in bundle.report
    assert "1. Write output/report.json with a top-level rows array." in bundle.report
    assert "- Source: `https://ensembl.org/info/consequences.html`" in bundle.report
    assert "- `task_prep/artifacts/rank.tsv` - " in bundle.report


def test_any_single_section_is_enough_for_a_report() -> None:
    only_contract = normalize_prep_bundle(json.dumps({
        "contract": [{"requirement": "Preserve the original process IDs."}],
    }))

    assert only_contract.report
    assert only_contract.contract_items == 1
    assert only_contract.environment_status == ""

    only_environment = normalize_prep_bundle(json.dumps({
        "environment": {"status": "blocked", "summary": "No Docker daemon.",
                        "blocked_reason": "docker: cannot connect"},
    }))

    assert "## Runtime [blocked]" in only_environment.report
    assert "Not working: docker: cannot connect" in only_environment.report


def test_empty_response_produces_no_report() -> None:
    bundle = normalize_prep_bundle(json.dumps(
        {"environment": {}, "contract": [], "findings": [], "artifacts": []}
    ))

    assert bundle.report == ""
    assert bundle.artifact_paths == []


def test_one_bad_entry_does_not_discard_the_bundle() -> None:
    bundle = normalize_prep_bundle(_payload(
        contract=[
            {"requirement": "", "locator": "task_prompt"},
            {"requirement": "Keep gateway IDs unchanged.", "locator": "task_prompt"},
        ],
        findings=[
            {"title": "no observation", "writer_action": "do something"},
            {"title": "kept", "observation": "Rule 21 extends Rule 16."},
        ],
    ))

    assert bundle.contract_items == 1
    assert bundle.finding_count == 1
    assert "Keep gateway IDs unchanged." in bundle.report
    assert bundle.dropped == [
        "contract:empty_requirement", "finding:empty_observation"
    ]


def test_writer_facing_checks_may_reference_the_deliverable() -> None:
    """The prep boundary is who runs a check and when, not the string output/.

    A contract check, a finding's writer action, and a verified command are all
    instructions the writer executes against its own draft; they necessarily
    name deliverable paths under output/, and v19 keeps them intact.
    """
    bundle = normalize_prep_bundle(_payload(
        environment={
            "status": "ready",
            "summary": "ok",
            "commands": ["python check.py output/report.json", "python -V"],
        },
        contract=[{
            "requirement": "Emit one row per case.",
            "locator": "task_prompt",
            "check": "wc -l output/rows.csv",
        }],
        findings=[{
            "title": "self-check available",
            "observation": "The checker exists.",
            "writer_action": "Run the checker on output/report.json.",
        }],
    ))

    assert bundle.dropped == []
    assert bundle.contract_items == 1
    assert bundle.finding_count == 1
    assert "- Check: wc -l output/rows.csv" in bundle.report
    assert "Run the checker on output/report.json." in bundle.report
    assert "`python check.py output/report.json`" in bundle.report
    assert "`python -V`" in bundle.report


def test_self_check_renders_as_a_first_class_section() -> None:
    bundle = normalize_prep_bundle(_payload(
        artifacts=[
            {"path": "check_contract.py", "purpose": "contract linter"},
            {"path": "rank.tsv", "purpose": "rank table"},
        ],
        self_check={
            "command": "python3 task_prep/artifacts/check_contract.py output",
            "artifact": "check_contract.py",
            "covers": "checks the rows array and required fields; cannot judge values",
        },
    ))

    assert bundle.self_check is not None
    assert bundle.dropped == []
    assert "## Self-check" in bundle.report
    assert "`python3 task_prep/artifacts/check_contract.py output`" in bundle.report
    assert "it has no authority" in bundle.report
    assert bundle.report.index("## Self-check") < bundle.report.index(
        "## Deliverable contract checklist"
    )
    assert bundle.contract[0]["requirement"].startswith("Write output/report.json")


def test_self_check_must_name_a_declared_artifact() -> None:
    undeclared = normalize_prep_bundle(_payload(self_check={
        "command": "python3 task_prep/artifacts/ghost.py output",
        "artifact": "ghost.py",
        "covers": "everything",
    }))
    assert undeclared.self_check is None
    assert "self_check:artifact_not_declared" in undeclared.dropped
    assert "## Self-check" not in undeclared.report

    empty_command = normalize_prep_bundle(_payload(self_check={
        "command": "",
        "artifact": "rank.tsv",
        "covers": "",
    }))
    assert empty_command.self_check is None
    assert "self_check:empty_command" in empty_command.dropped


def test_delivery_switch_withholds_self_check_and_its_artifact() -> None:
    """The A/B off arm removes every writer-facing trace of the self-check.

    Prep still wrote and declared the script; only delivery changes, so a
    paired run isolates the self-check channel from the rest of prep. The
    script artifact goes too - a listed file is discoverable even when the
    digest never names it.
    """
    bundle = normalize_prep_bundle(_payload(
        artifacts=[
            {"path": "check_contract.py", "purpose": "contract linter"},
            {"path": "rank.tsv", "purpose": "rank table"},
        ],
        self_check={
            "command": "python3 task_prep/artifacts/check_contract.py output",
            "artifact": "check_contract.py",
            "covers": "contract items",
        },
    ))
    assert bundle.self_check is not None

    withhold_self_check(bundle)

    assert bundle.self_check is None
    assert bundle.artifact_paths == ["rank.tsv"]
    assert "self_check:withheld_by_config" in bundle.dropped
    assert "## Self-check" not in bundle.report
    assert "check_contract.py" not in bundle.report
    assert "- `task_prep/artifacts/rank.tsv` - rank table" in bundle.report
    assert "Self-check" not in build_prep_digest(bundle, "task_prep/PREP_REPORT.md")
    # Idempotent: a second call must not double-record the drop.
    withhold_self_check(bundle)
    assert bundle.dropped.count("self_check:withheld_by_config") == 1


def test_report_rerenders_without_an_unavailable_artifact() -> None:
    from ale_run.agents.ale_claw.task_prep import render_prep_report

    bundle = normalize_prep_bundle(_payload(
        artifacts=[
            {"path": "check_contract.py", "purpose": "contract linter"},
            {"path": "rank.tsv", "purpose": "rank table"},
        ],
        self_check={
            "command": "python3 task_prep/artifacts/check_contract.py output",
            "artifact": "check_contract.py",
            "covers": "contract items",
        },
    ))
    assert "## Self-check" in bundle.report

    report = render_prep_report(bundle, unavailable=frozenset({"check_contract.py"}))

    assert "## Self-check" not in report
    assert "- (unavailable) contract linter" in report
    assert "- `task_prep/artifacts/rank.tsv` - rank table" in report
    assert bundle.self_check is None
    assert "self_check:artifact_unavailable" in bundle.dropped


def test_section_sizes_are_bounded() -> None:
    bundle = normalize_prep_bundle(json.dumps({
        "contract": [
            {"requirement": f"Requirement {index}", "locator": "task_prompt"}
            for index in range(MAX_PREP_CONTRACT_ITEMS + 5)
        ],
        "findings": [
            {"observation": "x" * 4000, "title": "long"}
        ],
    }))

    assert bundle.contract_items == MAX_PREP_CONTRACT_ITEMS
    assert "Requirement 0" in bundle.report
    assert f"Requirement {MAX_PREP_CONTRACT_ITEMS}" not in bundle.report
    assert len(bundle.report) <= MAX_PREP_REPORT_CHARS


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


def test_self_check_artifact_referencing_the_deliverable_is_collected() -> None:
    artifacts, dropped = asyncio.run(collect_prep_artifacts(
        interface=_ArtifactInterface("open('output/report.json')\n"),
        scratch_dir="/tmp/prep",
        artifact_paths=["checker.py"],
        os_type="linux",
    ))

    assert artifacts == {"artifacts/checker.py": "open('output/report.json')\n"}
    assert dropped == []


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
        contract_items=12,
        finding_count=2,
    )
    path = "/task/root/task_prep/PREP_REPORT.md"
    digest = build_prep_digest(result, path)

    assert path in digest
    assert "take precedence" in digest
    assert "Runtime [ready]" in digest
    assert "`uv run main.py`" in digest
    assert "12 contract item(s)" in digest
    # The digest is a pointer, not a copy: the report body stays in the file.
    assert "long body" not in digest
    assert "Read it before you start planning" in digest


def test_writer_digest_names_the_self_check_command() -> None:
    """A staged script the digest never names is a script the writer never runs."""
    result = TaskPrepResult(
        status="completed",
        report="# Task-specific prep\n",
        self_check={
            "command": "python3 task_prep/artifacts/check_contract.py output",
            "artifact": "check_contract.py",
            "covers": "required fields and row counts",
        },
    )
    digest = build_prep_digest(result, "/task/root/task_prep/PREP_REPORT.md")

    assert "`python3 task_prep/artifacts/check_contract.py output`" in digest
    assert "structural coverage only" in digest
    assert "no authority" in digest
    assert "required fields and row counts" in digest
    assert "not evidence the task is complete" in digest


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


def test_self_check_preflight_accepts_a_reporting_script() -> None:
    interface = _CommandRecorder(stdout="FAIL: output/report.json missing\n")

    reason = asyncio.run(preflight_self_check(
        interface=interface,
        scratch_dir="/tmp/prep",
        self_check={
            "command": "python3 task_prep/artifacts/check.py output",
            "artifact": "check.py",
            "covers": "",
        },
    ))

    assert reason == ""
    assert "/tmp/prep/check.py" in interface.commands[0]
    assert "task_prep/artifacts" not in interface.commands[0]
    assert "selfcheck-probe" in interface.commands[0]


def test_self_check_preflight_rejects_crash_silence_and_stray_command() -> None:
    crashed = asyncio.run(preflight_self_check(
        interface=_CommandRecorder(
            stdout="", stderr="Traceback (most recent call last):\n  KeyError\n"
        ),
        scratch_dir="/tmp/prep",
        self_check={"command": "python3 task_prep/artifacts/check.py output",
                    "artifact": "check.py", "covers": ""},
    ))
    assert "unhandled exception" in crashed

    silent = asyncio.run(preflight_self_check(
        interface=_CommandRecorder(stdout="   \n"),
        scratch_dir="/tmp/prep",
        self_check={"command": "python3 task_prep/artifacts/check.py output",
                    "artifact": "check.py", "covers": ""},
    ))
    assert "printed nothing" in silent

    stray = asyncio.run(preflight_self_check(
        interface=_CommandRecorder(stdout="ok"),
        scratch_dir="/tmp/prep",
        self_check={"command": "echo done", "artifact": "check.py", "covers": ""},
    ))
    assert "does not invoke the declared artifact" in stray


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
