# Task-specific working prior

The task prompt and `/input` are authoritative. This file is an editable prior-knowledge supplement, not a task requirement, answer, coverage claim, or proof of correctness. Recheck evidence before use; revise or remove an entry when later research contradicts it.

## Priority knowledge

### 1. Cost-tier routing can make the >25% branch unreachable [failure_mode]
- Input gap: The inputs require numeric 15% and 25% tiers but do not establish Flowable's selection behavior when multiple exclusive-gateway conditions are simultaneously true.
- Claim: Flowable evaluates exclusive-gateway flows in XML order and takes only the first true flow. Therefore, at a single gateway, placing `${cost_variance_pct > 15}` before `${cost_variance_pct > 25}` makes the >25% route unreachable. Use non-overlapping conditions or, preferably for the required sequential approvals, route all >15% cases through Finance and test >25% at a downstream gateway after Finance review.
- Evidence:
  - Source: `https://www.flowable.com/open-source/docs/bpmn/ch07b-BPMN-Constructs` - The Exclusive Gateway section states that outgoing flows are evaluated in definition order and, if multiple conditions are true, only the first flow defined in the XML is selected. It also states that a default flow is selected only when no other flow is selected and its condition is ignored.
- Solver use: Inspect the actual XML order and topology for cost routing. Probe 15, a value just above 15, 25, and a value just above 25; verify >25 executes Finance review followed by executive cost escalation, while 15 and 25 themselves follow the task's strict 'exceeding' wording.
- Risk if ignored: A 30% case may execute only Finance review, leaving the executive tier structurally or operationally unreachable and failing path-sensitivity, Rule 21, and scenario S64 checks.
- Recheck: Deploy a minimal or completed model, complete sourcing with numeric variances 15, 15.01, 25, and 25.01, and compare historic activity IDs. Also statically check that no broader condition precedes an overlapping narrower condition at an XOR gateway.
- Confidence: high

### 2. Inclusive gateways synchronize tokens, not merely true business flags [failure_mode]
- Input gap: The materials require an inclusive adjustment merge for overlapping triggers but do not explain how Flowable decides which incoming branches an inclusive join waits for.
- Claim: A Flowable inclusive join waits for each incoming branch that actually has a process token; it does not independently infer simultaneous supply, quality, and capacity triggers from variables. Model the upstream execution so all required assessments occur and active trigger paths are genuinely activated, or consolidate already-produced trigger variables before one adjustment route. Do not expect several sequential XOR branches feeding an inclusive gateway to prove or preserve overlap by themselves.
- Evidence:
  - Source: `https://www.flowable.com/open-source/docs/bpmn/ch07b-BPMN-Constructs` - The Inclusive Gateway section says an inclusive split may take more than one true outgoing flow, and the join waits until an execution has arrived for each incoming sequence flow that has a process token; it waits only for incoming flows that will be executed.
- Solver use: Trace S29, S45, and S53 token-by-token. Confirm sourcing failure does not bypass mandatory quality inspection or prevent capacity-trigger information from reaching the common adjustment path, and confirm only one mix-adjustment instance is created for a compound trigger set.
- Risk if ignored: The model can appear to have three arrows into an inclusive merge yet process only the first detected trigger, skip later gates, duplicate the mix task, or deadlock while waiting for a branch that was never correctly paired.
- Recheck: For each dual/triple-trigger case, mark every activated outgoing branch from each split and every token expected at the join. Runtime-test one single-trigger and one triple-trigger instance, checking that the join releases and the mix task appears exactly once.
- Confidence: high

### 3. One assignee or candidate list does not enforce joint waiver approval [failure_mode]
- Input gap: The task requires joint QA Lead and Supply Chain Lead sign-off but does not establish whether assigning one Flowable user task to multiple candidates creates an all-participants quorum.
- Claim: A Flowable user task has only one assignee. Candidate users or groups are potential owners; one candidate can claim and complete the task, so a comma-separated candidate list does not enforce approval by both roles. If runtime joint sign-off must be genuine, represent the two decisions as independent user-task executions joined before evaluating both verdicts, while keeping IDs, role metadata, and compliance documentation aligned with the task's static expectations.
- Evidence:
  - Source: `https://www.flowable.com/open-source/docs/bpmn/ch07b-BPMN-Constructs` - The User Assignment section states: 'Only one user can be assigned as the human performer for the task.' It describes candidate users/groups as potential owners rather than an all-candidates approval mechanism.
  - Source: `https://www.flowable.com/open-source/docs/bpmn/ch07a-BPMN-Introduction` - The documentation explains that a group-assigned task is visible to every member, but once one member claims it that user becomes the assignee and can complete it; the task disappears from the other candidates' task lists.
- Solver use: Distinguish discoverability from quorum enforcement. For the Grade B waiver, ensure the topology or explicit decision data demonstrates both QA and Supply Chain approval before acceptance, rather than relying solely on candidateUsers/candidateGroups metadata.
- Risk if ignored: A single actor could accept Grade B material unilaterally even though the XML appears to mention both roles, violating Rule 12 and potentially failing role-data coupling or runtime governance validation.
- Recheck: Start a Grade B instance and inspect the waiver task's assignee and identity links. Claim and complete it as only one candidate; if the process proceeds without a second independent approval/verdict, joint sign-off is not enforced.
- Confidence: high

## Writer updates

- None yet.
