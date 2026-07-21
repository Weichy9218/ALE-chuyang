# Task-specific prep bundle

Authority: supplemental. The task prompt and `/input` always take precedence over this report and every bundled artifact. Confidence describes evidence strength, not priority. Recheck before use; ignore or edit prep output when task-local evidence contradicts it.
Network policy: allowed (default:no explicit prohibition).

## Focus: Cross-file grading-output consistency [contract_checker]

- Task basis: `input/starter_project/output_contract.json#required_outputs,grades_csv_header,error_tags_csv_header,manifest_required_keys` - The contract declares five required outputs, exact CSV headers, and required manifest keys.
- Blocker: The output contract, rubric point limits and tags, submission-derived IDs, per-student feedback keys, and grade totals are distributed across multiple files, making consistent manual verification error-prone.
- Increment: A portable read-only checker joins those authorities and reports missing or extra files, malformed headers, student-ID drift, duplicate grade IDs, out-of-range part scores, inconsistent totals, unknown error tags, feedback-key mismatches, diagnostic feedback word-count excesses, missing manifest keys, and an empty summary.
- Task relation: supplements
- Decision impact: Informs whether the writer can rely on direct manual output or should add a deterministic validation pass before finalization.

## Deliverables

### D1. Grading output contract checker [artifact]
- Observation: The checker accepted the starter-generated structural baseline with zero findings and detected a deliberately altered S01 total as inconsistent with its part-score sum.
- Applies if: A candidate output directory contains, or is intended to contain, the five task-required deliverables and the task root retains the released rubric, Markdown submissions, and starter output contract.
- Do not infer: Zero findings does not establish grading correctness, adequate feedback substance, complete contract coverage, or correctness of error-tag choices; the reported word count uses a deterministic diagnostic tokenizer because the rubric does not define word tokenization.
- Evidence:
  - Source [task_local]: `input/starter_project/output_contract.json#required_outputs,grades_csv_header,error_tags_csv_header,manifest_required_keys` - Declares the five filenames, exact CSV headers, and manifest keys checked by the artifact.
  - Source [task_local]: `input/released/rubric.json#problems,error_tags,feedback_style` - Declares part maxima 2.0, 3.0, 2.0, and 3.0; seven rubric error-tag names; and max_words_per_student 70.
  - Source [task_local]: `input/TASK_PROMPT.md#Rules` - “Keep student IDs stable across every output file.”
  - Source [runtime_observation]: `runtime:probe` - Artifact SHA-256 285b1d09f033c402f61925d6751eca0678aa9e799e369db20dde854dfe7eca1b; baseline run printed findings=0, while changing S01 total_score from 0.00 to 1.00 printed exactly one total-versus-part-sum finding and exited 1.
- Artifact: `artifacts/check_output_contract.py`
- Recheck: software/python task_prep/artifacts/check_output_contract.py . output
- Expected signal: Prints CHECKED with the submission-derived student IDs and a findings count; each detected inconsistency is printed as FINDING, with exit status 0 when none are found and 1 when findings exist.
- Confidence: high
