---
name: deliverable-contract
description: Use when the task asks you to PRODUCE or COMPUTE something whose correctness can be checked mechanically — output files with a required schema/format/counts/fields, code, a model or workflow that must run, numeric results, data transforms. Do NOT use for read-and-judge work where the answer is a written judgement with nothing runnable to produce (use evidence-audit for that).
---

# Extract the acceptance criteria, then make them a check you run

This is a general method, not rules for any specific task. Everything below comes from the task's own visible materials, never from a grader or a reference answer. The failure these tasks punish most is finishing on output that is "almost right" — one required element missing, one field off. A written intention to be thorough does not catch that; a check you actually run does.

1. Extract the task's own acceptance criteria into an explicit checklist. The task states them: the exact files you must produce, required schema, counts, fields, naming, and the rules or constraints the output must satisfy. Many tasks hand you the checklist directly — an enforcement list, a rubric table, required-topic list, or a shipped test scenario. Enumerate every criterion and quote the sentence it comes from, so none is dropped. This checklist is the contract.

2. Make the checklist runnable. Turn the criteria into something that gives a pass/fail verdict on your own output:
   - If the task ships something runnable against your output (a server, a compose file, a test scenario file, a validation script you may run on your OWN work), run it.
   - Otherwise write a small checker (e.g. `verify.py`) that parses your output files and asserts each criterion: every required file exists, the schema/counts/fields hold, every required element or topic is present and reachable, cross-file ids resolve. One assertion per checklist item.
   - Build the checker only from the task's stated criteria and general domain knowledge. It is legitimate because it comes from the same public materials the task gave you.

3. Do not finish until every check passes. Build in dependency order; after each part, run the checker, read what fails, fix, and re-run. A checklist item with no check written yet, or a check that fails, means the work is not done — do not declare completion on unverified output. Re-scan the task text for any stated criterion your checker does not yet cover, and cover it.

4. Leave the check as evidence. Keep the checker and its passing output alongside your deliverables so the result is inspectable and you can see at a glance that every criterion is green.

Boundaries: derive every criterion and every check only from the task's own materials; use the task's own vocabulary; do not read grader scripts or reference-answer files even if reachable (during your run the reference is not on the machine anyway); do not invent a criterion the task did not state. If a stated criterion is genuinely unverifiable after real effort, say so specifically rather than quietly skipping it. You have this method now — apply it; no need to re-read this file mid-task.
