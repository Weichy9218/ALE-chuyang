# Task-specific prep bundle

Authority: supplemental. The task prompt and `/input` always take precedence over this report and every bundled artifact. Confidence describes evidence strength, not priority. Recheck before use; ignore or edit prep output when task-local evidence contradicts it.
Network policy: prohibited (task_prompt#Closed-Book Rule).

## Focus: Manifest-resolved concordance for exact regulatory terms [input_index]

- Task basis: `task_prompt` - whether the staged rules provide specific numerical amounts for `流量费` and `撤单费`
- Blocker: The relevant terms must be located across ten extracted documents, then joined back to exact Simplified Chinese citation aliases; manual searching risks missing occurrences or citing an extract filename instead of a manifest-authorized document name.
- Increment: A portable, read-only Python concordance searches all UTF-8 text mirrors with literal OR semantics and emits deterministic TSV rows containing context, line and character offsets, nearby numeral tokens, manifest document metadata, citation aliases, and extract hashes.
- Task relation: supplements
- Decision impact: It informs whether the solver should inspect a small set of term-bearing passages for numerical fee language rather than infer amounts from unrelated numerical thresholds.

## Deliverables

### D1. Corpus concordance generator [artifact]
- Observation: On the staged corpus, a validated run for `流量费` and `撤单费` emits two occurrence rows plus the TSV header, with both occurrences manifest-resolved to doc_08 and line 115; the tool also exposes nearby numeral-like tokens for manual discrimination between article numbers, thresholds, and monetary amounts.
- Applies if: Use when locating literal Chinese terms in `input/extracted_text/*.txt` and resolving each hit through `input/document_manifest.json`.
- Do not infer: A hit count, nearby numeral token, or lack of a currency token does not by itself establish any conclusion, fee amount, completeness of synonymous terminology, legal interpretation, or required output handling.
- Evidence:
  - Source [task_local]: `input/question_set.json#questions[1]` - The staged question asks for "the specific numerical amounts of the flow fee and cancellation fee in the provided rules".
  - Source [task_local]: `input/document_manifest.json#doc_08` - doc_08 maps `extracted_text/程序化交易管理实施细则.txt` to the citation alias `上海证券交易所程序化交易管理实施细则`.
  - Source [runtime_observation]: `runtime:probe` - Validated artifact SHA-256: 924c5bdb2a11f6b5aad0c69249f3018fef9b81a6293fb4a9a2c3128a31159b14; validation command produced exactly 3 TSV lines: one header and two occurrence rows.
- Artifact: `artifacts/corpus_concordance.py`
- Recheck: python3 task_prep/artifacts/corpus_concordance.py input 流量费 撤单费 --context 160 | tee /tmp/fee_concordance.tsv && test "$(wc -l < /tmp/fee_concordance.tsv)" -eq 3 && grep -c $'doc_08\textracted_text/程序化交易管理实施细则.txt' /tmp/fee_concordance.tsv
- Expected signal: The line-count test succeeds and the final grep prints `2`; the two data rows include literal contexts, line/character locations, citation aliases, numeral-token JSON, and extract SHA-256 values.
- Confidence: high
