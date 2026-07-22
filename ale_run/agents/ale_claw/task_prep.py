"""Pre-solve preparation for ALE Claw.

The prep worker runs in the writer's sandbox before the writer starts and has
three jobs: make the task's runtime actually work, compile the deliverable's
machine-checkable contract from the public task surface, and supply exact facts
or reusable tools the writer would otherwise have to derive.

It never reads or writes the writer's candidate ``output/`` (which does not
exist while prep runs); judging a candidate artifact is verifier work. Its
writer-facing checks and tools may - and should - tell the writer how to verify
the eventual deliverable under ``output/``: the boundary is who runs a check and
when, not whether the deliverable path is mentioned.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
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

logger = logging.getLogger(__name__)

PREP_PROTOCOL_VERSION = "task-prep-v23"
NO_PREP_SENTINEL = "NO_TASK_SPECIFIC_PREP"

MAX_PREP_CONTRACT_ITEMS = 24
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
PREP_SELF_CHECK_TIMEOUT_S = 120

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
    contract_items: int = 0
    finding_count: int = 0
    contract: list[dict[str, str]] = field(default_factory=list)
    self_check: dict[str, str] | None = None
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
        data["protocol"] = PREP_PROTOCOL_VERSION
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

## 2. Compile the deliverable contract

Read the task prompt and `input/` and enumerate the obligations the deliverable
must satisfy that a machine could check: required files and their locations,
required fields and their spelling, identifiers that must be preserved,
consistency required across two files, ordering, units, row or record counts,
value ranges, encoding, and any explicitly weighted requirement.

Every item must carry the locator it came from. Give the check a writer could
run against its own draft deliverable under `output/` before submitting - an
exact command or an exact comparison, not "verify carefully". Explain the items
that are easy to miss or easy to read the wrong way, and say which reading the
task text supports.

When the contract has more than a handful of mechanical items - many required
fields, cross-file consistency rules, exhaustive ID preservation - do not leave
the checklist manual: implement it as one runnable self-check script, attach it
as an artifact, and register it in the `self_check` output field so the writer
gets a single exact command. The script takes the draft directory as an
argument and prints what passed, what failed, and what it cannot check. It must
report to stdout even when the draft directory is empty or files are missing -
a missing file is a finding to print, not a reason to exit silently. The
harness probes the script once on an empty draft and withholds it if it
crashes or prints nothing. Test it on a tiny synthetic draft you create under
the scratch directory, never on the real task root.

The self-check reports structural coverage, never correctness. It may check
that a file exists, that a field is present and spelled as the task spells it,
that row and record counts match a stated number, that identifiers are
preserved, that two files agree where the task says they must, and that
encoding and ordering follow the stated rule. It must not hardcode expected
values, decide whether an answer is right, or score anything: it answers "is
anything missing", not "is this correct". Judging the content of a candidate
deliverable is the verifier's role, and where no verifier runs, the writer
rechecks the task itself.

This is a reading of the public task, not a grading rubric and not a guess at
the hidden reference. Do not invent obligations the materials do not state. Do
not tell the writer what value to put in a field. If the task states an
obligation once and clearly, it still belongs on the list; completeness of the
list is what makes it useful. A checklist pulls effort toward the dimensions it
names, so phrase items as minimum obligations, never as targets to maximize,
and say explicitly what the list does not cover.

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
- A runnable self-check script that verifies contract items against a draft
  deliverable directory the writer passes as an argument. The writer runs it
  on its own `output/` as often as it wants; you never run it, because no
  candidate output exists while you work. Where the contract has many
  mechanical obligations (dozens of required fields, cross-file consistency
  rules, exhaustive ID preservation), this is the single most valuable
  artifact you can leave.

Attach reusable mappings, resolvers, metric code, and self-check scripts as
artifacts under `{scratch}`. Test an artifact before you declare it; test a
self-check script on a tiny synthetic draft you create under `{scratch}`,
never on the real task root.

## Boundaries

- The task prompt and `input/` outrank everything you produce. When your evidence
  contradicts them, drop your evidence.
- Never read, write, lint, score, or check the writer's `output/`. Judging a
  candidate artifact is the verifier's role, not yours. Telling the writer how
  to check its own draft is different and encouraged: contract checks and
  self-check artifacts should reference the deliverable paths under `output/`
  that the writer will create.
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
  "contract": [
    {{
      "requirement": "one machine-checkable obligation",
      "locator": "task_prompt or input/path#locator",
      "check": "how the writer verifies it",
      "note": "why it is easy to miss, optional"
    }}
  ],
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
  ],
  "self_check": {{
    "command": "exact command the writer runs against its draft, taking the draft directory as an argument, e.g. python3 task_prep/artifacts/check_contract.py output",
    "artifact": "the artifact path (relative to the scratch directory) implementing it",
    "covers": "which structural obligations it checks and what it cannot check"
  }}
}}

At most {MAX_PREP_CONTRACT_ITEMS} contract items, {MAX_PREP_FINDINGS} findings,
and {MAX_PREP_ARTIFACTS} artifacts. `self_check` is optional and must name a
declared artifact. A working runtime, a complete contract checklist, and a
runnable self-check are worth more than a long findings list."""


def build_task_prep_request(task_prompt: str) -> str:
    return (
        "Prepare this task for the writer. Get its runtime working, compile the "
        "deliverable contract from the public materials, and report the exact "
        "facts or tools the writer cannot easily derive.\n\n"
        f"PUBLIC TASK PROMPT:\n{task_prompt.strip()}"
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if stripped[index + end :].strip():
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("prep response does not contain one JSON object")


def _text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


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
    contract_items: int = 0
    finding_count: int = 0
    environment: dict[str, Any] = field(default_factory=dict)
    contract: list[dict[str, str]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    artifact_entries: list[dict[str, str]] = field(default_factory=list)
    self_check: dict[str, str] | None = None


def normalize_prep_bundle(text: str) -> PrepBundle:
    """Turn a prep response into a writer report plus its audit counters.

    Validation is mechanical and per-item: a malformed or out-of-bounds entry is
    dropped and recorded, never a reason to discard the whole bundle.
    """
    dropped: list[str] = []
    if not text or text.startswith(NO_PREP_SENTINEL):
        return PrepBundle(dropped=dropped)
    value = _parse_json_object(text)

    raw_env = value.get("environment")
    env: dict[str, Any] = {}
    if isinstance(raw_env, dict):
        status = _text(raw_env.get("status"), limit=20)
        if status not in PREP_ENV_STATUSES:
            status = ""
        commands = [
            command for command in (
                _text(raw, limit=600)
                for raw in (raw_env.get("commands") or [])[:MAX_PREP_ENV_COMMANDS]
            )
            if command
        ]
        env = {
            "status": status,
            "summary": _text(raw_env.get("summary"), limit=1200),
            "commands": commands,
            "blocked_reason": _text(raw_env.get("blocked_reason"), limit=600),
        }
        if not env["status"] and not env["summary"]:
            env = {}
    elif raw_env is not None:
        dropped.append("environment:not_an_object")

    contract: list[dict[str, str]] = []
    raw_contract = value.get("contract")
    if isinstance(raw_contract, list):
        for raw in raw_contract[:MAX_PREP_CONTRACT_ITEMS]:
            if not isinstance(raw, dict):
                dropped.append("contract:not_an_object")
                continue
            item = {
                "requirement": _text(raw.get("requirement"), limit=400),
                "locator": _text(raw.get("locator"), limit=300),
                "check": _text(raw.get("check"), limit=400),
                "note": _text(raw.get("note"), limit=400),
            }
            if not item["requirement"]:
                dropped.append("contract:empty_requirement")
                continue
            contract.append(item)
    elif raw_contract is not None:
        dropped.append("contract:not_a_list")

    findings: list[dict[str, Any]] = []
    raw_findings = value.get("findings")
    if isinstance(raw_findings, list):
        for raw in raw_findings[:MAX_PREP_FINDINGS]:
            if not isinstance(raw, dict):
                dropped.append("finding:not_an_object")
                continue
            item = {
                "title": _text(raw.get("title"), limit=160),
                "observation": _text(raw.get("observation"), limit=1200),
                "writer_action": _text(raw.get("writer_action"), limit=600),
                "do_not_infer": _text(raw.get("do_not_infer"), limit=400),
                "sources": [
                    source for source in (
                        _text(entry, limit=400)
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
        for raw in raw_artifacts[:MAX_PREP_ARTIFACTS]:
            if not isinstance(raw, dict):
                dropped.append("artifact:not_an_object")
                continue
            path = _text(raw.get("path"), limit=200)
            if not _artifact_path_ok(path):
                dropped.append(f"artifact:invalid_path:{path[:60]}")
                continue
            artifacts.append({
                "path": path,
                "purpose": _text(raw.get("purpose"), limit=300),
            })
    elif raw_artifacts is not None:
        dropped.append("artifacts:not_a_list")

    self_check: dict[str, str] | None = None
    raw_self_check = value.get("self_check")
    if isinstance(raw_self_check, dict):
        candidate_check = {
            "command": _text(raw_self_check.get("command"), limit=300),
            "artifact": _text(raw_self_check.get("artifact"), limit=200),
            # The coverage statement is the self-check's boundary declaration -
            # what it does not check. Truncating it mid-sentence (observed on
            # SEC at 300 chars) removes exactly the caveat it exists to make.
            "covers": _text(raw_self_check.get("covers"), limit=900),
        }
        declared = {item["path"] for item in artifacts}
        if not candidate_check["command"]:
            dropped.append("self_check:empty_command")
        elif candidate_check["artifact"] not in declared:
            dropped.append("self_check:artifact_not_declared")
        else:
            self_check = candidate_check
    elif raw_self_check is not None:
        dropped.append("self_check:not_an_object")

    if not env and not contract and not findings:
        return PrepBundle(dropped=dropped)

    bundle = PrepBundle(
        artifact_paths=[item["path"] for item in artifacts],
        dropped=dropped,
        environment_status=env.get("status", "") if env else "",
        contract_items=len(contract),
        finding_count=len(findings),
        environment=env,
        contract=contract,
        findings=findings,
        artifact_entries=artifacts,
        self_check=self_check,
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
    self_check = bundle.self_check
    if self_check and self_check["artifact"] in unavailable:
        bundle.self_check = None
        self_check = None
        bundle.dropped.append("self_check:artifact_unavailable")
    lines = [
        "# Task-specific prep",
        "",
        "Supplemental preparation done in this sandbox before you started. The "
        "task prompt and `/input` take precedence; discard anything here that "
        "conflicts with them.",
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
    if self_check:
        lines.extend([
            "",
            "## Self-check",
            "",
            f"Run `{self_check['command']}` against your draft whenever you "
            "want a coverage readout. It was tested on a synthetic sample "
            "only; it has no authority, and the checklist below stays the "
            "source of truth.",
            f"- Tool: `task_prep/artifacts/{self_check['artifact']}` - "
            f"{self_check['covers'] or 'contract self-check'}",
        ])
    if bundle.contract:
        lines.extend([
            "",
            "## Deliverable contract checklist",
            "",
            "Compiled from the task prompt and `/input`. It is a reading of the "
            "stated requirements, not a grading rubric, and it is incomplete "
            "by construction. Recheck anything you rely on, and never trade a "
            "quality the list does not name for a stricter pass on one it "
            "does: satisfy each item in the most natural way the task allows.",
            "",
        ])
        for index, item in enumerate(bundle.contract, 1):
            lines.append(f"{index}. {item['requirement']}")
            if item["locator"]:
                lines.append(f"   - Source: `{item['locator']}`")
            if item["check"]:
                lines.append(f"   - Check: {item['check']}")
            if item["note"]:
                lines.append(f"   - Note: {item['note']}")
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


def withhold_self_check(bundle: PrepBundle) -> None:
    """Remove the self-check and its artifact from everything the writer sees.

    Delivery switch for the self-check A/B (``task_specific_prep_self_check``):
    the prep agent behaves identically - same prompt, same budget, the script
    is still written and declared - and only the delivery differs, so a paired
    run isolates the net effect of the self-check channel from the rest of
    prep. The artifact is withheld too: a staged script the report lists is
    still discoverable, and the off arm must not deliver it through a side
    door.
    """
    if bundle.self_check is None:
        return
    withheld = bundle.self_check["artifact"]
    bundle.self_check = None
    bundle.artifact_paths = [
        path for path in bundle.artifact_paths if path != withheld
    ]
    bundle.artifact_entries = [
        entry for entry in bundle.artifact_entries if entry["path"] != withheld
    ]
    bundle.dropped.append("self_check:withheld_by_config")
    if bundle.report:
        bundle.report = render_prep_report(bundle, unavailable=frozenset())


def build_prep_digest(
    bundle_or_result: Any, report_path: str | None
) -> str:
    """The only prep content injected into the writer's first prompt.

    Everything else lives in the report file. Four things must arrive at t=0
    because they change what the writer does before it reads anything: the
    runtime state (a real fact about the sandbox), the exact self-check command
    (a staged file nobody names is a file nobody runs), the findings, and where
    the rest is.

    Findings are here because they are the one class of prep output with no
    other carrier. Runtime state sinks into commands and the self-check sinks
    into a script, but an exact external fact the task omits - an official
    ordering, a versioned rule - can only travel as prose. The v21 six-task run
    showed the writer never opens the report file (it has the commands and the
    script it needs), so a finding left only in that file reaches nobody:
    Variant's Ensembl severity ordering was delivered, staged, and never seen.
    Only the title and the observation travel; sources, writer_action, and the
    do-not-infer caveat stay in the report for the writer that follows up.
    """
    env = getattr(bundle_or_result, "environment", None) or {}
    self_check = getattr(bundle_or_result, "self_check", None)
    contract_items = getattr(bundle_or_result, "contract_items", 0)
    finding_count = getattr(bundle_or_result, "finding_count", 0)
    findings = getattr(bundle_or_result, "findings", None) or []

    lines = [
        "A prep agent worked in this sandbox before you started: it set up the "
        "runtime, read the public task materials, and looked up what the task "
        "does not supply. Its runtime state is real and already in place; "
        "everything it wrote is supplemental. The task prompt and `/input` "
        "take precedence over all of it."
    ]
    if env.get("status") or env.get("summary"):
        lines.append("")
        lines.append(f"**Runtime [{env.get('status') or 'unspecified'}]** "
                     f"{env.get('summary', '')}".rstrip())
        for command in env.get("commands") or []:
            lines.append(f"- Verified command: `{command}`")
        if env.get("blocked_reason"):
            lines.append(f"- Not working: {env['blocked_reason']}")
    if self_check:
        lines.extend([
            "",
            f"**Self-check** `{self_check['command']}`",
            "Run it against your draft before you finish and read what it "
            "reports. It checks structural coverage only "
            f"({self_check['covers'] or 'see the report'}); it has no "
            "authority and passing it is not evidence the task is complete.",
        ])
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
            f"{contract_items} contract item(s) and {finding_count} finding(s)"
            if (contract_items or finding_count) else "no checklist items"
        )
        lines.extend([
            "",
            f"**Full report** `{report_path}` holds {counts}, source locators, "
            "and any artifacts. Read it before you start planning; it is a "
            "reading of the stated requirements, not a grading rubric, and it "
            "may be incomplete. Never trade a quality it does not name for a "
            "stricter pass on one it does.",
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


async def preflight_self_check(
    *,
    interface: Any,
    scratch_dir: str,
    self_check: dict[str, str],
) -> str:
    """Run the declared self-check once against an empty draft.

    The self-check is the highest-frequency signal prep emits and the writer
    can run it without limit, so a script that crashes is a high-frequency
    wrong signal. This is the minimum version of the fixture discipline the
    verifier already applies: the script must start, finish, say something,
    and not die of its own bug. Reporting failures against an empty draft is
    correct behaviour and passes; only a crash, a timeout, or silence fails.

    Returns "" when the check is usable, otherwise a short reason.
    """
    probe = f"{scratch_dir.rstrip('/')}/selfcheck-probe"
    command = self_check["command"].replace(
        "task_prep/artifacts/", f"{scratch_dir.rstrip('/')}/"
    )
    if scratch_dir.rstrip("/") not in command:
        return "command does not invoke the declared artifact"
    script = (
        f"rm -rf -- {shlex.quote(probe)} && "
        f"mkdir -p -- {shlex.quote(probe)}/output && "
        f"cd {shlex.quote(probe)} && {command}"
    )
    try:
        result = await asyncio.wait_for(
            interface.run_command(script), timeout=PREP_SELF_CHECK_TIMEOUT_S
        )
    except TimeoutError:
        return f"timed out after {PREP_SELF_CHECK_TIMEOUT_S}s on an empty draft"
    except Exception as exc:  # noqa: BLE001 - an unusable probe drops the check
        return f"{type(exc).__name__}: {exc}"
    stdout = str(getattr(result, "stdout", "") or "").strip()
    stderr = str(getattr(result, "stderr", "") or "")
    if "Traceback (most recent call last)" in stderr:
        return "raised an unhandled exception on an empty draft"
    if not stdout:
        return "printed nothing on an empty draft"
    return ""


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
    deliver_self_check: bool = True,
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
    )
    registry.attach_inbox(run.run_id, session.inbox)
    started = time.monotonic()
    try:
        raw = (await asyncio.wait_for(session.run(), timeout=timeout_s)).strip()
        if raw.startswith("(subagent reached max steps"):
            raise RuntimeError("task prep reached max steps without a final report")
        bundle = normalize_prep_bundle(raw)
        if not deliver_self_check:
            withhold_self_check(bundle)
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
        if bundle.self_check and report:
            reason = await preflight_self_check(
                interface=interface,
                scratch_dir=scratch_dir,
                self_check=bundle.self_check,
            )
            if reason:
                bundle.self_check = None
                bundle.dropped.append(f"self_check:preflight_failed:{reason}")
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
            contract_items=bundle.contract_items,
            finding_count=bundle.finding_count,
            contract=bundle.contract,
            self_check=bundle.self_check,
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
