# Task-specific prep bundle

Authority: supplemental. The task prompt and `/input` always take precedence over this report and every bundled artifact. Confidence describes evidence strength, not priority. Recheck before use; ignore or edit prep output when task-local evidence contradicts it.
Network policy: allowed (default:no explicit prohibition).

## Focus: Resolve existing-audience definition fields against available profile fields [input_index]

- Task basis: `input/existing_audiences.csv#AUD-005` - AUD-005,Cart Abandoners,has_cart_abandonment = 1 AND recency_days < 7,623
- Blocker: The overlap task cross-links free-text audience definitions with the Parquet schema and field dictionary; AUD-005 may require a field that is not available, which changes whether all overlaps can be computed by predicate evaluation.
- Increment: A portable read-only indexer extracts unquoted identifiers from every existing-audience definition and deterministically reports whether each occurs in the profile schema and data dictionary.
- Task relation: supplements
- Decision impact: Informs whether the solver can use one uniform predicate-evaluation method for every existing audience or must separately recognize an unevaluable definition.

## Deliverables

### D1. Audience-definition field resolver [artifact]
- Observation: Across the supplied six definitions, the resolver finds ten distinct audience-field references by row; only AUD-005's has_cart_abandonment reference is absent from both the 25-field Parquet schema and the data dictionary, while its recency_days reference is present.
- Applies if: Applies when overlap membership is to be derived from the definitions in existing_audiences.csv against unified_profiles.parquet and the supplied dictionary.
- Do not infer: Do not infer an overlap value, substitute value, omission rule, or treatment for AUD-005; field absence alone does not authorize any handling policy.
- Evidence:
  - Source [task_local]: `input/existing_audiences.csv#AUD-005` - Definition is "has_cart_abandonment = 1 AND recency_days < 7".
  - Source [task_local]: `input/data_dictionary.tsv#field_name column` - The listed fields include recency_days but do not include has_cart_abandonment.
  - Source [runtime_observation]: `runtime:probe` - PyArrow schema inspection reports 25 profile fields, has_cart_abandonment present: False, and 10,000 rows; unified_profiles.parquet SHA-256 is eeab6b6ccae27e6f9bb1cf29b2e51b43443b98253d18bb47991ec536280dd297.
- Artifact: `artifacts/audience_definition_field_index.py`
- Recheck: uv run --project input/runtime_env python task_prep/artifacts/audience_definition_field_index.py input/unified_profiles.parquet input/existing_audiences.csv input/data_dictionary.tsv
- Expected signal: The TSV row for AUD-005 and has_cart_abandonment ends with "0\t0"; all other emitted field-reference rows end with "1\t1". Artifact SHA-256 is 8640fcc63e8760d11bd8202abdd63a9cf6ca68e33d3f4498e2b6a7a4a0386cba.
- Confidence: high
