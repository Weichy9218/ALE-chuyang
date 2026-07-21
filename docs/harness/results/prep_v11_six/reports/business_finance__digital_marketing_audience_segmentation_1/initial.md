# Task-specific working prior

The task prompt and `/input` are authoritative. This file is an editable prior-knowledge supplement, not a task requirement, answer, coverage claim, or proof of correctness. Recheck evidence before use; revise or remove an entry when later research contradicts it.

## Priority knowledge

### 1. Existing-audience rows are definitions, not membership lists [failure_mode]
- Input gap: The task asks for customer-level overlap, but existing_audiences.csv supplies no member identifiers; one definition uses a field absent from both the profile schema and data dictionary, and the supplied size values do not consistently equal counts obtained by applying the other definitions to unified_profiles.parquet.
- Claim: Evaluate only definitions supported by exact profile fields and operators; do not treat the size column as overlap membership or fabricate has_cart_abandonment. The unsupported AUD-005 overlap cannot be derived from the supplied public data without an explicit rule.
- Evidence:
  - Source: `input/existing_audiences.csv#rows 2-7` - The file contains only audience_id, name, definition, and size. AUD-005 requires has_cart_abandonment = 1, while no customer membership column or separate membership file is present.
  - Source: `input/data_dictionary.tsv#field rows 2-26` - The complete documented profile field list has no has_cart_abandonment field; supported fields used by other definitions include state, ltv, recency_days, total_purchases, email_opens_30d, app_sessions_30d, has_app, and loyalty_tier.
- Solver use: Parse or encode each supported definition against unified_profiles.parquet, intersect its resulting customer_id set with the post-suppression qualifying set, and explicitly avoid silently converting the size metadata into membership. Handle AUD-005 conservatively pending clarification rather than inventing values.
- Risk if ignored: Using size as overlap_count can produce impossible overlaps and wrong percentages; treating the absent field as false yields an unjustified zero that looks valid and is difficult to detect.
- Recheck: Assert every identifier referenced in each definition exists in the parquet columns; independently recompute supported definition counts and compare them with the CSV size field to confirm that size is not reliable membership evidence.
- Confidence: high

### 2. Task-level PII removal is stricter than the YAML list [local_conflict]
- Input gap: The governance YAML's restricted_fields list omits state, whereas the public task explicitly requires removing age, gender, city, and state from the roster.
- Claim: Follow the task-level four-column removal requirement and remove state as well as age, gender, and city; do not generate the roster by dropping only governance_policies.yaml restricted_fields.
- Evidence:
  - Source: `input/governance_policies.yaml#PII Restriction restricted_fields` - The YAML lists only age, gender, and city as restricted_fields.
  - Source: `input/data_dictionary.tsv#rows 3-6` - age, gender, state, and city are all present profile columns, so state will remain in an automatic YAML-only drop unless separately removed.
- Solver use: Use an explicit required exclusion set containing all four task-named fields, and report the same four names under governance_applied.pii_fields_removed.
- Risk if ignored: The output roster leaks state and fails the explicit output contract even though a YAML-driven compliance check may appear to pass.
- Recheck: Reload audience_roster.csv and assert that none of {'age','gender','city','state'} occurs in its columns.
- Confidence: high

### 3. Default uv cache path is unwritable in the installed runtime [runtime_behavior]
- Input gap: The task gives a bare uv sync command but does not establish whether uv's default cache directory is writable in this machine's execution context.
- Claim: In the inspected runtime, bare uv sync fails before dependency setup because /home/user/.cache/uv cannot be created; point UV_CACHE_DIR to a writable scratch location when synchronization or uv run needs cache access.
- Evidence:
  - Source: `runtime:cd input/runtime_env && uv sync --quiet` - Command exited 2 with: Failed to initialize cache at /home/user/.cache/uv; failed to create directory; Permission denied (os error 13).
  - Source: `runtime:UV_CACHE_DIR=/tmp/ale-task-prep-497454817a/uvcache uv sync --quiet` - With a writable cache directory, synchronization completed and the project Python successfully loaded pandas and the parquet file.
- Solver use: Set UV_CACHE_DIR to a writable temporary directory before invoking uv, or use the already-created project environment if valid. This changes only execution plumbing, not task logic.
- Risk if ignored: The solver may fail before reading the parquet or producing any outputs despite correct analysis code.
- Recheck: Run uv cache dir and a minimal uv run python import of pandas and pyarrow under the intended environment; if the default path is writable in the solver process, the workaround is unnecessary.
- Confidence: high

## Open questions

### Q1. What percentage threshold defines flag_high_overlap?
- Unresolved because: The required overlap_report.tsv includes the flag, but neither the brief nor governance policy defines a high-overlap cutoff.
- Safe handling: Do not import an industry-standard threshold or infer one from Minimum Audience Size. If clarification is impossible, choose and disclose a deterministic assumption in the generating logic while keeping overlap_count and overlap_pct independently correct.

### Q2. Should email_opt_out=1 suppress the entire cross-channel roster for this campaign?
- Unresolved because: The brief excludes such customers from cross-channel messaging only when it references email content, but no campaign creative/content flag is supplied; channel policies otherwise define SMS and push eligibility only from their own opt-ins.
- Safe handling: Do not silently equate email opt-out with SMS/push opt-out. Keep the conditional brief rule explicit and avoid claiming that campaign content references email unless the task materials establish it.

## Writer updates

- None yet.
