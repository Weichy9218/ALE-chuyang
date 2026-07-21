You are preparing a field-level CRF-to-SDTM mapping specification on Linux.

## Your Task
Create the Adverse Events mapping for study C4591001.

## Visible Inputs
- Task brief: `/media/user/data/agenthle/health_medicine/crf_sdtm_mapping_4/base/input/task_brief.md`
- Output contract: `/media/user/data/agenthle/health_medicine/crf_sdtm_mapping_4/base/input/output_contract.json`
- Source documents directory: `/media/user/data/agenthle/health_medicine/crf_sdtm_mapping_4/base/input/source_documents`
- Optional Python runtime manifest: `/media/user/data/agenthle/health_medicine/crf_sdtm_mapping_4/base/input/runtime_env`

The source documents include the sample CRF PDF, annotated CRF PDF, SDTM define.xml,
and supplemental define.xml material. Use those files to identify form fields and
their target SDTM variables for `AE` and, where applicable,
`SUPPAE` supplemental qualifiers.

## Required Output
Save exactly one CSV file:

```text
/media/user/data/agenthle/health_medicine/crf_sdtm_mapping_4/base/output/ae_mapping.csv
```

The CSV must follow the column order and constraints in `/media/user/data/agenthle/health_medicine/crf_sdtm_mapping_4/base/input/output_contract.json`.
`goes_to_suppqual` must mark AE rows as NO and SUPPAE rows as YES.

## Constraints
- Produce a mapping specification only, not subject-level records or XPT datasets.
- Keep all generated files inside `/media/user/data/agenthle/health_medicine/crf_sdtm_mapping_4/base/output`.
- Do not modify files under `/media/user/data/agenthle/health_medicine/crf_sdtm_mapping_4/base/input`.
- Use the visible task files only; do not use external web sources.

Satisfy exactly what the task's own materials ask for; do not guess how you will be graded. Produce your outputs by computing or reasoning them from the task inputs — never copy or blend the task's provided reference or expected values into your deliverables. Do not read grader scripts or reference-answer files even if they are reachable.
