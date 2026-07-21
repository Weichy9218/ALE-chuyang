You are a digital marketing analyst performing audience segmentation for a re-engagement campaign.

## Task Directory
`/media/user/data/agenthle/business_finance/digital_marketing_audience_segmentation_1/base`

## Your Task
1. Read the segmentation brief at `/media/user/data/agenthle/business_finance/digital_marketing_audience_segmentation_1/base/input/segmentation_brief.md` and the governance policies at `/media/user/data/agenthle/business_finance/digital_marketing_audience_segmentation_1/base/input/governance_policies.yaml`. Use `/media/user/data/agenthle/business_finance/digital_marketing_audience_segmentation_1/base/input/data_dictionary.tsv` for field reference.
2. Load customer profiles from `/media/user/data/agenthle/business_finance/digital_marketing_audience_segmentation_1/base/input/unified_profiles.parquet`.
3. Identify customers matching the target criteria in the brief (high-transaction but email-disengaged).
4. Apply governance rules: suppress customers with active support tickets, respect channel opt-in/opt-out, compute per-customer SMS and push eligibility.
5. Strip geo/demographic identifier columns (age, gender, city, state) from the output roster for PII compliance.
6. Analyze overlap between the qualifying audience and each existing audience in `/media/user/data/agenthle/business_finance/digital_marketing_audience_segmentation_1/base/input/existing_audiences.csv`.
7. Produce three output files.

## Output Files
Save all files to `/media/user/data/agenthle/business_finance/digital_marketing_audience_segmentation_1/base/output/`:

**`segment_definition.json`** — JSON object with keys:
- `segment_name`: descriptive name
- `created_date`: date string
- `version`: version string
- `filter_predicates`: list of {field, operator, value}
- `suppression_rules`: list of {field, operator, value, reason}
- `activation_channels`: mapping of channel name → {eligibility_field, required_value}
- `governance_applied`: {pii_fields_removed: [...], opt_out_compliance: bool, support_suppression: bool}
- `audience_stats`: {total_qualifying, sms_eligible, push_eligible, any_channel_eligible, pct_of_total_profiles}

**`audience_roster.csv`** — CSV, one row per qualifying customer after suppression. Include customer_id and profile/engagement columns, but exclude age, gender, city, state. Add columns: `sms_eligible`, `push_eligible`, `any_channel_eligible` (1 or 0).

**`overlap_report.tsv`** — TSV with columns: existing_audience_id, existing_audience_name, overlap_count, overlap_pct, flag_high_overlap. One row per existing audience. overlap_pct = (overlap_count / total qualifying audience size) * 100.

## Environment
Python 3.12 and `uv` are available on this machine. A dependency manifest is at `/media/user/data/agenthle/business_finance/digital_marketing_audience_segmentation_1/base/input/runtime_env/pyproject.toml`. Install with: `cd /media/user/data/agenthle/business_finance/digital_marketing_audience_segmentation_1/base/input/runtime_env && uv sync`
Then run scripts with: `uv run --project /media/user/data/agenthle/business_finance/digital_marketing_audience_segmentation_1/base/input/runtime_env python your_script.py`

Satisfy exactly what the task's own materials ask for; do not guess how you will be graded. Produce your outputs by computing or reasoning them from the task inputs — never copy or blend the task's provided reference or expected values into your deliverables. Do not read grader scripts or reference-answer files even if they are reachable.
