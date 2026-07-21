# Task-specific working prior

The task prompt and `/input` are authoritative. This file is an editable prior-knowledge supplement, not a task requirement, answer, coverage claim, or proof of correctness. Recheck evidence before use; revise or remove an entry when later research contradicts it.
Network policy: allowed (default:no explicit prohibition).

## Priority knowledge

### 1. AUD-005 overlap cannot be evaluated from supplied fields [local_conflict]
- Input gap: The task requires overlap for every existing audience but does not specify how to handle an audience predicate whose field is absent from the customer profiles and data dictionary.
- Claim: AUD-005 uses `has_cart_abandonment = 1`, but `has_cart_abandonment` is absent from the Parquet schema and data dictionary. Do not silently interpret the missing field as false, substitute another field, or infer overlap from the audience's aggregate `size`; none of those operations is authorized by the inputs. A direct pandas query/eval will instead raise an undefined-variable error.
- Evidence:
  - Source: `runtime:UV_CACHE_DIR=/tmp/ale-task-prep-497454817a/uvcache uv run python schema inspection of ../unified_profiles.parquet and ../existing_audiences.csv under input/runtime_env` - Installed runtime resolved pandas 2.3.3 and pyarrow 16.1.0. The Parquet schema contains 25 fields and no `has_cart_abandonment`; AUD-005's definition is `has_cart_abandonment = 1 AND recency_days < 7`. The data dictionary likewise has no such field.
  - Source: `https://pandas.pydata.org/docs/reference/api/pandas.errors.UndefinedVariableError.html` - Official pandas documentation states that `UndefinedVariableError` is raised by `query` or `eval` when using an undefined variable name, with the example `df.query("A > x")` raising `UndefinedVariableError: name 'x' is not defined`.
- Solver use: Before evaluating audience definitions, validate every referenced field against the exact profile columns. Treat AUD-005 as an unresolved source-data conflict and avoid fabricating membership. If the required numeric TSV cannot represent an unavailable overlap, document the handling transparently rather than silently reporting a computed zero; still preserve the required one-row-per-audience structure to the extent the task contract permits.
- Risk if ignored: Automated expression evaluation may terminate before outputs are produced, or a silent fallback may report a false zero overlap for AUD-005 and make the overlap report materially misleading.
- Recheck: Extract identifiers from each audience definition and compare them with `set(pd.read_parquet(...).columns)` and the dictionary's `field_name` column; then run the AUD-005 expression on a copy to confirm that pandas raises `UndefinedVariableError`.
- Confidence: high

## Open questions

### Q1. What numeric overlap values should represent AUD-005 when its membership predicate is not computable from supplied data?
- Unresolved because: The inputs provide only an aggregate audience size, not member IDs or the missing predicate field, and define no unavailable-value convention for the numeric overlap columns.
- Safe handling: Do not infer membership or equate unavailable with zero. Make any unavoidable representation explicit and keep it isolated from the overlaps that are computable from supplied fields.

## Writer updates

- None yet.
