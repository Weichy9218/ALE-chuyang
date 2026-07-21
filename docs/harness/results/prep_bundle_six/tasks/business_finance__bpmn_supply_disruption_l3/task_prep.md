# Task-specific prep bundle

Authority: supplemental. The task prompt and `/input` always take precedence over this report and every bundled artifact. Confidence describes evidence strength, not priority. Recheck before use; ignore or edit prep output when task-local evidence contradicts it.
Network policy: allowed (default:no explicit prohibition).

## Focus: Topological form-property producer validation [contract_checker]

- Task basis: `input/task_prompt.md#Data flow topology rule` - “For each new task's `in_*` form property, traces the BPMN sequence-flow graph to verify a matching `out_*` producer exists on a topological predecessor.”
- Blocker: A matching process variable name is insufficient: every new user task input must be paired with a producer that precedes the consumer in the sequence-flow graph, which is difficult to verify reliably across branches, joins, and loops by inspection.
- Increment: A portable, read-only checker identifies new user tasks relative to the original BPMN, normalizes matching `in_name`/`out_name` properties, computes sequence-flow reachability, and emits per-input JSON findings with candidate and reachable producer IDs.
- Task relation: supplements
- Decision impact: It informs whether the solver must add or reroute producer tasks and convergence paths before finalizing the BPMN data-flow design.

## Deliverables

### D1. Topological data-flow checker [artifact]
- Observation: The checker returns exit code 1 and an explicit finding when a new user task has an `in_*` form property without a matching reachable `out_*` producer; a synthetic `in_missing_probe` test produced one finding and exit code 1.
- Applies if: Use after a candidate modified BPMN exists and the staged original BPMN is available for distinguishing original user-task IDs from new user-task IDs.
- Do not infer: A zero exit code does not establish full evaluator compliance, runtime variable initialization, branch-sensitive guaranteed execution, type compatibility, or correctness of any JSON deliverable.
- Evidence:
  - Source [task_local]: `input/task_prompt.md#Evaluation Method, section E` - “For each new task's `in_*` form property, traces the BPMN sequence-flow graph to verify a matching `out_*` producer exists on a topological predecessor.”
  - Source [task_local]: `input/task_prompt.md#Data flow topology rule` - “If task B consumes `in_foo`, there must be a task A with `out_foo` such that A is reachable from the start event and B is reachable from A by following sequence flows forward.”
  - Source [runtime_observation]: `runtime:probe` - Artifact SHA-256 a70fdfc25d5528aa481cb757fea562571a20fe84e94e65c910fc1308bcdb7179; synthetic new task with `in_missing_probe` yielded `unmatched_count: 1` and exit code 1.
- Artifact: `artifacts/topological_dataflow_check.py`
- Recheck: python3 task_prep/artifacts/topological_dataflow_check.py output/modified_process.bpmn20.xml --original input/starter_project/original_process.bpmn20.xml
- Expected signal: JSON reports `new_task_inputs_checked`, `unmatched_count`, and one finding per checked input; exit code 0 means no unmatched input was found within the checker's stated scope, exit code 1 means at least one unmatched input, and exit code 2 means a usage or parse error.
- Confidence: high
