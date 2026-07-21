# Task-specific working prior

The task prompt and `/input` are authoritative. This file is an editable prior-knowledge supplement, not a task requirement, answer, coverage claim, or proof of correctness. Recheck evidence before use; revise or remove an entry when later research contradicts it.

## Priority knowledge

### 1. Resolve SUPPAE qualifiers through QVAL value-level metadata [failure_mode]
- Input gap: The prompt requires AE-related SUPPAE mappings but does not explain that qualifier-specific names and origins are represented under the generic SUPPAE.QVAL value list rather than as ordinary SUPPAE ItemGroup variables.
- Claim: Do not derive candidate SUPPAE rows solely from the SUPPAE ItemGroupDef, which exposes structural variables such as QNAM and QVAL. Traverse IT.SUPPAE.QVAL's ValueListRef and each referenced WhereClauseDef; the WhereClause CheckValue is the qualifier QNAM, while the value-level ItemDef supplies its label and origin.
- Evidence:
  - Source: `input/source_documents/sdtm_define.xml#ItemDef OID="IT.SUPPAE.QVAL" and ValueListDef OID="VL.SUPPAE.QVAL"` - IT.SUPPAE.QVAL references VL.SUPPAE.QVAL. Its ItemRefs are conditioned on QNAM CheckValue values (for example AECMGIV, AENDGIV, AEMERES, AERELTXT, and AESUBJDC), with qualifier-specific descriptions and CRF origins.
  - Source: `input/source_documents/annotated_crf.pdf#C4591001 ADVERSE EVENT REPORT, pages labeled 10-11 of 131` - Annotations explicitly use forms such as “AEMERES in SUPPAE,” “AERELTXT in SUPPAE,” “AECMGIV in SUPPAE,” “AENDGIV in SUPPAE,” and “AESUBJDC in SUPPAE,” confirming that QNAM—not the generic QVAL variable name—is the output identifier.
- Solver use: When parsing define.xml, join ValueListDef ItemRefs to their WhereClauseDefs and emit the exact QNAM as sdtm_variable, then cross-check each candidate against the AE form annotation before including it.
- Risk if ignored: A flat ItemGroup parser can omit the actual supplemental qualifiers or incorrectly emit QVAL/QNAM as mapped variables, causing multiple missing or invalid rows.
- Recheck: For every proposed SUPPAE sdtm_variable, locate an exact QNAM CheckValue in VL.SUPPAE.QVAL and confirm the same name is attached to an AE-form field in the annotated CRF.
- Confidence: high

### 2. Parent date origins are blank because origin is conditional [failure_mode]
- Input gap: The task does not explain why the parent AE date ItemDefs lack Origin elements or that their origins are supplied through category-conditioned value lists.
- Claim: For variables with a def:ValueListRef, do not interpret a blank parent Origin as unknown. AESTDTC and AEENDTC have separate value-level branches conditioned on whether AECAT equals REACTOGENICITY, with Assigned on one branch and CRF on the other; select the branch applicable to the mapped form using the exact local condition.
- Evidence:
  - Source: `input/source_documents/sdtm_define.xml#ItemDefs IT.AE.AESTDTC and IT.AE.AEENDTC; ValueListDefs VL.AE.AESTDTC and VL.AE.AEENDTC` - Both parent ItemDefs reference value lists and contain no parent def:Origin. Each value list has an AECAT EQ REACTOGENICITY item with Origin Type="Assigned" and an AECAT NE REACTOGENICITY item with Origin Type="CRF".
  - Source: `input/source_documents/annotated_crf.pdf#C4591001 ADVERSE EVENT REPORT, page labeled 10 of 131` - The form shows Category annotated to AECAT and directly annotates Start Date Time to AESTDTC and End Date Time to AEENDTC, providing the local evidence needed to evaluate the define.xml branch.
- Solver use: Whenever an ItemDef has a ValueListRef, resolve its WhereClause against the exact form context before populating origin or mapping logic; preserve the task’s stated origin convention when formatting the CSV.
- Risk if ignored: The solver may leave origins blank or assign the reactogenicity branch to ordinary adverse-event fields, producing subtle column mismatches despite correct variable names.
- Recheck: Inspect each mapped variable’s ItemDef for def:ValueListRef; if present, enumerate all referenced WhereClauseDefs and verify exactly one condition matches the source-form context.
- Confidence: high

### 3. Do not copy define.xml ItemRef Role into the CSV role column [local_conflict]
- Input gap: The contract asks for a role column but does not define its full vocabulary or a translation from define.xml ItemRef Role values.
- Claim: The define.xml ItemRef Role attribute represents conformance status (Req/Exp/Perm), not the semantic mapping role illustrated by the contract. At minimum, do not mechanically place Req, Exp, or Perm in the CSV role field; derive semantic roles from the task’s example and variable function, and avoid inventing unsupported terminology.
- Evidence:
  - Source: `input/output_contract.json#example_row and column "role"` - The example assigns AETERM the role "Topic".
  - Source: `input/source_documents/sdtm_define.xml#ItemGroupDef OID="IG.AE", ItemRef ItemOID="IT.AE.AETERM"` - The same AETERM reference has Role="Req", demonstrating that the XML Role attribute and the output contract’s role value are different concepts.
- Solver use: Treat XML Role as metadata useful for conformance, not as the output role. Validate AETERM against the explicit Topic example and apply only a consistent semantic-role scheme supported by local evidence to other rows.
- Risk if ignored: Every otherwise-correct row could receive Req/Exp/Perm in a column expected to contain semantic roles, sharply reducing exact-column matches.
- Recheck: Compare the proposed AETERM role with both the contract example and its XML ItemRef; if the extraction pipeline returns Req, it is reading the wrong role concept.
- Confidence: high

## Open questions

### Q1. What complete semantic vocabulary is expected in the CSV role column beyond the explicitly illustrated AETERM value Topic?
- Unresolved because: The output contract provides one example, while define.xml supplies only the incompatible conformance statuses Req/Exp/Perm; external SDTM sources are expressly prohibited.
- Safe handling: Do not substitute ItemRef conformance status. Infer roles conservatively from variable function and internal examples, keep terminology consistent, and do not claim that the local files define an exhaustive role taxonomy.

## Writer updates

- None yet.
