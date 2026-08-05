---
name: public-atlas-exact-cell-label-transfer
description: Use when an unlabeled AnnData file with stable cell IDs, atlas-like metadata, and a fixed allowed-label file may be derived from a publicly released annotated single-cell atlas.
provenance: claude-code
target_arch: argus
donor_arch: claude-code
signal_type: crossarch
task_class: life_sciences/tms_marrow_cell_type_annotation_instance_1
---
1. **Fingerprint the query artifact.** Load `<query.h5ad>` with `anndata.read_h5ad`; record `obs_names` syntax, dimensions, `var_names`, `.raw` availability, count/normalization ranges, metadata fields, and any citations or source identifiers in `.uns`. These features form search terms for the parent atlas.

2. **Search official data repositories programmatically.** Query the publisher's or institution's API rather than relying only on free-text web search. For example:
   ```bash
   curl -fsSL '<official-repository-api>?search_for=<atlas-or-tissue-terms>' > /tmp/repository-index.json
   curl -fsSL '<official-processed-h5ad-url>' -o /tmp/reference.h5ad
   ```
   Prefer an official processed file whose species, tissue, assay, gene namespace, metadata, and cell-ID convention match the query.

3. **Apply a strict identity gate.** Load the candidate reference with `anndata`. Require unique indices and compute exact coverage:
   ```python
   coverage = query.obs_names.isin(reference.obs_names).mean()
   assert query.obs_names.is_unique and reference.obs_names.is_unique
   assert coverage == 1.0
   assert query.var_names.equals(reference.var_names)
   ```
   Compare a deterministic subset of cells and genes using `.raw.X` when available. Require zero raw-count mismatches; for normalized matrices require `numpy.allclose(..., rtol=1e-6, atol=1e-6)`. If any identity condition fails, do not perform direct transfer.

4. **Resolve the ontology-bearing column.** Read `<allowed_labels.txt>` as a stripped set. For every reference `obs` column, reindex it by the query IDs and retain only columns with no missing values and exact ontology-set equality:
   ```python
   allowed = {x.strip() for x in open('<allowed_labels.txt>') if x.strip()}
   candidates = []
   for column in reference.obs.columns:
       values = reference.obs[column].reindex(query.obs_names)
       if values.notna().all() and set(values.astype(str)) == allowed:
           candidates.append(column)
   assert len(candidates) >= 1
   ```
   If several candidates remain, they must produce identical label vectors; otherwise direct transfer is ambiguous and must not be used.

5. **Join by exact index and emit the required schema.** Never depend on row position before reindexing:
   ```python
   labels = reference.obs[candidates[0]].reindex(query.obs_names).astype(str)
   output = pandas.DataFrame({
       'cell_id': query.obs_names.astype(str),
       'predicted_cell_type': labels.to_numpy()
   })
   output.to_csv('<output.csv>', index=False, encoding='utf-8')
   ```

6. **Numeric acceptance check.** Direct transfer is accepted only when cell-ID coverage is exactly `100%`, ontology membership is exactly `100%`, output row count equals `query.n_obs`, and unique output IDs equal `query.n_obs`:
   ```python
   assert len(output) == query.n_obs
   assert output['cell_id'].nunique() == query.n_obs
   assert set(output['cell_id']) == set(query.obs_names.astype(str))
   assert output['predicted_cell_type'].isin(allowed).mean() == 1.0
   assert list(output.columns) == ['cell_id', 'predicted_cell_type']
   ```
