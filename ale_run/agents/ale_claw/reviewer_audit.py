"""Independent, source-grounded delivery audit with a hard zero-discrepancy gate.

This is the ``reviewer`` arm's engine. It is a faithful, minimal port of argus's
independent Reviewer audit (``verticals/ale_last_exam/skills/reviewer/
ale-last-exam-delivery-review.md`` + ``roles/prompts/reviewer.py``) onto the
single-agent ale_claw harness, with none of argus's heavy machinery (no codex
subprocesses, no wheel builds, no Manager/Planner/Scientist multi-role stack, no
skill-propagation bookkeeping).

Relationship to the existing ``verifier`` arm
--------------------------------------------
The ``verifier`` (``verifier.py``) is deliberately a **zero-authority advisory
reviewer**: ``blocking`` is forced false everywhere, ``_overall`` never emits a
pass/fail verdict, and it never re-derives semantic values. It measures schema/
contract conformance and surfaces advisory feedback the writer may ignore. That
design was a retreat from an earlier hard gate that broke because it tried to
prove *source-implication* (an ambiguous, gameable semantic judgement).

The Reviewer audit takes the opposite stance on the subset of the deliverable
that is **deterministically recomputable from the public inputs**, and only
there. It:

  * runs a FRESH auditor sub-agent that never sees the writer's pipeline
    (``memory_store=None``, no writer transcript) — argus's "the reviewer
    re-derives, it does not re-read the claim";
  * treats the original instruction as the sole contract and refuses to award
    completion from the writer's narrative;
  * reopens/parses every named artifact from a read-only, hashed snapshot;
  * independently recomputes each *groundable* semantic field from the raw
    ``input/`` + ``software/`` and compares cell-by-cell;
  * refuses to invent a target for a field it cannot deterministically ground —
    such fields are recorded as ``not_verified`` (NA), left OUT of the gate, and
    always listed back to the writer as an explicit boundary (never silently
    passed — argus/wcy "a clean audit must never read as 'all correct'");
  * counts every genuine discrepancy into named counters and, mechanically,
    only lets the run finish when **every counter is zero** for the complete
    bundle. The gate is enforced in code (``ReviewerVerdict.gate_passes``), not
    left to the model's self-report.

The gate therefore fires only on *facts* (a deterministic recompute disagreed),
never on an ambiguous relevance judgement — which is exactly the failure mode
the old hard gate died on. Everything not deterministically groundable stays
advisory, honouring the verifier's hard-won lessons.

Hidden-reference safety is inherited from the lifecycle, not re-implemented:
the task's hidden reference/grader is staged only in Phase 3, AFTER ``launch()``
returns, so the auditor — which runs inside ``launch()`` — physically cannot
read it. On top of that, the auditor prompt denylists grader/solution/reference/
evaluator paths and forbids reading anything outside the public surface.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Reuse the verifier's fresh-context sub-agent runner and usage accounting
# verbatim: same isolation guarantees (memory_store=None, restricted toolset,
# own registry), no duplicated infrastructure.
from .verifier import AgentUsage, _run_fresh_agent

logger = logging.getLogger(__name__)

# The auditor's effective toolset. NOTE: the shared ``_run_fresh_agent`` runner
# pins the sub-agent's allowed tools to the verifier's read/exec/analyze_image
# set, which is a superset of what we need (read to reopen artifacts, exec to run
# independent recompute scripts, analyze_image to inspect rendered visuals per the
# argus "inspect native state/visuals" step). This constant documents the intent;
# it is not re-passed, so there is no second source of truth to drift.
REVIEWER_AUDIT_TOOL_NAMES = frozenset({"read", "exec", "analyze_image"})

MAX_FINDINGS = 40
MAX_NOT_VERIFIED = 40
MAX_REASON_CHARS = 800
MAX_NEXT_ACTION_CHARS = 2000
MAX_INLINE_REPORT_CHARS = 20_000

# The named zero-discrepancy counters. All must be 0 over the complete bundle
# for the auditor to return `done`. These are the argus "hard gate" made
# mechanical + the memory-note hardening ("named zero-discrepancy counters").
COUNTER_NAMES = (
    "missing_required",       # a mandatory output/field/artifact is absent
    "unparseable_artifacts",  # named but corrupt/empty/all-null/placeholder/invalid
    "field_mismatches",       # recompute-from-source disagreed with a written cell
    "contradictions",         # stale export / cross-artifact contradictory values
    "stale_or_unfinished",    # required sim/render/build/export did not truly finish
)

# Authority ladder, ported from argus roles/task_contract.py:EFFECTIVE_TASK_CONTRACT.
_AUTHORITY_LADDER = (
    "Authority order: the original task instruction and its named public "
    "materials (input/, software/) outrank everything else. You never invent "
    "stricter gates than the instruction states, and you never relax one it "
    "states. The hidden reference and final grader are unavailable and must "
    "remain so."
)

REVIEWER_AUDIT_SYSTEM_PROMPT = f"""\
You are an independent Reviewer performing a source-grounded delivery audit of a
solver's finished work on one Agents' Last Exam task. You are a SEPARATE agent:
you did not write this deliverable, you cannot see the solver's reasoning or
code, and you must not trust any narrative claim of completion. You re-derive;
you do not re-read the claim.

{_AUTHORITY_LADDER}

CONTRACT
- Treat the original task instruction as the SOLE contract. Do not award
  completion from the solver's narrative or from a correctly named file.
- Produce your judgements ONLY from the public task instruction, the public
  input/ and software/, and the read-only snapshot of the solver's output/ that
  this prompt points you to.
- NEVER read, search for, or infer a hidden reference, expected-answer file,
  grader/evaluator/solution/scoring script, or any prior run's score. If you
  encounter such a path, do not open it. Your recomputations must come from the
  raw task inputs, never from any provided reference or expected value.

REVIEW PROTOCOL — audit in this order (argus delivery-review):
 1. Enumerate every mandatory output and every hard gate stated in the
    instruction. This enumeration is the contract you audit against.
 2. Inspect exact paths, names, extensions, sizes, and companion files against
    what the instruction requires.
 3. Reopen or parse each artifact with a task-appropriate INDEPENDENT check. A
    correctly named but corrupt, empty, all-null, placeholder, or structurally
    invalid file FAILS.
 4. For every semantic field/value in the deliverable that you can
    deterministically recompute from the raw input/ + software/, do so with your
    OWN script or reasoning and compare CELL BY CELL against what was written.
    Confirm that reported values actually come from the outputs of any required
    simulation/render/export/build/replay, not from a guess or a narrative.
 5. Cross-check all artifacts against each other for stale exports and
    contradictory values.
 6. Run a final hard-gate pass over the WHOLE bundle.

GROUNDING RULE (this is what makes the gate sound — obey it strictly)
- You may only count a field as a mismatch when you INDEPENDENTLY recomputed the
  correct value from a NAMED public source with an unambiguous, deterministic
  method. State that source (path + the exact bytes/rows/keys you used).
- If a field's correct value is NOT deterministically derivable from the public
  inputs (it needs an undefined threshold/tolerance/tie-break, a proxy, a sample,
  a subjective judgement, or an external fact the instruction does not pin down),
  you MUST NOT guess a target and MUST NOT count it. Record it under
  `not_verified` with a one-line reason. A weak agent-designed proxy is not
  evidence; prefer `not_verified` over a fabricated expectation.
- Do not modify output/, input/, or software/. Write only to your own /tmp
  scratch. Read the deliverable from the snapshot path given below.

COUNTERS (the hard gate)
Tally every confirmed defect into exactly one of these counters:
  missing_required       - a mandatory output/field/artifact is absent
  unparseable_artifacts  - named but corrupt/empty/all-null/placeholder/invalid
  field_mismatches       - your recompute-from-source disagreed with a written value
  contradictions         - stale export or cross-artifact contradictory values
  stale_or_unfinished    - a required sim/render/build/export did not truly finish,
                           or a reported value is not backed by its output
Return status `done` ONLY when EVERY counter is 0 across the complete bundle and
you have independently verified the whole thing. If one observable requirement
is still unverified or one defect stands, return `continue` and put the
highest-risk repair first with an EXACT command or edit the solver can apply.
Return `blocked` only for a genuine external/credential dependency you cannot
resolve from public materials.

OUTPUT
Your final message must be exactly ONE JSON object and nothing else, matching:
{{
  "status": "done" | "continue" | "blocked",
  "reason": "<short verdict rationale, <= {MAX_REASON_CHARS} chars>",
  "counters": {{ {", ".join(f'"{c}": <int>' for c in COUNTER_NAMES)} }},
  "findings": [
    {{
      "id": "kebab-case-id",
      "counter": "<one of the counter names>",
      "artifact": "<output path>",
      "locator": "<row/cell/key/region>",
      "observed": "<what the deliverable has>",
      "recomputed": "<the value you independently derived from the public source>",
      "source": "<public path + the exact rows/keys/quote you recomputed from>",
      "fix": "<exact command or edit the solver should apply>"
    }}
  ],
  "not_verified": [
    {{ "requirement": "<the requirement>", "why": "<why it is not groundable from public materials>" }}
  ],
  "next_action": "<the single highest-priority repair instruction, empty when done>"
}}
Every finding must cite a public `source`. `counters` must equal the number of
findings tagged to each counter. Do not emit any prose outside the JSON object.
"""


@dataclass
class ReviewerFinding:
    id: str
    counter: str
    artifact: str = ""
    locator: str = ""
    observed: str = ""
    recomputed: str = ""
    source: str = ""
    fix: str = ""

    @classmethod
    def from_obj(cls, obj: dict[str, Any], index: int) -> "ReviewerFinding":
        def s(key: str) -> str:
            return str(obj.get(key, "") or "").strip()

        fid = s("id") or f"finding-{index}"
        counter = s("counter")
        if counter not in COUNTER_NAMES:
            counter = "field_mismatches"
        return cls(
            id=fid[:80],
            counter=counter,
            artifact=s("artifact")[:300],
            locator=s("locator")[:300],
            observed=s("observed")[:1000],
            recomputed=s("recomputed")[:1000],
            source=s("source")[:1000],
            fix=s("fix")[:1000],
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id, "counter": self.counter, "artifact": self.artifact,
            "locator": self.locator, "observed": self.observed,
            "recomputed": self.recomputed, "source": self.source, "fix": self.fix,
        }


@dataclass
class ReviewerVerdict:
    """One audit round's verdict, with the gate enforced mechanically.

    ``gate_passes`` is the single source of truth for whether the bundle may
    finish. It never trusts the model's ``status`` alone: even a ``done`` verdict
    is overridden to a rejection if any counter is non-zero or any finding stands.
    """
    status: str                      # "done" | "continue" | "blocked"
    reason: str = ""
    counters: dict[str, int] = field(default_factory=lambda: {c: 0 for c in COUNTER_NAMES})
    findings: list[ReviewerFinding] = field(default_factory=list)
    not_verified: list[dict[str, str]] = field(default_factory=list)
    next_action: str = ""
    parse_error: str | None = None   # set when the auditor output could not be parsed
    raw_head: str = ""               # first chars of the raw auditor output (audit trail)

    def outstanding(self, disputes: set[str]) -> list[ReviewerFinding]:
        """Findings that still count against the gate (not writer-disputed)."""
        return [f for f in self.findings if f.id not in disputes]

    def outstanding_counters(self, disputes: set[str]) -> dict[str, int]:
        """Counter tally over the non-disputed findings only. This — not the
        stored ``counters`` (which cover ALL findings for the audit trail) — is
        what the gate reads, so a legitimately disputed finding stops counting."""
        tally = {c: 0 for c in COUNTER_NAMES}
        for f in self.outstanding(disputes):
            tally[f.counter] = tally.get(f.counter, 0) + 1
        return tally

    def gate_passes(self, disputes: set[str]) -> bool:
        """Hard zero-discrepancy gate. True only when every non-disputed defect
        is gone (equivalently, every counter over the outstanding findings is
        zero). A parse error never passes the gate on its own (fail-closed for
        the *decision*), but the caller still fails-open for the *run* by
        bounding rounds and never failing the unit."""
        if self.parse_error is not None:
            return False
        return not self.outstanding(disputes)

    def effective_status(self, disputes: set[str]) -> str:
        """What the harness acts on. ``done`` from the model is honoured only if
        the mechanical gate agrees; ``blocked`` is passed through."""
        if self.status == "blocked":
            return "blocked"
        return "done" if self.gate_passes(disputes) else "continue"

    def metadata(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "counters": dict(self.counters),
            "findings": [f.to_dict() for f in self.findings],
            "not_verified": self.not_verified,
            "next_action": self.next_action,
            "parse_error": self.parse_error,
            "raw_head": self.raw_head,
        }


def _extract_json_object(text: str) -> str | None:
    """Return the outermost balanced {...} block in ``text`` (models sometimes
    wrap the JSON in prose or a ```json fence despite instructions)."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_verdict(text: str) -> ReviewerVerdict:
    """Parse the auditor's final message into a verdict, defensively.

    A malformed auditor output must not silently become a pass: on any parse
    failure we return a ``continue`` verdict carrying ``parse_error`` (which the
    gate treats as not-passing), so the writer either gets another bounded round
    or the run ends on the round budget with the writer's own last output intact.
    """
    raw_head = (text or "")[:400]
    blob = _extract_json_object(text or "")
    if blob is None:
        return ReviewerVerdict(
            status="continue", reason="auditor produced no JSON verdict",
            parse_error="no_json_object", raw_head=raw_head,
        )
    try:
        obj = json.loads(blob)
    except Exception as exc:  # noqa: BLE001
        return ReviewerVerdict(
            status="continue", reason="auditor verdict was not valid JSON",
            parse_error=f"json_decode_error: {exc}", raw_head=raw_head,
        )
    if not isinstance(obj, dict):
        return ReviewerVerdict(
            status="continue", reason="auditor verdict was not an object",
            parse_error="not_an_object", raw_head=raw_head,
        )

    status = str(obj.get("status", "")).strip().lower()
    if status not in ("done", "continue", "blocked"):
        status = "continue"

    findings_obj = obj.get("findings") or []
    findings: list[ReviewerFinding] = []
    if isinstance(findings_obj, list):
        for i, f in enumerate(findings_obj[:MAX_FINDINGS]):
            if isinstance(f, dict):
                findings.append(ReviewerFinding.from_obj(f, i))

    # Recompute counters from the findings themselves so the model cannot report
    # "0 defects" while listing defects. The self-reported counters are kept only
    # for the audit trail; the derived ones drive the gate.
    derived = {c: 0 for c in COUNTER_NAMES}
    for f in findings:
        derived[f.counter] = derived.get(f.counter, 0) + 1

    not_verified_obj = obj.get("not_verified") or []
    not_verified: list[dict[str, str]] = []
    if isinstance(not_verified_obj, list):
        for nv in not_verified_obj[:MAX_NOT_VERIFIED]:
            if isinstance(nv, dict):
                not_verified.append({
                    "requirement": str(nv.get("requirement", "") or "").strip()[:500],
                    "why": str(nv.get("why", "") or "").strip()[:500],
                })

    return ReviewerVerdict(
        status=status,
        reason=str(obj.get("reason", "") or "").strip()[:MAX_REASON_CHARS],
        counters=derived,
        findings=findings,
        not_verified=not_verified,
        next_action=str(obj.get("next_action", "") or "").strip()[:MAX_NEXT_ACTION_CHARS],
        raw_head=raw_head,
    )


def build_audit_task(*, task_prompt: str, snapshot_path: str, round_index: int) -> str:
    """The per-task request handed to the fresh auditor sub-agent."""
    return (
        "Audit the finished deliverable for the task below.\n\n"
        f"AUDIT ROUND: {round_index}\n"
        f"DELIVERABLE SNAPSHOT (read-only copy of output/): {snapshot_path}\n"
        "Read the deliverable from that snapshot path. The public task inputs are\n"
        "under input/ and software/ in the task root. Do not look for or open any\n"
        "hidden reference, grader, evaluator, or solution file.\n\n"
        "===== ORIGINAL TASK INSTRUCTION (the sole contract) =====\n"
        f"{task_prompt}\n"
        "===== END TASK INSTRUCTION =====\n\n"
        "Follow the review protocol and return exactly one JSON verdict object."
    )


# The writer signals it accepts a finding rather than repairing it with a line
# `AUDIT_DISPUTE <finding-id>` plus public counter-evidence. Mirrors the
# verifier's VERIFIER_DISPUTE protocol (line-anchored, whitespace-separated id)
# so the writer keeps the last word.
_DISPUTE_TOKEN = "AUDIT_DISPUTE"
_DISPUTE_RE = re.compile(r"^[ \t]*AUDIT_DISPUTE\s+([A-Za-z0-9_.-]+)\b", re.MULTILINE)


def parse_audit_disputes(text: str, known_ids: set[str]) -> set[str]:
    return {
        match.group(1) for match in _DISPUTE_RE.finditer(text or "")
        if match.group(1) in known_ids
    }


def build_audit_feedback_prompt(
    verdict: ReviewerVerdict,
    *,
    disputes: set[str],
    report_path: str | None,
    round_index: int,
) -> str:
    """Source-first repair feedback pushed to the writer between rounds.

    Every recomputed value cited here was derived by the auditor from the PUBLIC
    inputs, so it is a legitimate correction — it is NOT a hidden reference/
    expected value, and copying the task's provided reference remains forbidden.

    Repair is SCOPED: the feedback names the exact artifacts to fix and tells the
    writer to touch only those, leaving every other file byte-identical. A full
    pipeline re-run can silently regress an un-audited graded artifact, so the
    harness also enforces this mechanically — every non-named path is reverted to
    the pre-repair snapshot after the round.
    """
    lines: list[str] = []
    lines.append("## Independent delivery audit — scoped repair needed")
    lines.append(
        "A fresh, independent Reviewer re-derived your deliverable from the "
        "public task inputs (it never saw your work and cannot read any hidden "
        "reference or grader). Its verdict is NOT final and does NOT block you: "
        "you are the only agent that decides output/. Fix ONLY the named "
        "artifacts listed below — apply the smallest edit that resolves each "
        "defect. Leave every other file in output/ byte-identical; do NOT "
        "regenerate or re-run the whole bundle/pipeline, because that risks "
        "clobbering already-correct artifacts the audit did not flag. The "
        "recomputed values come from the public inputs; never copy any provided "
        "reference/expected value."
    )
    if verdict.reason:
        lines.append(f"\nReviewer reason: {verdict.reason}")

    outstanding = verdict.outstanding(disputes)
    if outstanding:
        lines.append("\n### Confirmed defects (each blocks completion until fixed or disputed)")
        for f in outstanding:
            lines.append(
                f"\n- [{f.counter}] `{f.id}` — {f.artifact}"
                + (f" @ {f.locator}" if f.locator else "")
            )
            if f.observed:
                lines.append(f"    observed:   {f.observed}")
            if f.recomputed:
                lines.append(f"    recomputed: {f.recomputed}")
            if f.source:
                lines.append(f"    source:     {f.source}")
            if f.fix:
                lines.append(f"    fix:        {f.fix}")

    if verdict.next_action:
        lines.append(f"\n### Highest-priority next action\n{verdict.next_action}")

    # Boundary declaration — never let a clean/partial audit read as "all
    # correct". These were NOT checked; they carry zero evidence either way.
    lines.append("\n### NOT VERIFIED by this audit (no evidence either way)")
    if verdict.not_verified:
        for nv in verdict.not_verified:
            req = nv.get("requirement", "")
            why = nv.get("why", "")
            lines.append(f"- {req}" + (f" — why untested: {why}" if why else ""))
    else:
        lines.append(
            "- The auditor did not record any requirement as impossible to ground "
            "from public materials this round."
        )

    allowlist = sorted({f.artifact for f in outstanding if f.artifact})
    if allowlist:
        lines.append(
            "\n### Files you may edit this round (everything else is reverted)\n"
            + "\n".join(f"- {a}" for a in allowlist)
            + "\nAny change you make outside these paths is discarded after the "
            "round — keep the rest of output/ untouched."
        )

    lines.append(
        f"\nIf a confirmed defect is wrong, reply with a line `"
        f"{_DISPUTE_TOKEN} <finding-id>` and public counter-evidence; a disputed "
        "finding stops forcing a round. Otherwise apply the fix and finish with a "
        "DONE line."
    )
    if report_path:
        lines.append(f"\nFull audit report: {report_path}")
    return "\n".join(lines)


async def run_reviewer_audit(
    *,
    interface: Any,
    task_prompt: str,
    snapshot_path: str,
    round_index: int,
    model: str,
    summary_model: str,
    tools: list,
    registry: Any,
    parent_session_dir: Path,
    max_steps: int,
    thinking_params: dict[str, Any] | None,
    summary_runtime: Any | None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> tuple[ReviewerVerdict, AgentUsage, str]:
    """Run one fresh, independent audit pass and return (verdict, usage, raw).

    The auditor is a fresh sub-agent (``memory_store=None``, its own registry,
    restricted read+exec toolset) — it shares nothing with the writer beyond the
    public task surface and a read-only snapshot of output/. Argus runs a fresh
    reviewer every round for exactly this anti-anchoring reason.
    """
    task = build_audit_task(
        task_prompt=task_prompt, snapshot_path=snapshot_path, round_index=round_index,
    )
    text, usage = await _run_fresh_agent(
        label=f"reviewer-audit-{round_index}",
        task=task,
        system_prompt=REVIEWER_AUDIT_SYSTEM_PROMPT,
        model=model,
        summary_model=summary_model,
        tools=tools,
        registry=registry,
        parent_session_dir=parent_session_dir,
        max_steps=max_steps,
        thinking_params=thinking_params,
        summary_runtime=summary_runtime,
        api_key=api_key,
        api_base=api_base,
    )
    verdict = parse_verdict(text)
    return verdict, usage, text


# Boyue is a shared, load-balanced Azure gateway. A transient overload surfaces
# — AFTER litellm's own in-call retries (num_retries=24, exp backoff) are
# exhausted — as one of these markers, killing the audit sub-agent's agentic
# loop and losing the whole audit (a "reviewer" run then silently degrades to a
# "base" run). Re-running the entire fresh audit after a cooldown recovers the
# common case where the gateway was briefly unavailable.
#
# Note on auth errors: the audit only runs AFTER the writer completed on the
# same endpoint/key, so a 401 / "invalid subscription key" reaching the audit is
# almost always a spurious gateway or key-rotation artifact (a genuinely bad key
# would have failed the writer and the whole run first). We therefore treat auth
# errors as transient and give them one cooldown-retry too.
_AUDIT_TRANSIENT_MARKERS = (
    "serviceunavailable", "service unavailable", "503", "overloaded",
    "timeout", "timed out", "429", "ratelimit", "rate limit", "rate_limit",
    "bad_response_status_code", "bad gateway", "502", "504",
    "connection error", "temporarily", "apiconnectionerror",
    # spurious-on-boyue auth (see note above)
    "authenticationerror", "invalid subscription key", "401", "invalid api key",
)
# Only genuine, self-reproducing exhaustion is terminal — retrying the same
# key/endpoint cannot help, so surface it fast (still fail-open, keeping writer
# output) rather than burning cooldowns.
_AUDIT_TERMINAL_MARKERS = (
    "insufficient_quota", "exceeded your current quota", "billing",
)


def _audit_error_is_transient(exc: Exception) -> bool:
    """True if re-running the whole audit could plausibly succeed. Unknown errors
    (e.g. a parser bug, not a gateway blip) default to non-transient — retrying
    would only waste cooldowns before the caller fails open anyway."""
    msg = str(exc).lower()
    if any(m in msg for m in _AUDIT_TERMINAL_MARKERS):
        return False
    return any(m in msg for m in _AUDIT_TRANSIENT_MARKERS)


async def run_reviewer_audit_with_retry(
    *,
    max_attempts: int = 3,
    base_cooldown_s: float = 20.0,
    **kwargs: Any,
) -> tuple[ReviewerVerdict, AgentUsage, str]:
    """``run_reviewer_audit`` + whole-audit retry on TRANSIENT gateway failures.

    The per-call retry budget (num_retries=24) lives *inside* each LLM call; when
    it is exhausted the whole agentic audit dies. Because the audit is a fresh,
    stateless sub-agent, the clean recovery unit is the entire audit, not a
    mid-session resume — so this re-runs it after an escalating cooldown with
    jitter (so concurrent tasks do not re-hit the gateway in lockstep). Terminal
    auth/quota errors are re-raised immediately: retrying the same bad
    key/endpoint only wastes wall-clock. The caller still fails open on the final
    raise, so the writer's output is never lost."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await run_reviewer_audit(**kwargs)
        except Exception as exc:  # noqa: BLE001 — classify, then retry or surface
            last_exc = exc
            transient = _audit_error_is_transient(exc)
            if not transient or attempt == max_attempts:
                logger.warning(
                    "reviewer audit attempt %d/%d failed (%s); surfacing: %s",
                    attempt, max_attempts,
                    "transient budget exhausted" if transient else "terminal, not retrying",
                    exc,
                )
                raise
            cooldown = base_cooldown_s * attempt + random.uniform(0.0, base_cooldown_s * 0.5)
            logger.warning(
                "reviewer audit attempt %d/%d hit transient gateway error (%s); "
                "cooling down %.0fs then re-running the whole audit",
                attempt, max_attempts, exc, cooldown,
            )
            await asyncio.sleep(cooldown)
    assert last_exc is not None  # unreachable; loop either returns or raises
    raise last_exc


def reviewer_audit_protocol_digest() -> str:
    """Content hash of the audit protocol (prompt + counter set), for the audit
    trail — a content digest, not a hand-incremented version number."""
    import hashlib

    material = REVIEWER_AUDIT_SYSTEM_PROMPT + "|" + ",".join(COUNTER_NAMES)
    return "reviewer-audit-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
