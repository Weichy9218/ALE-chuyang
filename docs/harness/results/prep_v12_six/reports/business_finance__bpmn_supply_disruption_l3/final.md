# Task-specific working prior

The task prompt and `/input` are authoritative. This file is an editable prior-knowledge supplement, not a task requirement, answer, coverage claim, or proof of correctness. Recheck evidence before use; revise or remove an entry when later research contradicts it.
Network policy: allowed (default:no explicit prohibition).

## Priority knowledge

### 1. Overlapping exclusive-gateway conditions are resolved by XML order [failure_mode]
- Input gap: The task requires a 30% cost variance to trigger Finance review and then Executive escalation, but does not establish how Flowable chooses among simultaneously true exclusive-gateway conditions such as cost_variance_pct > 15 and cost_variance_pct > 25.
- Claim: Flowable evaluates exclusive-gateway outgoing flows in XML definition order and selects only the first true flow. Therefore, overlapping >15 and >25 branches cannot independently trigger both approvals from one exclusive gateway. Model mutually exclusive tiers—for example, >25 routed through Finance then Executive, and >15 && <=25 routed through Finance only—or use an explicitly synchronized structure that guarantees both steps.
- Evidence:
  - Source: `https://www.flowable.com/open-source/docs/bpmn/ch07b-BPMN-Constructs` - Official Flowable documentation states that an exclusive gateway evaluates outgoing sequence flows in definition order; if multiple conditions are true, only the first defined flow is selected. It also states that a default flow is selected only when no other flow can be selected and that conditions on a default flow are ignored.
- Solver use: Inspect the cost-tier gateway predicates and their XML order. Probe exact boundary values 15, just above 15, 25, and just above 25; confirm the >25 route visits Finance before Executive and the middle tier never reaches Executive. Keep the default sequence flow condition-free as required locally.
- Risk if ignored: At 30%, both >15 and >25 evaluate true but only one branch runs, silently omitting either Finance review or Executive escalation; an unconditional/default-like flow placed first can also swallow all later conditions.
- Recheck: Deploy a minimal or final definition and run one instance with cost_variance_pct=20 and one with 30; compare historic activity IDs. Also inspect sequence-flow order and assert predicates are pairwise disjoint except for the intended default.
- Confidence: high

### 2. A boundary timer requires the async executor to fire [runtime_behavior]
- Input gap: The BPMN rules specify an interrupting 48-hour boundary timer, but neither the prompt nor docker-compose.yml explicitly confirms that the deployed engine's async executor is active or explains the runtime prerequisite for timer firing.
- Claim: Flowable timer boundary events fire only when the async executor is enabled. The correct interrupting XML is a boundaryEvent attached to the inspection task with cancelActivity="true" and an ISO-8601 duration PT48H; when fired it cancels the inspection and follows the boundary flow. Runtime validation must first confirm timer/job execution is active rather than treating a non-firing timer as a routing defect.
- Evidence:
  - Source: `https://www.flowable.com/open-source/docs/bpmn/ch07b-BPMN-Constructs` - Official documentation says a timer duration uses ISO 8601, shows `<boundaryEvent ... cancelActivity="true">` with `<timeDuration>PT4H</timeDuration>`, states that firing interrupts the attached activity, and notes that boundary timers fire only when `asyncExecutorActivate` is true.
  - Source: `input/starter_project/docker-compose.yml#services.flowable` - The stack pins `flowable/all-in-one:6.5.0` but supplies only `JAVA_OPTS=-Xmx1g`; it does not explicitly set or document `asyncExecutorActivate`.
- Solver use: Use PT48H and cancelActivity="true", with the expedited task directly downstream (or within the locally allowed two-flow distance). After stack startup, verify that the timer creates an executable timer job and that the executor processes jobs before relying on timeout scenario results. Do not weaken the BPMN timer merely to compensate for stack configuration.
- Risk if ignored: The normal inspection path may wait indefinitely during runtime testing, producing a false failure for S46–S48 and S65–S67 even when the boundary topology is correct; using cancelActivity="false" would leave both inspection and expedited paths active.
- Recheck: Start an instance and pause at inspection; query management/job state or temporarily deploy an equivalent short-duration timer, then confirm the inspection task disappears and only the boundary path advances. Check container logs/configuration if the timer remains due but unexecuted.
- Confidence: high

## Writer updates

- None yet.
