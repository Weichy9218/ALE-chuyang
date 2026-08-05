# The `reviewer` arm — independent, source-grounded delivery audit + hard zero-discrepancy gate

This document describes the new `reviewer` harness arm: a faithful, minimal port
of **argus's Reviewer role** onto the single-agent ale_claw solver. It is the
WS1 deliverable ("mimic argus by building an isolated, renamed, high-value
harness arm that integrates argus's true essence — an independent, source-grounded
Reviewer audit + hard zero-discrepancy gate").

It is **isolated and coexists** with the base solver and the earlier prep/verifier
arms: turning it off (`reviewer_audit: false`, the default) reproduces the base
byte-for-byte. It is registered in `harness/run/launch.py` ARMS so it is
A/B-comparable against `base` with the same task list, model, and budgets.

---

## 1. What it does (and why it is not the verifier)

After the writer produces its deliverable, the `reviewer` arm runs an **independent
audit sub-agent** and gates completion on its verdict:

1. **Fresh, isolated auditor.** A brand-new sub-agent (`memory_store=None`, its own
   `SubagentRegistry`, restricted read/exec toolset) that never saw the writer's
   reasoning, code, or transcript. It **re-derives; it does not re-read the claim.**
   A fresh auditor is spawned *every* round (argus's anti-anchoring discipline).
2. **Read-only snapshot.** The writer's `output/` is copied into an immutable,
   hashed snapshot (symlinks stripped, `chmod a-w`, double tree-hash). The auditor
   reads the deliverable from there; the source is verified unchanged.
3. **Instruction is the sole contract.** The auditor enumerates the mandatory
   outputs/hard gates from the *original task instruction* and audits against that —
   never against the writer's narrative or a merely-correctly-named file.
4. **Independent recompute, cell by cell.** For every semantic field it can
   **deterministically recompute from the public inputs** (`input/`, `software/`),
   the auditor computes the correct value with its own script and compares cell by
   cell. It confirms reported values actually come from the outputs of required
   sims/renders/builds, not from a guess.
5. **Reject proxies → NA.** A field whose correct value is *not* deterministically
   groundable from public materials (needs an undefined threshold/tolerance/tie-break,
   a proxy, a sample, or an external fact) is **never guessed**. It is recorded under
   `not_verified` (NA), left OUT of the gate, and always reported back to the writer
   as an explicit boundary.
6. **Hard zero-discrepancy gate.** Every confirmed defect is tallied into one of five
   named counters. The run may finish **only when every counter is zero over the
   complete bundle.** This gate is enforced *in code* (`ReviewerVerdict.gate_passes`),
   not left to the model's self-report — a `done` verdict with any standing finding
   is mechanically coerced to `continue`, and the writer gets a source-grounded
   repair round.

The named counters:

| counter | fires when |
|---|---|
| `missing_required` | a mandatory output/field/artifact is absent |
| `unparseable_artifacts` | named but corrupt/empty/all-null/placeholder/invalid |
| `field_mismatches` | the auditor's recompute-from-source disagreed with a written cell |
| `contradictions` | stale export / cross-artifact contradictory values |
| `stale_or_unfinished` | a required sim/render/build/export did not truly finish |

### Contrast with the existing `verifier` arm

The `verifier` (`verifier.py`) is deliberately a **zero-authority advisory** reviewer:
`blocking` is forced false everywhere, it never emits a pass/fail verdict, and it
does not re-derive semantic values — it measures schema/contract conformance and
surfaces feedback the writer may ignore. That design was a deliberate retreat from
an earlier hard gate (see `docs/harness/VERIFIER.md`) that broke because it tried to
prove *source-implication* — an ambiguous, gameable semantic judgement.

The `reviewer` arm takes the opposite stance **only on the subset that is
deterministically recomputable from public inputs**, and only there. The gate fires
on *facts* (a deterministic recompute disagreed), never on an ambiguous relevance
judgement — which is exactly the failure mode the old hard gate died on. Everything
not deterministically groundable stays advisory (`not_verified`/NA), honoring the
verifier's hard-won lessons. See §4.

---

## 2. argus essence checklist — ported vs. not ported

Source studied: `argus-skill-main/argus_skill/verticals/ale_last_exam/skills/reviewer/
ale-last-exam-delivery-review.md` (the 7-step audit playbook), `roles/prompts/reviewer.py`
(the Reviewer system prompt + fresh-session-per-round + executable file/shell tools +
reject-weak-proxies), `roles/task_contract.py` (`EFFECTIVE_TASK_CONTRACT` authority
ladder).

### PORTED (the transferable moat)

| argus mechanism | where it lives now |
|---|---|
| Independent audit before exit; **instruction as the sole contract** | `REVIEWER_AUDIT_SYSTEM_PROMPT` (CONTRACT + PROTOCOL) |
| **Don't award completion from the engineer/writer narrative** | prompt: "you did not write this … must not trust any narrative claim" |
| Reopen/parse each artifact with an **independent check** (corrupt/empty/all-null/placeholder fails) | protocol steps 2–3 → `unparseable_artifacts` |
| **Independently recompute** each groundable field, cell-by-cell, from raw inputs | protocol step 4 (GROUNDING RULE) → `field_mismatches` |
| Values must come from actual sim/render/build **outputs**, not guesses | protocol step 4 → `stale_or_unfinished` |
| Cross-check for **stale/contradictory** values | protocol step 5 → `contradictions` |
| **Final hard-gate pass** over the whole bundle; `done` only after verifying it all | `gate_passes` / `effective_status` (mechanical) |
| **Reject weak proxies** → prefer NA over a fabricated expectation | GROUNDING RULE → `not_verified` list |
| **Fresh reviewer session each round** (anti-anchoring) | new auditor per round via `run_reviewer_audit` |
| Structured verdict (status + reason + next_action) | `ReviewerVerdict` JSON schema |
| Authority ladder (instruction + public materials outrank all) | `_AUTHORITY_LADDER`, ported from `EFFECTIVE_TASK_CONTRACT` |

### Hardened refinements (from the contrastive-mining memory notes)

Added on top of argus's own skill, per the `argus-edge-is-source-grounded-audit`
memory: **no-import oracle** (the auditor never imports the writer's pipeline),
**cell-by-cell semantic recompute**, **reject-proxy → null/NA**, and **named
zero-discrepancy counters**.

### NOT PORTED (argus-specific heavy machinery — deliberately left out)

| argus mechanism | why not |
|---|---|
| `codex exec` subprocess per role (Manager/Planner/Engineer/Reviewer/Scientist) | ale_claw is a single-agent harness; the audit is one in-process fresh sub-agent |
| Wheel-building / multi-role handoff / round orchestration (`loop.py`) | out of scope for a solver+audit arm; would be a different harness |
| Scientist/Distiller runtime skill authoring + Reviewer-edits-injected-skill | that is the *skills* lever (a separate WS), not the harness lever; and ALE ran with `require_post_task_learning=false` anyway |
| `operator_question` verdict field (human-in-the-loop) | no operator in the ALE run loop; `blocked` covers genuine external deps |
| top-k skill selection / `primary_skills[0]` injection judge | skills-lever concern, not this arm |

---

## 3. How to run the A/B (dry-run first — NO real run without authorization)

The entry point is the settings file `harness/run/settings_reviewer_ab.yaml`
(arms `[base, reviewer]`, everything else off, so a paired Δ isolates the audit gate).

**Dry-run (pure file generation — no API cost, no Docker), from the stack dir on the
run box `~/ale/agents-last-exam`:**

```bash
.venv/bin/python harness/run/launch.py --stack . \
    --settings harness/run/settings_reviewer_ab.yaml --per-arm
```

This regenerates `configs/agents/ale_claw_base.yaml` + `ale_claw_reviewer.yaml`,
**verifies each preset line-exactly** against the declared arm switches
(`verify_arm_preset` aborts on any mismatch), prints the arm matrix + resolved
budgets, prints the exact launch command, and **exits without running anything.**

**Real run (real API spend + Docker compute) — ONLY after operator authorization:**
append `--launch`. Then read results back with:

```bash
python3 harness/run/summarize.py .logs/ale/reviewer_ab --baseline ale_claw_base
```

Budgets (in the settings file): `reviewer.max_steps: 40` per fresh audit session,
`reviewer.max_rounds: 2` audit→repair rounds. Keep `max_turns` uncapped (COGNITION
forbids turn/time caps: an unequal budget manufactures fake effects). For a first A/B,
point `run.tasks` at a deliverable-heavy list — the gate only bites on tasks that
*have* recomputable semantic fields.

---

## 4. Reconciliation with COGNITION.md (the wcy failure-mode guards)

The spec ("hard zero-diff gate + repair loop") appears to contradict wcy's own hard
lessons (retired hard gates, disabled auto-repair). The resolution is baked into the
design:

- **The gate fires only on deterministic facts.** The old hard gate died proving
  ambiguous *source-implication*. This gate coerces `done→continue` **only** when a
  deterministic recompute-from-public-source disagreed with a written cell, or a
  required output is absent/corrupt/unfinished. Ambiguous/ungroundable fields are
  `not_verified`/NA and never gate.
- **Never reports all-clear.** Every feedback message declares the `not_verified`
  boundary explicitly ("these were NOT checked; they carry zero evidence either way"),
  so a clean/partial audit can never read as "all correct" — the exact trap where a
  base writer hit "155 passed" and quit.
- **Fail-open throughout.** A snapshot failure, an auditor crash, or an unparseable
  verdict never fails the unit: the loop ends on the writer's own last output. A parse
  error is fail-*closed* for the *decision* (never a silent pass) but fail-*open* for
  the *run* (bounded rounds).
- **Bounded rounds mitigate oscillation.** `reviewer_audit_max_rounds` (default 2) caps
  the audit→repair cycle; a no-output-change round short-circuits immediately. This is
  the guard against the auto-repair oscillation/mis-repair that wcy observed.
- **Anti-reference-leak.** The recomputed values in feedback come from **public**
  inputs (the writer's own pipeline should reproduce them); the anti-copy reminder from
  `invariant.txt` is repeated. The hidden reference/grader is unreachable by
  construction (staged only in Phase 3, after `launch()` returns) *and* denylisted in
  the auditor prompt (no grader/solution/reference/evaluator paths). No task answers,
  scoring thresholds, or deliverable filenames are hardcoded anywhere.
- **Writer keeps the last word.** A finding can be rejected with a line
  `AUDIT_DISPUTE <finding-id>` + public counter-evidence (mirrors the verifier's
  `VERIFIER_DISPUTE` protocol); a disputed finding stops counting against the gate.

---

## 5. Files changed / added

**New:**
- `ale_run/agents/ale_claw/reviewer_audit.py` — the audit engine: system prompt
  (ported playbook), `ReviewerVerdict` + the mechanical gate, `parse_verdict`,
  `run_reviewer_audit` (reuses `verifier._run_fresh_agent`), `build_audit_feedback_prompt`,
  `parse_audit_disputes`, `reviewer_audit_protocol_digest`.
- `harness/run/settings_reviewer_ab.yaml` — the base-vs-reviewer A/B entry point.
- `docs/harness/REVIEWER_AUDIT.md` — this file.

**Edited:**
- `config.py` — `reviewer_audit`, `reviewer_audit_model`, `reviewer_audit_max_steps`
  (default 40), `reviewer_audit_max_rounds` (default 2, validated 1..3).
- `deployer.py` — reviewer registry + state; the gated audit→repair branch (mirrors
  the verifier loop but with the fresh auditor + hard gate); `reviewer_audit_round_<n>.json`
  + `reviewer_audit_meta.json` outputs.
- `harness/run/launch.py` — `reviewer_audit` added to `ARM_SWITCHES`; `reviewer_audit=False`
  on every existing arm; new `reviewer` arm; reviewer budgets in `DEFAULTS` +
  `verify_arm_preset` expected lines + settings read + printout.
- `harness/run/presets.py` — `ale_claw_agent_yaml` emits the three reviewer config lines.

**Reused, not duplicated:** `verifier._run_fresh_agent` (fresh-context sub-agent,
`memory_store=None`, restricted tools), `verifier_runtime.snapshot_output` (read-only
hashed snapshot), `verifier_runtime.stage_verifier_report`, the history-rebuild helpers
(`build_replay_messages`/`sanitize_history`/`limit_history_turns`/`convert_to_responses_api_items`),
and the `_drive` closure for the repair re-entry.

**Note on the auditor toolset:** `_run_fresh_agent` pins the sub-agent to the verifier's
`read/exec/analyze_image` set; the generated preset lists `analyze_image` in
`disabled_tools`, so the auditor's *effective* tools are `read` + `exec` (reopen
artifacts + run independent recompute scripts). This is intentional and matches the
"no write on output/" boundary.
