# Task-specific working prior

The task prompt and `/input` are authoritative. This file is an editable prior-knowledge supplement, not a task requirement, answer, coverage claim, or proof of correctness. Recheck evidence before use; revise or remove an entry when later research contradicts it.

## Priority knowledge

### 1. Interior missing values are not zeros [failure_mode]
- Input gap: The prompt does not identify which series contain missing observations or distinguish those gaps from reported zero admissions.
- Claim: The snapshot has 36 rows where both value and weekly_rate are missing: 17 for Massachusetts (25), 14 for Minnesota (27), and 5 for West Virginia (54). These are interior gaps, while all 53 series still extend through 2024-12-14. Preserve missingness during fitting rather than converting it to zero; use an estimator with explicit missing-data handling or an auditable imputation confined to model inputs.
- Evidence:
  - Source: `input/historical_weekly_hospital_admissions_asof_2024-12-14.csv#lines 3271-3291, 3571-3591, 7341` - Representative Massachusetts and Minnesota rows have empty value and weekly_rate fields; West Virginia is empty on 2024-10-05, whereas earlier rows such as 2024-05-18 are explicitly 0.0.
  - Source: `runtime:python3 pandas groupby count/isna probe on historical_weekly_hospital_admissions_asof_2024-12-14.csv` - Observed 7,950 rows, 53 locations, 36 missing values; missing counts were 25:17, 27:14, 54:5, and every location's maximum date was 2024-12-14.
- Solver use: Before fitting or constructing lags, inspect each location's missing mask. Ensure interpolation, rolling windows, and loss calculations do not silently treat NaN as zero or drop an entire location. Recheck that the latest usable observation remains 2024-12-14 for every series.
- Risk if ignored: Zero-filling creates artificial troughs and rebounds, especially in Massachusetts and Minnesota; unhandled NaNs can propagate to forecasts or cause rows to be silently omitted.
- Recheck: Load location as text, print rows with value.isna(), and assert that missingness is exactly 36 rows across codes 25, 27, and 54; separately count explicit value == 0 rows.
- Confidence: high

### 2. US history is not the exact sum of states and DC [local_conflict]
- Input gap: The materials require a US row but do not establish whether its historical values are arithmetically coherent with the 50 states plus DC.
- Claim: The supplied US series differs from the same-date sum of the 50 states and DC. On 2024-12-14 the jurisdiction sum is 8,414 versus US 8,793, and differences also occur historically. Do not force state forecasts to reconcile to the US series unless a task-local backtest demonstrates benefit; forecast the required US row independently if needed.
- Evidence:
  - Source: `runtime:python3 pandas pivot and sum over all locations except US and 72` - For complete dates, state-plus-DC minus US had median -44 and ranged from -435 to -3; on 2024-12-14 it was -379 (8,414 versus 8,793).
  - Source: `input/TASK_INSTRUCTIONS.md#Scoring` - The primary WIS, coverage tie-breaker, and point-MAE tie-breaker all explicitly exclude the aggregate US row.
- Solver use: Keep jurisdiction model selection and interval calibration independent of any US reconciliation constraint. Still produce the contract-required US rows, but validate them separately rather than altering scored jurisdiction forecasts to make totals match.
- Risk if ignored: A forced coherence step can systematically distort all 52 scored jurisdiction forecasts to match an aggregate that is not coherent with their supplied histories, while gaining nothing directly on the stated primary metric.
- Recheck: For each complete historical date, compare US value with the sum over the exact required state/DC codes excluding 72; falsify this finding if all differences are zero.
- Confidence: high

### 3. Raw one-week growth features encounter zeros and isolated jumps [failure_mode]
- Input gap: The prompt does not warn that recent jurisdiction histories contain explicit zeros and abrupt one-week reversals that make ratios or log growth undefined or extreme.
- Claim: Several recent series contain zero denominators or isolated jumps, such as Minnesota 0→88→0 and Ohio 11→229→17. Any ratio/log-growth extrapolator must explicitly guard zero denominators and non-finite values; it should not be used merely because it fits the latest jump without a rolling task-local backtest against a named simple baseline.
- Evidence:
  - Source: `input/historical_weekly_hospital_admissions_asof_2024-12-14.csv#lines 3592-3595 and 5392-5395` - Minnesota values for 2024-10-12 through 2024-11-02 are 0, 88, 0, 4; Ohio values are 1, 11, 229, 17 over the same dates.
- Solver use: If growth features are considered, assert all model inputs and outputs are finite, define behavior at zero explicitly, and compare the guarded method with a persistence or recent-level baseline over multiple historical cutoffs and all four horizons.
- Risk if ignored: Division by zero can yield infinity/NaN, while extrapolating an isolated jump can generate implausibly large forecasts and intervals that nevertheless pass the non-negative integer schema checks.
- Recheck: Compute consecutive ratios with floating-point warnings enabled, list non-finite ratios, and inspect the largest absolute one-week changes before fitting; reject the feature path if finite guards or backtest gains are absent.
- Confidence: high

## Writer updates

- Rechecked the reported missingness behavior during modeling: all series had a latest observation at 2024-12-14, and interior gaps were interpolated only as model inputs rather than interpreted as zero.
- Used independently forecast jurisdiction series without forcing reconciliation to US, consistent with the documented historical incoherence and scoring exclusion.
- Guarded log-trend calculations with a positive floor and clipped weekly growth; combined damped recent trend with a scaled prior-season trajectory after rolling seasonal-cutoff backtesting.
