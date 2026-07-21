# Task Prep v1 behavior audit

All cells below are `mean / median / p75` across the 26 tasks. `solver time` subtracts an uncached prep registry duration from the agent-active event interval; cached prep has zero measured research time.

| arm | active s | solver s | LLM turns | tools | run steps | input tokens | score |
|---|---:|---:|---:|---:|---:|---:|---:|
| new_prep | 903.6 / 757.0 / 1127.8 | 688.7 / 566.5 / 893.5 | 10.0 / 7.5 / 12.0 | 14.7 / 13.0 / 21.0 | 24.6 / 20.5 / 33.0 | 181697.3 / 124629.5 / 262236.8 | 0.6 / 0.8 / 1.0 |
| new_skills | 1082.7 / 860.5 / 1316.8 | 1082.7 / 860.5 / 1316.8 | 13.9 / 11.0 / 15.0 | 20.3 / 16.0 / 27.8 | 34.3 / 26.5 / 43.0 | 302424.3 / 210918.0 / 342859.8 | 0.6 / 0.6 / 1.0 |
| new_combined | 1088.8 / 892.5 / 1263.2 | 944.7 / 725.7 / 954.7 | 12.0 / 10.5 / 13.2 | 16.4 / 12.5 / 19.8 | 28.4 / 23.0 / 34.8 | 245857.7 / 157478.5 / 290561.5 | 0.6 / 0.7 / 1.0 |

## Prep

- Instances: 52; uncached research sessions: 42; unique fingerprints: 26.
- Statuses: completed=49, failed=3.
- Truncated injected reports: 19/52 instances, 12/26 unique reports.
- Uncached prep duration s: 222.3 / 207.4 / 266.5; LLM turns: 7.9 / 8.0 / 9.0; tools: 15.0 / 14.0 / 18.0.
- Uncached prep input tokens: 232472.6 / 180921.5 / 317258.2; output tokens: 4273.3 / 4051.5 / 5304.0; aggregate tools: analyze_image=15, exec=527, read=18, web_fetch=34, web_search=35.
- Full report chars: 3451.5 / 3518.0 / 4113.0; lost chars: 319.6 / 258.0 / 508.5 among measurable truncated reports.

## Skills

- Skill-enabled tasks: 52; load counts: deliverable-contract=48, evidence-audit=4.
- `memory_get` calls: 52; `memory_search` calls: 0.
- Skill loaded in solver turn 0: 49/52 tasks.

See `per_task.csv` for tool breakdowns, exact trigger turns, and CT rows.
