---
name: deliverable-contract
description: Use when visible task materials define mechanically observable requirements for generated artifacts, such as files, schemas, row or key sets, types, invariants, deterministic reruns, or executable behavior. Do not use to judge forecast or model quality without a public oracle, or for prose conclusions whose main risk is evidence coverage.
---

# Validate the observable public contract

1. Read the task's schemas, templates, examples, and runnable validation assets. List only requirements that can be observed in the final artifacts.

2. Reuse a shipped validator when available. Add the smallest temporary checks needed for uncovered explicit requirements, and run them against the final artifacts.

3. When public source evidence or an oracle exists, check semantics too: recompute derived values, trace submitted values to their source, or execute the artifact. Shape-only checks do not establish content correctness.

4. Separate `checked`, `failed`, and `unverifiable` criteria. A passing schema does not verify hidden future outcomes, source truth that was not checked, or subjective quality. Never present a proxy as a conclusive pass.

5. Fix observed failures and rerun the affected checks. Keep temporary checks outside required output locations unless the task explicitly requests them.
