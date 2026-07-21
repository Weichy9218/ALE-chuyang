# Task-specific working prior

The task prompt and `/input` are authoritative. This file is an editable prior-knowledge supplement, not a task requirement, answer, coverage claim, or proof of correctness. Recheck evidence before use; revise or remove an entry when later research contradicts it.

## Priority knowledge

### 1. Embedded task path omits education_info [local_conflict]
- Input gap: The released TASK_PROMPT.md names a different absolute root from the public task prompt and the actually mounted task directory.
- Claim: Use the active public root ending in education_info/homework_grading_numerical_pdes_instance_02/base for all reads, the Python wrapper, and final output; the embedded education/... path does not exist in this runtime.
- Evidence:
  - Source: `input/TASK_PROMPT.md#lines 3-9,16,27` - The embedded paths use /media/user/data/agenthle/education/homework_grading_numerical_pdes_instance_02/base, omitting '_info'.
  - Source: `runtime:realpath .; test -d /media/user/data/agenthle/education/homework_grading_numerical_pdes_instance_02/base; test -d /media/user/data/agenthle/education_info/homework_grading_numerical_pdes_instance_02/base` - The active root resolved to /media/user/data/agenthle/education_info/homework_grading_numerical_pdes_instance_02/base; the education/... directory was MISSING and the education_info/... directory existed.
- Solver use: Resolve every path from the public active root and write the five deliverables only to its output directory. If scripting, invoke that root's software/python wrapper.
- Risk if ignored: Commands may fail or, if a similarly named directory later appears, deliverables may be written outside the evaluator's active output directory.
- Recheck: Run realpath on the working directory and test existence of both candidate roots immediately before reading or writing.
- Confidence: high

### 2. Specific arithmetic tag survives generic conceptual-error wording [local_conflict]
- Input gap: The protocol generically describes tags as major conceptual mistakes, while the rubric explicitly defines a tag for an arithmetic/substitution error; the materials do not state a precedence rule.
- Claim: Treat the rubric's exact enumerated tag definitions as the operational tag vocabulary, including wrong_dt_max when its stated arithmetic/substitution condition is met; do not suppress a defined tag solely because the protocol uses the generic word 'conceptual'.
- Evidence:
  - Source: `input/released/grading_protocol.md#lines 3-6` - Line 5 says: 'Assign major-error tags when the rubric indicates a conceptual mistake.'
  - Source: `input/released/rubric.json#lines 24-31` - The enumerated tag wrong_dt_max is defined as 'Arithmetic or substitution for dt_max is incorrect,' alongside the conceptual-error tags.
- Solver use: After scoring each part, compare observed errors directly against the seven exact rubric definitions and emit only matching identifiers in the two-column error-tags file.
- Risk if ignored: A rubric-defined arithmetic tag may be omitted, or unsupported free-form tags may be introduced, making tags inconsistent with the released rubric.
- Recheck: Check every emitted identifier against rubric.json and separately inspect incorrect numerical substitutions for applicability of wrong_dt_max.
- Confidence: high

## Open questions

### Q1. How should partial credit be allocated within each problem part?
- Unresolved because: The rubric supplies only maximum points and correctness descriptions; neither the protocol nor solution key gives deduction amounts or an all-or-nothing rule.
- Safe handling: Do not invent a hidden deduction table. Apply one explicit, consistent evidence-based policy across students, distinguish separable requested components where the prompt does so, and ensure each part stays within its stated maximum and totals equal the part sum.

## Writer updates

- Rechecked active root and all released materials. Applied a consistent component policy: in 1b, 2 points assess the restriction and 1 point the numerical value, with 1 point for correct dx^2/kappa scaling when the constant is wrong; in 2b, a(u,v), l(v), and the test space are 1 point each. A correct weak-form equality in 2a is not also penalized for an omitted space because the space is explicitly assessed in 2b.
