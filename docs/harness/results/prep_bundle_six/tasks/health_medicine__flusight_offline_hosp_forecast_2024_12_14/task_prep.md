# Task-specific prep bundle

Authority: supplemental. The task prompt and `/input` always take precedence over this report and every bundled artifact. Confidence describes evidence strength, not priority. Recheck before use; ignore or edit prep output when task-local evidence contradicts it.
Network policy: prohibited (task_prompt).

## Focus: Deterministic historical-panel gap and blank-value index [input_index]

- Task basis: `task_prompt` - Use the archived historical snapshot in `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/historical_weekly_hospital_admissions_asof_2024-12-14.csv` to forecast weekly admissions for the 53 required jurisdictions and four required target weeks.
- Blocker: Ordinary inspection does not reliably distinguish absent weekly rows from present rows whose numeric observations are blank across the 7,950-row, 53-location panel; either condition can silently alter training windows and backtests.
- Increment: A portable read-only Python index hashes the input, checks duplicate location-date keys and missing calendar weeks, and reports blank-value runs by jurisdiction without selecting an imputation or modeling policy.
- Task relation: supplements
- Decision impact: Informs whether the solver must explicitly handle missing observations before using complete-case numeric fitting or rolling-origin backtests.

## Deliverables

### D1. Historical gap index [artifact]
- Observation: For the validated snapshot (SHA-256 `61c165879482bb0c8b77865006037db442198752542c9ecf08753a5cb9d54d30`), all 53 locations have 150 weekly rows with no absent calendar weeks or duplicate location-date keys, but 36 present rows have blank `value` and `weekly_rate`: Massachusetts (`25`) has 17, Minnesota (`27`) has 14, and West Virginia (`54`) has 5.
- Applies if: Applies when fitting or backtesting from `historical_weekly_hospital_admissions_asof_2024-12-14.csv`, especially when a library may reject, propagate, or silently drop blank numeric observations.
- Do not infer: Do not infer an imputation, deletion, zero-filling, jurisdiction-exclusion, forecast, interval, or scoring policy from the detected blanks; the artifact only locates and characterizes input integrity conditions.
- Evidence:
  - Source [task_local]: `input/historical_weekly_hospital_admissions_asof_2024-12-14.csv#header and all location-date rows` - Validated file has SHA-256 `61c165879482bb0c8b77865006037db442198752542c9ecf08753a5cb9d54d30`, 7,950 rows, 53 locations, one `as_of` value (`2024-12-14`), zero duplicate location-date keys, zero absent weekly dates within location spans, and 36 blank numeric rows concentrated in locations 25, 27, and 54.
- Artifact: `artifacts/history_gap_index.py`
- Recheck: python3 task_prep/artifacts/history_gap_index.py input/historical_weekly_hospital_admissions_asof_2024-12-14.csv
- Expected signal: JSON reports the stated SHA-256, `row_count: 7950`, `location_count: 53`, `duplicate_location_date_keys: 0`, an empty `locations_with_absent_weeks`, and blank-value counts of 17 for `25`, 14 for `27`, and 5 for `54`; a changed snapshot or panel structure falsifies one or more signals.
- Confidence: high
