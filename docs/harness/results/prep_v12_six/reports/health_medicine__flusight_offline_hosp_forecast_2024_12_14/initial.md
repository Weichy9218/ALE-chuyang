# Task-specific working prior

The task prompt and `/input` are authoritative. This file is an editable prior-knowledge supplement, not a task requirement, answer, coverage claim, or proof of correctness. Recheck evidence before use; revise or remove an entry when later research contradicts it.
Network policy: prohibited (input/task_prompt.md#lines 10-11).

## Priority knowledge

### 1. Interior missing observations in three jurisdictions [failure_mode]
- Input gap: The prompt and schema do not disclose whether the historical value series is complete or explain how missing observations should be handled.
- Claim: There are 36 rows where both value and weekly_rate are blank: 17 for Massachusetts (25), 14 for Minnesota (27), and 5 for West Virginia (54). These are interior gaps rather than absent rows, while all three series resume afterward. Any lag, seasonal-lag, residual, or backtest calculation must handle these blanks explicitly rather than silently propagating NaNs or treating them as zero.
- Evidence:
  - Source: `input/historical_weekly_hospital_admissions_asof_2024-12-14.csv#blank value/weekly_rate rows for locations 25, 27, and 54 (including lines 3271-3287, 3571-3584, and 7337-7341)` - Blank observations occur during 2024-05-18 through 2024-10-05 in Massachusetts and Minnesota and during 2024-09-07 through 2024-10-05 in West Virginia; the file contains 36 blank value fields in total.
  - Source: `runtime:python3 csv scan grouping rows with value == '' and weekly_rate == ''` - Observed 36 blank value rows and 36 blank weekly_rate rows, confined to location 25 (17), 27 (14), and 54 (5); each location still has 150 dated rows at uninterrupted 7-day spacing.
- Solver use: Before fitting or backtesting, assert finite inputs for every training window. Either use only complete windows or apply an explicit task-local imputation strategy; do not convert these blanks to hospitalization counts of zero. Recheck seasonal lags that cross the affected dates.
- Risk if ignored: Model fitting may return NaN forecasts, drop different numbers of observations by jurisdiction, or interpret missing reports as genuine zero admissions, distorting fitted dynamics and interval calibration.
- Recheck: Read the CSV with location forced to string, count value.isna() by location, and print the missing dates; then assert that every array passed to a model or error-calibration routine is finite.
- Confidence: high

## Writer updates

- None yet.
