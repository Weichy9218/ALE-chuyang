You are acting as a regulatory consultant on Shanghai Stock Exchange Northbound programmatic-trading reporting.

## Closed-Book Rule

- Use only the staged materials under `/media/user/data/agenthle/business_finance/sse_northbound_programmatic_trading_01/base/input`.
- Do not use outside web search or external regulatory knowledge.

## Inputs

- Task brief: `/media/user/data/agenthle/business_finance/sse_northbound_programmatic_trading_01/base/input/task_brief.md`
- Question set: `/media/user/data/agenthle/business_finance/sse_northbound_programmatic_trading_01/base/input/question_set.json`
- Output contract: `/media/user/data/agenthle/business_finance/sse_northbound_programmatic_trading_01/base/input/output_contract.json`
- Document manifest: `/media/user/data/agenthle/business_finance/sse_northbound_programmatic_trading_01/base/input/document_manifest.json`
- Original source files: `/media/user/data/agenthle/business_finance/sse_northbound_programmatic_trading_01/base/input/source_documents`
- Extracted UTF-8 text mirrors: `/media/user/data/agenthle/business_finance/sse_northbound_programmatic_trading_01/base/input/extracted_text`

## Your Task

Answer the three client questions in the staged brief:

1. whether leverage-related information must be reported separately through each broker for same-LEI accounts;
2. whether the staged rules provide specific numerical amounts for `流量费` and `撤单费`;
3. whether a French firm can report using only the original foreign-language software name.

## Deliverable

Write exactly one JSON file here:

- `/media/user/data/agenthle/business_finance/sse_northbound_programmatic_trading_01/base/output/research_answers.json`

Each top-level question key must contain:

- `conclusion`: exactly `Yes`, `No`, or `Unknown`
- `citation_document`: the Simplified Chinese source document name you rely on
- `evidence_snippet`: an exact Simplified Chinese excerpt copied from the staged source
- `answer_text`: a short English explanation

Satisfy exactly what the task's own materials ask for; do not guess how you will be graded. Produce your outputs by computing or reasoning them from the task inputs — never copy or blend the task's provided reference or expected values into your deliverables. Do not read grader scripts or reference-answer files even if they are reachable.
