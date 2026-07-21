You are working on a Linux VM to produce a FluSight-style offline influenza hospitalization forecast.

Visible task files:
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/task_prompt.md`
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/output_contract.json`
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/TASK_INSTRUCTIONS.md`
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/forecast_output_schema.md`
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/forecast_output_template.csv`
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/historical_weekly_hospital_admissions_asof_2024-12-14.csv`
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/locations.csv`
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/source_provenance.md`
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/runtime_env/pyproject.toml`
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/runtime_env/uv.lock`
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/software/bootstrap_runtime.sh`
- `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/software/python_with_task_deps.sh`

What you must do:
1. Read `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/task_prompt.md` and `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/output_contract.json` first.
2. Use the archived historical snapshot in `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input/historical_weekly_hospital_admissions_asof_2024-12-14.csv` to forecast weekly admissions for the 53 required jurisdictions and four required target weeks.
3. Fill the staged template contract exactly and write one final file under `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/output`:
   - `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/output/submission.csv`
4. If you want the staged Python environment, materialize it with `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/software/bootstrap_runtime.sh` and run Python with `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/software/python_with_task_deps.sh`.

Rules:
- Do not use the internet or external files.
- Do not modify files under `/media/user/data/agenthle/health_medicine/flusight_offline_hosp_forecast_2024_12_14/base/input`.
- Output must contain exactly 212 rows with the required columns and integer constraints.
- Write only the required `submission.csv` into the writable output directory.

Satisfy exactly what the task's own materials ask for; do not guess how you will be graded. Produce your outputs by computing or reasoning them from the task inputs — never copy or blend the task's provided reference or expected values into your deliverables. Do not read grader scripts or reference-answer files even if they are reachable.
