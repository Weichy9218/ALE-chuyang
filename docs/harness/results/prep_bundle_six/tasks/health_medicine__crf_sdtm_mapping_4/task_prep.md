# Task-specific prep bundle

Authority: supplemental. The task prompt and `/input` always take precedence over this report and every bundled artifact. Confidence describes evidence strength, not priority. Recheck before use; ignore or edit prep output when task-local evidence contradicts it.
Network policy: prohibited (task_prompt).

## Focus: Deterministic AE/SUPPAE metadata-to-aCRF locator [input_index]

- Task basis: `task_prompt` - The source documents include the sample CRF PDF, annotated CRF PDF, SDTM define.xml, and supplemental define.xml material. Use those files to identify form fields and their target SDTM variables for `AE` and, where applicable, `SUPPAE` supplemental qualifiers.
- Blocker: The annotated CRF has 131 pages, while SUPPAE qualifier names are encoded indirectly through VL.SUPPAE.QVAL ItemRefs, WhereClauseRefs, and QNAM CheckValue elements. Ordinary reading risks missing links or repeatedly searching unrelated pages.
- Increment: A portable read-only Python indexer resolves AE ItemRefs and SUPPAE QNAM value-list links from sdtm_define.xml, extracts exact token occurrences and PDF page numbers from annotated_crf.pdf, and emits a deterministic TSV for bounded human review.
- Task relation: supplements
- Decision impact: It informs whether the solver can review a finite metadata-derived candidate list with localized aCRF evidence instead of manually traversing the full XML and PDF.

## Deliverables

### D1. AE source-index builder [artifact]
- Observation: The script reproducibly resolves AE metadata and SUPPAE QNAM indirection, invokes pdftotext with layout preservation, and writes a TSV containing metadata attributes plus exact-token aCRF page occurrences.
- Applies if: The source directory contains files named sdtm_define.xml and annotated_crf.pdf, and the runtime provides Python 3 plus the pdftotext executable.
- Do not infer: A metadata entry or token occurrence is not proof that a row belongs in the final mapping, and absence of a token occurrence does not authorize omission or any mapping policy.
- Evidence:
  - Source [task_local]: `input/source_documents/sdtm_define.xml#ItemGroupDef[@SASDatasetName='AE']` - The AE ItemGroupDef contains 49 ordered ItemRef elements in the supplied file.
  - Source [task_local]: `input/source_documents/sdtm_define.xml#ValueListDef[@OID='VL.SUPPAE.QVAL']` - The value list contains eight ItemRefs whose WhereClauseRefs resolve to SUPPAE QNAM CheckValue values.
  - Source [task_local]: `input/source_documents/annotated_crf.pdf#document metadata` - The supplied annotated CRF has 131 pages and SHA-256 d90190802b3496ca90dce3872852a8907f086728351538584b1b710f96e130ed.
- Artifact: `artifacts/build_ae_source_index.py`
- Recheck: python3 task_prep/artifacts/build_ae_source_index.py input/source_documents task_prep/artifacts/recheck_ae_source_index.tsv
- Expected signal: The command prints indexed_rows=57, ae_rows=49, and suppae_qnams=8, then creates the requested TSV outside input/source_documents.
- Confidence: high

### D2. Prebuilt AE/SUPPAE candidate index [artifact]
- Observation: For the supplied inputs, the index has 57 rows: 49 AE metadata variables and eight SUPPAE QNAM candidates. Exact-token localization places AECMGIV, AENDGIV, and AESUBJDC on extracted PDF pages 12 and 70; AEMERES and AERELTXT on page 11; AEMEFL and AEAENO on page 70; and finds no exact DICTVER token.
- Applies if: The annotated_crf.pdf SHA-256 is d90190802b3496ca90dce3872852a8907f086728351538584b1b710f96e130ed and sdtm_define.xml SHA-256 is d38d1b823ee62b922cd0f9a3e04582994a83295416c6898df48b8821a96fd806.
- Do not infer: The listed candidates are not selected final mapping rows; page localization does not establish field labels, mapping rules, origins, controlled terms, or whether metadata-only variables should be included.
- Evidence:
  - Source [task_local]: `input/source_documents/sdtm_define.xml#ValueListDef[@OID='VL.SUPPAE.QVAL']` - Resolved QNAM CheckValue sequence: AECMGIV, DICTVER, AEMEFL, AEAENO, AENDGIV, AEMERES, AERELTXT, AESUBJDC.
  - Source [task_local]: `input/source_documents/annotated_crf.pdf#pages 11-12 and 70 in pdftotext extraction` - Exact standalone-token searches localize seven of the eight define-derived SUPPAE QNAMs; DICTVER has no exact occurrence.
- Artifact: `artifacts/ae_source_index.tsv`
- Recheck: python3 task_prep/artifacts/build_ae_source_index.py input/source_documents task_prep/artifacts/recheck_ae_source_index.tsv && cmp task_prep/artifacts/ae_source_index.tsv task_prep/artifacts/recheck_ae_source_index.tsv
- Expected signal: The builder reports 57 rows and cmp exits with status 0; the staged index SHA-256 is ba59277c3d94075e7dba70b759eb28ef3d0611fcf3dd0bc6403a5b391a83e397.
- Confidence: high
