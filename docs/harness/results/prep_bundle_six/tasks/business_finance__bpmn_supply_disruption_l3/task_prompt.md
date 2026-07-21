You are working on a Linux VM with Docker, Docker Compose, Python, and curl available.

## Your Task
Redesign LY Juice Company's monthly production scheduling workflow in Flowable BPMN 6.5.0 so it handles a compound disruption:
1. raw material supply shortage
2. incoming material quality hold

## Visible Inputs
- task prompt: `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/input/task_prompt.md`
- starter project directory: `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/input/starter_project`
- original BPMN: `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/input/starter_project/original_process.bpmn20.xml`
- disruption scenario: `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/input/starter_project/disruption_scenario_L3.md`
- business rules: `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/input/starter_project/business_rules_L3.md`
- org hierarchy: `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/input/starter_project/org_hierarchy.json`
- scenario suite: `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/input/starter_project/test_scenarios_L3.json`
- Flowable stack file: `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/input/starter_project/docker-compose.yml`
- original diagram: `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/input/starter_project/original_process_diagram.png`

## What You Must Do
1. Read the staged task materials.
2. Modify the BPMN while preserving original anchored elements and IDs.
3. Use process definition key `monthlyProductionScheduling_modified_L3`.
4. Start or reuse the local Flowable stack from `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/input/starter_project/docker-compose.yml`.
5. Deploy the modified BPMN and validate it against the provided scenario definitions.
6. Write the final output bundle to `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/output`.

## Runtime Notes
- Flowable REST API base URL: `http://localhost:8080/flowable-task/process-api/`
- Flowable credentials: `admin` / `test`
- For runtime testing, set role assignee variables to `admin`
- Ensure every gateway or assignee expression only references variables that already exist
- Keep new manual work as `userTask` nodes and use `${...}` expressions for gateway logic

## Required Output Files
- `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/output/modified_process.bpmn20.xml`
- `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/output/structural_changes.json`
- `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/output/business_rules_compliance.json`
- `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/output/test_results.json`

You may also write `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/output/deployment_log.json` as an optional diagnostic artifact.

## Evaluation Method
Your output is scored by a **static structural evaluator** that parses the BPMN XML directly — it does NOT re-run Flowable. The evaluator checks structural topology, test results, compliance cross-validation, anti-gaming, data flow, and role coupling. Each section is weighted; partial credit is given. Read the full evaluation details and **required output schemas** (including the exact JSON format for `test_results.json`) in `/media/user/data/agenthle/business_finance/bpmn_supply_disruption_l3/base/input/task_prompt.md`.

## Data Flow Topology Rule
Every new task's `in_*` form property must have a matching `out_*` producer on a **topological predecessor** in the sequence-flow graph. The evaluator traces BFS paths, not Flowable's global variable scope.

## Important Constraints
- Do not modify the staged input files
- Keep successful exception handling paths rejoined into the main workflow
- Send last-resort escalation to a separate terminal end event
- Keep the JSON artifacts consistent with the BPMN you actually produced

Satisfy exactly what the task's own materials ask for; do not guess how you will be graded. Produce your outputs by computing or reasoning them from the task inputs — never copy or blend the task's provided reference or expected values into your deliverables. Do not read grader scripts or reference-answer files even if they are reachable.
