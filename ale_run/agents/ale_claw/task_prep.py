"""Pre-solve preparation for ALE Claw.

The prep worker runs in the writer's sandbox before the writer starts and has
three jobs: make the task's runtime actually work, run the task's core
mechanical step once and report where it breaks, and supply exact facts or
reusable tools the writer would otherwise have to derive.

It does not compile a deliverable contract and does not ship a script that
checks a candidate deliverable. Contract and schema conformance belong to the
verifier, which measures the writer's real output; a second checklist compiled
from the same public text carries no extra information and pulls the writer's
effort toward whatever it happens to name. Prep never reads or writes the
writer's ``output/``, which does not exist while it runs.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import shlex
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .harness.subagent.subagent_registry import (
    SubagentRegistry,
    SubagentType,
)
from .harness.subagent.subagent_session import GeneralSubagentSession
from .parsing import extract_json_object

logger = logging.getLogger(__name__)

NO_PREP_SENTINEL = "NO_TASK_SPECIFIC_PREP"

PREP_ATTEMPT_OUTCOMES = ("completed", "broke", "not_attempted")

PREP_WRAP_UP_NOTICE = (
    "Step budget notice: about {remaining} turns remain. Finish within the "
    "next 10 turns and return your JSON object. Leave the runtime in the "
    "state you verified, and report the core-step attempt honestly - "
    "outcome `broke` with the real error is a useful result, and outcome "
    "`not_attempted` is better than a guess. Running out of turns returns "
    "nothing at all."
)
"""Fired once when the step budget is ~80% spent.

Prep now spends part of its budget actually running the task's core step,
which is open-ended work, so exhausting the budget mid-run is a real risk -
and the loop returns a sentinel, discarding everything the run learned.
"""

MAX_PREP_FINDINGS = 6
MAX_PREP_ARTIFACTS = 4
MAX_PREP_ARTIFACT_BYTES = 64_000
MAX_PREP_ENV_COMMANDS = 8
MAX_PREP_REPORT_CHARS = 48_000
"""Safety ceiling on the report file, not an attention budget.

The report is delivered as a file the writer opens on demand, so its length no
longer competes with the writer's first-turn context. This bound only stops a
runaway response from filling the sandbox; a truncated report announces itself
in its own header so a partial checklist is never read as a complete one.
"""
DIGEST_FINDING_CHARS = 600
"""Per-finding budget in the first-turn digest.

Six findings at this size is a few thousand characters - the cost of the one
prep output class that has no programmatic carrier. The full entry, with its
sources and caveats, stays in the report file.
"""
MAX_PREP_TOOL_RESULT_CHARS_PER_TURN = 60_000
PREP_IO_TIMEOUT_S = 60
PREP_SETUP_TIMEOUT_S = 180
"""Scratch initialization gets more room than ordinary artifact I/O.

It is one idempotent ``rm -rf && mkdir``, but it runs before the LLM session
starts, so losing it forfeits the entire prep opportunity - the observed
failure shape is a run with zero LLM turns. Under parallel episodes sharing
one disk, 60 s proved too tight; the command is also retried once because a
retry has no side effects.
"""
PREP_AGENT_TIMEOUT_S = 1_800

PREP_ENV_STATUSES = ("ready", "partial", "not_needed", "blocked")
PREP_ARTIFACT_SUFFIXES = frozenset({
    ".csv", ".json", ".md", ".py", ".sh", ".sql", ".tsv", ".txt", ".yaml", ".yml",
})
PREP_TOOL_NAMES = frozenset({
    "read",
    "exec",
    "web_search",
    "web_fetch",
})


@dataclass
class TaskPrepResult:
    status: str
    report: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    environment_status: str = ""
    finding_count: int = 0
    attempt: dict[str, str] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    duration_s: float = 0.0
    llm_turns: int = 0
    tool_calls: int = 0
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    compactions: int = 0
    error: str | None = None

    def metadata(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("report", None)
        artifacts = data.pop("artifacts", {})
        data["protocol_digest"] = prep_protocol_digest()
        data["report_chars"] = len(self.report)
        data["report_sha256"] = (
            hashlib.sha256(self.report.encode("utf-8")).hexdigest()
            if self.report else None
        )
        data["artifact_count"] = len(artifacts)
        data["artifact_chars"] = sum(len(content) for content in artifacts.values())
        data["artifact_manifest"] = [
            {
                "path": path,
                "chars": len(content),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
            for path, content in sorted(artifacts.items())
        ]
        return data


def prep_scratch_dir(task_root: str) -> str:
    digest = hashlib.sha256(task_root.encode()).hexdigest()[:12]
    return f"/tmp/ale-task-prep-{digest}"


def prep_protocol_digest() -> str:
    """Content hash of the prep contract: the prompt text and output schema.

    A hand-bumped version number inflates with every edit and cannot be mapped
    back to what actually ran, which is how two rounds ended up compared under
    labels that did not describe their real difference. This digest is derived
    from the prompt the agent is actually given, so two runs share it exactly
    when they were given the same contract.
    """
    prompt = build_task_prep_system_prompt("<task_root>", scratch_dir="<scratch>")
    return "prep-" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def build_task_prep_system_prompt(
    task_root: str, *, scratch_dir: str | None = None
) -> str:
    scratch = scratch_dir or prep_scratch_dir(task_root)
    return f"""# Task-Specific Prep Agent

You run in the writer's sandbox before the writer starts. Everything you install,
configure, or leave on disk outside the task root is still there when the writer
begins, so your setup work is real work, not a report about work.

Public task root: {task_root or '(discover it from the task prompt)'}
Artifact scratch directory: {scratch}

You have three jobs, in this order of value.

## 1. Make the runtime work

Find what this task needs to run: `software/`, staged wrappers and launchers,
`pyproject.toml` / `requirements.txt` / lockfiles, Docker or service
dependencies, interpreter version pins, cache and permission requirements.
Then actually start it. Run the task's own recommended entry point first. When
it fails, diagnose and fix it: pick the interpreter that matches the pin,
redirect an unwritable cache, install a missing dependency, start the service,
or find the wrapper that works. Confirm the fix by running something that does
useful task work, not by importing a module.

Leave the sandbox in the state you verified. Report the exact commands that
worked. When a required capability cannot be made to work at all, say so
plainly and set status `blocked`: knowing that Docker is unavailable changes the
writer's method just as much as a working launcher does.

Keep the public task root read-only. The harness stages your report and
artifacts there after you finish, so you never write to it yourself. Installs,
caches, and temporary files belong in the runtime environment, `/tmp`, or
`{scratch}`.

## 2. Run this task's core mechanical step once

Identify the one mechanical step the task is built around - parse the filings,
run the annotation pipeline, fit the model, transform the records, drive the
task's own software - and actually run it end to end on the real inputs, with
your working files under `{scratch}`. You are not producing the deliverable.
You are finding out where this task breaks before the writer spends its budget
finding out.

Report what broke, with the exact command and the verbatim error. A breakage you
hit yourself outranks any obligation you could read off the task text, because
it is measured rather than predicted. Reading the prompt tells you what the task
says; running the step tells you what the task does. If the step runs clean, say
so and set outcome `completed` - that is also information.

Some tasks have no mechanical core: when the only step is reading staged
materials and writing prose, set outcome `not_attempted` with a one-line reason
instead of inventing a step to run.

When the step broke and you did not solve it, attach the exact repro script you
ran as an artifact, and report the breakage as one observation: the command and
the verbatim error. Do not rank the writer's priorities, do not label anything
a primary or critical problem, and do not direct where its budget goes. A
breakage you could not solve is a fact about the task, not an agenda for the
writer - the observed failure mode is a writer that spends its budget where an
unresolved prep note pointed, on a task it would otherwise have done well.

Do not compile a checklist of deliverable obligations, and do not write a script
that checks a candidate deliverable. Contract and schema conformance belong to
the verifier, which measures the writer's real output; a second checklist
compiled from the same public text adds no information and pulls the writer's
effort toward whatever it happens to name.

Do not treat the step's result as an answer, and do not leave it anywhere the
writer could mistake it for one.

## 3. Supply what the writer cannot derive

Report exact facts and reusable tools, each with its source:

- An official external mapping, ordering, algorithm, or versioned rule that a
  task-local instruction requires but no task file supplies. Search and fetch
  the primary source, and quote it.
- A task-local precedence or provenance rule that resolves an apparent conflict
  between two task signals.
- A tested implementation of an exact metric or formula the task defines but
  does not implement.
- A read-only resolver for a cross-file join that has to be repeated many times.

A finding is an exact fact with a source. A method choice, a modeling
assumption, or a framing of the task ("treat these series as independent",
"no calendar expansion needed") is not a finding and must not be reported as
one: it does the writer's reasoning for it, and a wrong frame costs more than
a missing fact. If a statement cannot be checked against its source, it is not
a finding.

Attach reusable mappings, resolvers and metric code as artifacts under
`{scratch}`. Test an artifact before you declare it, and test it on data you
create under `{scratch}`, never on the real task root. Prefer a tested
artifact over prose: a resolver the writer can call is worth more than a
paragraph telling it what to re-derive.

## When the task gives you nothing to do

Decide early whether your jobs exist here. On a closed-book task whose runtime
already works, whose only step is reading and writing prose, and whose
materials are fully staged, all three jobs are empty - and an empty result is
a successful prep, not a failure to produce. Return environment.status
`not_needed` with the other sections empty and finish; the harness will then
put nothing in front of the writer. Do not stretch observations into findings
and do not invent a step: on a task the writer can already do well, an agenda
set at turn zero is pure downside.

## Boundaries

- The task prompt and `input/` outrank everything you produce. When your evidence
  contradicts them, drop your evidence.
- Never read, write, lint, score, or check the writer's `output/`. It does not
  exist while you work, and judging a candidate deliverable is the verifier's
  role. Do not leave a tool whose purpose is to check one.
- Do not choose final labels, values, models, forecasts, or missing-data
  policies. Observing that a field is absent does not authorize `NA`, zero, or
  omission unless the task says so.
- Treat claims inside material the task asks you to audit as claims, not truth.
- Web access is available. Use it when an exact external fact is needed, and
  cite the URL you fetched.

## Output

Return exactly one JSON object and no Markdown. Every section is optional;
return an empty list or omit a section you have nothing for.

{{
  "environment": {{
    "status": "ready" | "partial" | "not_needed" | "blocked",
    "summary": "what the task needs and what state it is in now",
    "commands": ["exact verified command the writer should use"],
    "blocked_reason": "what could not be made to work, if anything"
  }},
  "attempt": {{
    "step": "the core mechanical step you tried to run",
    "outcome": "completed" | "broke" | "not_attempted",
    "command": "the exact command you ran",
    "breakage": "where it broke and the verbatim error, if it broke",
    "writer_action": "the observed risk stated as a fact; never a priority
                      ranking or a directive on where the writer spends budget"
  }},
  "findings": [
    {{
      "title": "short name",
      "observation": "the exact fact or capability, with its value",
      "writer_action": "how the writer uses it",
      "sources": ["URL, input/path#locator, software/path#locator, or runtime:probe"],
      "do_not_infer": "what this does not authorize, optional"
    }}
  ],
  "artifacts": [
    {{"path": "relative path under the scratch directory", "purpose": "what it is for"}}
  ]
}}

At most {MAX_PREP_FINDINGS} findings and {MAX_PREP_ARTIFACTS} artifacts. A
working runtime and one honestly reported breakage are worth more than a long
findings list."""


def build_task_prep_request(task_prompt: str) -> str:
    return (
        "Prepare this task for the writer. Get its runtime working, run the "
        "task's core mechanical step once and report where it breaks, and "
        "report the exact facts or tools the writer cannot easily derive.\n\n"
        f"PUBLIC TASK PROMPT:\n{task_prompt.strip()}"
    )


def _clean(value: Any) -> str:
    """Whitespace-collapse a free-text field without truncating it.

    Content fields (runtime summaries, breakage tracebacks, findings
    observations) are kept in full. A silent character cut drops real content
    the writer needs and, unlike a list-length cap, leaves nothing in
    ``dropped`` to mark the loss - the audit trail would then claim prep
    returned less than it did. The writer-facing digest applies its own
    injection budget; the report file keeps the whole thing, and the only
    remaining size guard is the recorded ``report:truncated`` safety cap.
    """
    return " ".join(str(value or "").split())


def _text(value: Any, *, limit: int) -> str:
    """Whitespace-collapse and hard-cap. Reserved for enum guards and the
    digest's injection budget, never for storing report content."""
    return _clean(value)[:limit]


def _artifact_path_ok(path: str) -> bool:
    if not path or "\\" in path:
        return False
    candidate = PurePosixPath(path)
    return (
        not candidate.is_absolute()
        and len(candidate.parts) <= 4
        and all(part not in {"", ".", ".."} and not part.startswith(".")
                for part in candidate.parts)
        and candidate.suffix.lower() in PREP_ARTIFACT_SUFFIXES
    )


@dataclass
class PrepBundle:
    report: str = ""
    artifact_paths: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    environment_status: str = ""
    finding_count: int = 0
    environment: dict[str, Any] = field(default_factory=dict)
    attempt: dict[str, str] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    artifact_entries: list[dict[str, str]] = field(default_factory=list)


def normalize_prep_bundle(text: str) -> PrepBundle:
    """Turn a prep response into a writer report plus its audit counters.

    Validation is mechanical and per-item: a malformed or out-of-bounds entry is
    dropped and recorded, never a reason to discard the whole bundle.
    """
    dropped: list[str] = []
    if not text or text.startswith(NO_PREP_SENTINEL):
        return PrepBundle(dropped=dropped)
    value = extract_json_object(text)

    def _over_cap(name: str, raw: Any, cap: int) -> None:
        # An entry beyond a cap is dropped like any other invalid entry, and
        # like any other drop it is recorded - a silent slice would make the
        # audit trail claim prep returned less than it did.
        if isinstance(raw, list) and len(raw) > cap:
            dropped.append(f"{name}: {len(raw) - cap} beyond the {cap} cap")

    raw_env = value.get("environment")
    env: dict[str, Any] = {}
    if isinstance(raw_env, dict):
        status = _text(raw_env.get("status"), limit=20)
        if status not in PREP_ENV_STATUSES:
            status = ""
        _over_cap("environment.commands", raw_env.get("commands"), MAX_PREP_ENV_COMMANDS)
        commands = [
            command for command in (
                _clean(raw)
                for raw in (raw_env.get("commands") or [])[:MAX_PREP_ENV_COMMANDS]
            )
            if command
        ]
        env = {
            "status": status,
            "summary": _clean(raw_env.get("summary")),
            "commands": commands,
            "blocked_reason": _clean(raw_env.get("blocked_reason")),
        }
        if not env["status"] and not env["summary"]:
            env = {}
    elif raw_env is not None:
        dropped.append("environment:not_an_object")

    attempt: dict[str, str] = {}
    raw_attempt = value.get("attempt")
    if isinstance(raw_attempt, dict):
        outcome = _text(raw_attempt.get("outcome"), limit=20)
        if outcome not in PREP_ATTEMPT_OUTCOMES:
            outcome = ""
        candidate = {
            "step": _clean(raw_attempt.get("step")),
            "outcome": outcome,
            "command": _clean(raw_attempt.get("command")),
            # The verbatim error is the whole point of this field: a paraphrased
            # or truncated traceback is a guess about the breakage, not the
            # breakage. Kept in full.
            "breakage": _clean(raw_attempt.get("breakage")),
            "writer_action": _clean(raw_attempt.get("writer_action")),
        }
        if not candidate["step"]:
            dropped.append("attempt:empty_step")
        elif not candidate["outcome"]:
            dropped.append("attempt:unknown_outcome")
        else:
            attempt = candidate
    elif raw_attempt is not None:
        dropped.append("attempt:not_an_object")

    findings: list[dict[str, Any]] = []
    raw_findings = value.get("findings")
    if isinstance(raw_findings, list):
        _over_cap("findings", raw_findings, MAX_PREP_FINDINGS)
        for raw in raw_findings[:MAX_PREP_FINDINGS]:
            if not isinstance(raw, dict):
                dropped.append("finding:not_an_object")
                continue
            _over_cap("finding.sources", raw.get("sources"), 4)
            item = {
                "title": _clean(raw.get("title")),
                "observation": _clean(raw.get("observation")),
                "writer_action": _clean(raw.get("writer_action")),
                "do_not_infer": _clean(raw.get("do_not_infer")),
                "sources": [
                    source for source in (
                        _clean(entry)
                        for entry in (raw.get("sources") or [])[:4]
                    )
                    if source
                ],
            }
            if not item["observation"]:
                dropped.append("finding:empty_observation")
                continue
            findings.append(item)
    elif raw_findings is not None:
        dropped.append("findings:not_a_list")

    artifacts: list[dict[str, str]] = []
    raw_artifacts = value.get("artifacts")
    if isinstance(raw_artifacts, list):
        _over_cap("artifacts", raw_artifacts, MAX_PREP_ARTIFACTS)
        for raw in raw_artifacts[:MAX_PREP_ARTIFACTS]:
            if not isinstance(raw, dict):
                dropped.append("artifact:not_an_object")
                continue
            path = _clean(raw.get("path"))
            if not _artifact_path_ok(path):
                dropped.append(f"artifact:invalid_path:{path[:60]}")
                continue
            artifacts.append({
                "path": path,
                "purpose": _clean(raw.get("purpose")),
            })
    elif raw_artifacts is not None:
        dropped.append("artifacts:not_a_list")

    if not env and not attempt and not findings:
        return PrepBundle(dropped=dropped)

    bundle = PrepBundle(
        artifact_paths=[item["path"] for item in artifacts],
        dropped=dropped,
        environment_status=env.get("status", "") if env else "",
        finding_count=len(findings),
        environment=env,
        attempt=attempt,
        findings=findings,
        artifact_entries=artifacts,
    )
    bundle.report = render_prep_report(bundle, unavailable=frozenset())
    return bundle


def render_prep_report(bundle: PrepBundle, *, unavailable: frozenset[str]) -> str:
    """Render the writer-facing report from a parsed bundle.

    ``unavailable`` holds declared artifact paths that could not be staged; the
    report is rendered (or re-rendered) so it never advertises a file the
    writer cannot open.
    """
    env = bundle.environment
    lines = [
        "# Task-specific prep",
        "",
        "Supplemental preparation done in this sandbox before you started.",
        "",
        "Authority order, highest first: (1) the task prompt, (2) `input/` and "
        "`software/`, (3) your own re-check of those materials, (4) anything in "
        "this report, (5) general knowledge. When anything here conflicts with "
        "something above it, discard what is here.",
    ]
    if env:
        lines.extend(["", f"## Runtime [{env['status'] or 'unspecified'}]", ""])
        if env["summary"]:
            lines.append(env["summary"])
        if env["commands"]:
            lines.extend(["", "Verified commands:"])
            lines.extend(f"- `{command}`" for command in env["commands"])
        if env["blocked_reason"]:
            lines.extend(["", f"Not working: {env['blocked_reason']}"])
    if bundle.attempt:
        attempt = bundle.attempt
        lines.extend([
            "",
            f"## Core step attempt [{attempt['outcome']}]",
            "",
            "This step was actually run in this sandbox before you started. It "
            "is a measurement of what this task does, not a reading of what it "
            "says, and it is the one thing here you cannot get by rereading "
            "the prompt.",
            "",
            f"- Step: {attempt['step']}",
        ])
        if attempt["command"]:
            lines.append(f"- Command: `{attempt['command']}`")
        if attempt["breakage"]:
            lines.extend(["", "Where it broke:", "", "```", attempt["breakage"], "```"])
        if attempt["writer_action"]:
            lines.extend(["", f"Watch out for: {attempt['writer_action']}"])
    if bundle.findings:
        lines.extend(["", "## Findings", ""])
        for index, item in enumerate(bundle.findings, 1):
            lines.append(f"### {index}. {item['title'] or 'finding'}")
            lines.append(f"- Observation: {item['observation']}")
            if item["writer_action"]:
                lines.append(f"- Writer action: {item['writer_action']}")
            for source in item["sources"]:
                lines.append(f"- Source: `{source}`")
            if item["do_not_infer"]:
                lines.append(f"- Do not infer: {item['do_not_infer']}")
            lines.append("")
    if bundle.artifact_entries:
        lines.extend(["", "## Artifacts", ""])
        for item in bundle.artifact_entries:
            if item["path"] in unavailable:
                lines.append(f"- (unavailable) {item['purpose']}")
            else:
                lines.append(
                    f"- `task_prep/artifacts/{item['path']}` - {item['purpose']}"
                )

    report = "\n".join(lines).strip() + "\n"
    if len(report) > MAX_PREP_REPORT_CHARS:
        # Announce truncation in the header: a reader who opens a cut-off file
        # must not mistake a partial checklist for a complete one.
        banner = (
            "> **This report was truncated at the safety limit.** The sections "
            "below are incomplete; treat the checklist as partial and reread "
            "the task prompt and `/input` for anything it does not cover.\n"
        )
        body = report[:MAX_PREP_REPORT_CHARS - len(banner)].rsplit("\n", 1)[0]
        head, _, rest = body.partition("\n")
        report = f"{head}\n\n{banner}{rest}\n"
        if "report:truncated" not in bundle.dropped:
            bundle.dropped.append("report:truncated")
    return report


def build_prep_digest(
    bundle_or_result: Any, report_path: str | None
) -> str:
    """The only prep content injected into the writer's first prompt.

    Everything else lives in the report file. Three things must arrive at t=0
    because they change what the writer does before it reads anything: the
    runtime state (a real fact about the sandbox), the core-step breakage (a
    measurement of what this task does, which no amount of rereading the prompt
    would produce), and the findings.

    Findings are here because they are the one class of prep output with no
    other carrier. Runtime state sinks into the sandbox itself, but an exact
    external fact the task omits - an official ordering, a versioned rule - can
    only travel as prose, and a finding left only in the report file has been
    observed to reach nobody. Only the title and observation travel; sources,
    the suggested use, and the do-not-infer caveat stay in the report.
    Prep's own prescriptions (writer_action) never travel at t=0: the digest
    sets the writer's opening agenda, and an unresolved prep note framed as a
    priority has been observed to pull a writer's budget into a pit on a task
    it would otherwise have done well.
    """
    env = getattr(bundle_or_result, "environment", None) or {}
    attempt = getattr(bundle_or_result, "attempt", None) or {}
    finding_count = getattr(bundle_or_result, "finding_count", 0)
    findings = getattr(bundle_or_result, "findings", None) or []

    # An empty prep puts nothing in front of the writer. Ready-with-nothing
    # and not_needed carry no information the writer can act on, so injecting
    # "a prep agent worked here" would be agenda without content; partial and
    # blocked runtimes are real constraints and always travel.
    if not (
        attempt
        or findings
        or (env.get("commands") or [])
        or env.get("blocked_reason")
        or env.get("status") in ("partial", "blocked")
    ):
        return ""

    lines = [
        "A prep agent worked in this sandbox before you started: it set up the "
        "runtime, read the public task materials, and looked up what the task "
        "does not supply. Its runtime state is real and already in place; "
        "everything it wrote is supplemental.",
        "",
        "Authority order, highest first: (1) the task prompt, (2) `input/` and "
        "`software/`, (3) your own re-check of those materials, (4) anything in "
        "this prep output, (5) general knowledge. When this prep output "
        "conflicts with anything above it, discard the prep output.",
    ]
    if env.get("status") or env.get("summary"):
        lines.append("")
        lines.append(f"**Runtime [{env.get('status') or 'unspecified'}]** "
                     f"{env.get('summary', '')}".rstrip())
        for command in env.get("commands") or []:
            lines.append(f"- Verified command: `{command}`")
        if env.get("blocked_reason"):
            lines.append(f"- Not working: {env['blocked_reason']}")
    if attempt:
        lines.extend([
            "",
            f"**Core step [{attempt.get('outcome') or 'unknown'}]** "
            f"{attempt.get('step', '')}".rstrip(),
        ])
        if attempt.get("command"):
            lines.append(f"- Command run: `{attempt['command']}`")
        if attempt.get("breakage"):
            lines.append(
                f"- Broke here: {_text(attempt['breakage'], limit=DIGEST_FINDING_CHARS)}"
            )
        if attempt.get("outcome") == "broke":
            lines.append(
                "- Prep did not solve this. It is one observation about the "
                "task, not a ranking of your priorities; your own reading of "
                "the task decides where your budget goes."
            )
    if findings:
        lines.extend([
            "",
            "**Findings** — exact facts the task materials do not supply. "
            "Each is supplemental evidence, not an instruction; the task "
            "prompt and `/input` still decide. Full sources, the suggested "
            "use, and what each does not authorize are in the report.",
        ])
        for item in findings:
            title = item.get("title") or "finding"
            observation = _text(item.get("observation"), limit=DIGEST_FINDING_CHARS)
            lines.append(f"- {title}: {observation}")
    if report_path:
        counts = (
            f"{finding_count} finding(s)" if finding_count else "no findings"
        )
        lines.extend([
            "",
            f"**Full report** `{report_path}` holds {counts}, the full breakage "
            "detail, source locators, and any artifacts. Read it before you "
            "start planning. It records what prep observed, not what the task "
            "will be graded on, and it may be incomplete.",
        ])
    else:
        lines.extend([
            "",
            "The full report could not be staged as a file, so only the "
            "runtime state above is available.",
        ])
    return "\n".join(lines)


async def collect_prep_artifacts(
    *,
    interface: Any,
    scratch_dir: str,
    artifact_paths: list[str],
    os_type: str,
) -> tuple[dict[str, str], list[str]]:
    """Read declared text artifacts out of the prep scratch directory."""
    artifacts: dict[str, str] = {}
    dropped: list[str] = []
    if not artifact_paths or os_type.lower() != "linux":
        return artifacts, dropped
    for relative in artifact_paths[:MAX_PREP_ARTIFACTS]:
        if not _artifact_path_ok(relative):
            dropped.append(f"artifact:invalid_path:{relative[:60]}")
            continue
        full_path = f"{scratch_dir.rstrip('/')}/{relative}"
        quoted = shlex.quote(full_path)
        try:
            result = await asyncio.wait_for(
                interface.run_command(
                    f"[ -f {quoted} ] && [ ! -L {quoted} ] && wc -c < {quoted}"
                ),
                timeout=PREP_IO_TIMEOUT_S,
            )
        except TimeoutError:
            dropped.append(f"artifact:unreadable:{relative}")
            continue
        # A failed probe means the declared file is not there: empty stdout
        # must not be parsed first, or every missing file is misfiled as
        # unreadable and the audit trail points away from the actual cause
        # (usually prep writing the file somewhere other than it declared).
        if getattr(result, "returncode", 1) != 0:
            dropped.append(f"artifact:missing:{relative}")
            continue
        try:
            byte_count = int(str(getattr(result, "stdout", "") or "").strip())
        except ValueError:
            dropped.append(f"artifact:unreadable:{relative}")
            continue
        if byte_count > MAX_PREP_ARTIFACT_BYTES:
            dropped.append(f"artifact:too_large:{relative}")
            continue
        try:
            content = await asyncio.wait_for(
                interface.read_text(full_path), timeout=PREP_IO_TIMEOUT_S
            )
        except Exception:  # noqa: BLE001 - an unreadable artifact is dropped
            dropped.append(f"artifact:unreadable:{relative}")
            continue
        if "\x00" in content:
            dropped.append(f"artifact:rejected_content:{relative}")
            continue
        artifacts[f"artifacts/{relative}"] = content
    if any(
        entry.startswith(("artifact:missing:", "artifact:unreadable:"))
        for entry in dropped
    ):
        # Diagnostic, not recovery: record what is actually on disk so the
        # audit trail can tell a wrongly declared path from a file that was
        # never written.
        try:
            listing = await asyncio.wait_for(
                interface.run_command(
                    f"find {shlex.quote(scratch_dir.rstrip('/'))} "
                    "-maxdepth 4 -type f 2>/dev/null | head -c 1500"
                ),
                timeout=PREP_IO_TIMEOUT_S,
            )
            found = " ".join(str(getattr(listing, "stdout", "") or "").split())
            dropped.append(f"scratch:contents:{found[:600] or '(no files)'}")
        except Exception:  # noqa: BLE001 - a diagnostic must not add a failure
            pass
    return artifacts, dropped


async def run_task_specific_prep(
    *,
    interface: Any,
    os_type: str,
    task_id: str,
    task_root: str,
    task_prompt: str,
    model: str,
    summary_model: str,
    tools: list,
    registry: SubagentRegistry,
    parent_session_dir: Path,
    max_steps: int,
    timeout_s: int = PREP_AGENT_TIMEOUT_S,
    thinking_params: dict[str, Any] | None = None,
    summary_runtime: Any | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> TaskPrepResult:
    """Run prep in the writer's sandbox and return its report and artifacts.

    Prep leaves real runtime state behind, so its result is never cached.
    """
    scratch_dir = prep_scratch_dir(task_root or task_id)
    setup_command = (
        f"rm -rf -- {shlex.quote(scratch_dir)} && "
        f"mkdir -p -- {shlex.quote(scratch_dir)}"
    )
    setup_failure = ""
    for _attempt in range(2):
        try:
            setup = await asyncio.wait_for(
                interface.run_command(setup_command),
                timeout=PREP_SETUP_TIMEOUT_S,
            )
        except TimeoutError:
            setup_failure = f"timed out after {PREP_SETUP_TIMEOUT_S}s"
            continue
        if getattr(setup, "returncode", 1) == 0:
            break
        setup_failure = f"exit code {getattr(setup, 'returncode', 1)}"
    else:
        raise RuntimeError(
            "could not initialize task prep scratch directory "
            f"({setup_failure})"
        )

    request = build_task_prep_request(task_prompt)
    run = registry.register(
        type=SubagentType.GENERAL,
        task=request,
        label="task-specific-prep",
        model=model,
    )
    registry.mark_running(run.run_id)
    session = GeneralSubagentSession(
        run_id=run.run_id,
        task=request,
        model=model,
        tools=tools,
        registry=registry,
        summary_model=summary_model,
        parent_session_dir=parent_session_dir,
        memory_store=None,
        max_steps=max_steps,
        thinking_params=thinking_params,
        summary_runtime=summary_runtime,
        allowed_tool_names=PREP_TOOL_NAMES,
        max_tool_result_chars_per_turn=MAX_PREP_TOOL_RESULT_CHARS_PER_TURN,
        system_prompt=build_task_prep_system_prompt(
            task_root, scratch_dir=scratch_dir
        ),
        api_key=api_key,
        api_base=api_base,
        wrap_up_notice=PREP_WRAP_UP_NOTICE,
    )
    registry.attach_inbox(run.run_id, session.inbox)
    started = time.monotonic()
    try:
        raw = (await asyncio.wait_for(session.run(), timeout=timeout_s)).strip()
        if raw.startswith("(subagent reached max steps"):
            raise RuntimeError("task prep reached max steps without a final report")
        bundle = normalize_prep_bundle(raw)
        report = bundle.report
        artifacts: dict[str, str] = {}
        unavailable: frozenset[str] = frozenset()
        if bundle.artifact_paths:
            artifacts, artifact_drops = await collect_prep_artifacts(
                interface=interface,
                scratch_dir=scratch_dir,
                artifact_paths=bundle.artifact_paths,
                os_type=os_type,
            )
            bundle.dropped.extend(artifact_drops)
            unavailable = frozenset(
                path for path in bundle.artifact_paths
                if f"artifacts/{path}" not in artifacts
            )
            if unavailable and report:
                report = render_prep_report(bundle, unavailable=unavailable)
        registry.complete(run.run_id, raw, session.usage)
        if bundle.dropped:
            logger.info(
                "task prep dropped entries: %s", ", ".join(bundle.dropped[:10])
            )
        return TaskPrepResult(
            status="completed" if report else "empty",
            report=report,
            artifacts=artifacts,
            environment_status=bundle.environment_status,
            finding_count=bundle.finding_count,
            attempt=bundle.attempt,
            environment=bundle.environment,
            findings=bundle.findings,
            dropped=bundle.dropped,
            input_tokens=session.usage.input_tokens,
            output_tokens=session.usage.output_tokens,
            duration_s=time.monotonic() - started,
            llm_turns=session.llm_turns,
            tool_calls=session.tool_call_count,
            tool_call_counts=dict(sorted(session.tool_call_counts.items())),
            compactions=session.compaction_count,
        )
    except Exception as exc:  # noqa: BLE001 - prep must not abort the writer
        registry.fail(run.run_id, str(exc), session.usage)
        logger.warning("task-specific prep failed: %s", exc)
        return TaskPrepResult(
            status="failed",
            input_tokens=session.usage.input_tokens,
            output_tokens=session.usage.output_tokens,
            duration_s=time.monotonic() - started,
            llm_turns=session.llm_turns,
            tool_calls=session.tool_call_count,
            tool_call_counts=dict(sorted(session.tool_call_counts.items())),
            compactions=session.compaction_count,
            error=f"{type(exc).__name__}: {exc}",
        )
