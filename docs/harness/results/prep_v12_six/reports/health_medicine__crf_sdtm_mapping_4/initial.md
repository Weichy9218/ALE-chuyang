# Task-specific working prior

The task prompt and `/input` are authoritative. This file is an editable prior-knowledge supplement, not a task requirement, answer, coverage claim, or proof of correctness. Recheck evidence before use; revise or remove an entry when later research contradicts it.
Network policy: prohibited (task prompt#Constraints and input/task_brief.md#Input Files).

## Priority knowledge

### 1. supp_define.xml is an ADaM define, not a second SDTM define [local_conflict]
- Input gap: The prompt calls supp_define.xml “supplemental define.xml material” but does not disclose its standard or explain how its authority differs from sdtm_define.xml.
- Claim: supp_define.xml declares FileOID “C4591001.ADaM-IG.1.1” and StandardName “ADaM-IG”; its ADAE items are analysis variables and must not be introduced as AE or SUPPAE targets. Use sdtm_define.xml as the source of allowable SDTM target variables, while using ADaM lineage only as corroboration when helpful.
- Evidence:
  - Source: `input/source_documents/supp_define.xml#ODM header and MetaDataVersion` - FileOID="C4591001.ADaM-IG.1.1", def:StandardName="ADaM-IG", and def:StandardVersion="1.1".
  - Source: `input/source_documents/supp_define.xml#ItemDef IT.ADAE.AECMGIV and IT.ADAE.AESUBJDC` - The analysis items describe lineage such as “SUPPAE.QVAL where SUPPAE.QNAM='AECMGIV'”, confirming these are ADAE columns sourced from SUPPAE rather than SDTM target definitions.
- Solver use: Before accepting any target, confirm that it is defined under the AE or SUPPAE ItemGroup in sdtm_define.xml. Do not map to ADAE or copy ADaM roles/origins as SDTM metadata.
- Risk if ignored: The CSV may contain analysis-only ADAE variables, incorrect metadata, or omit the actual QNAM-based SUPPAE target required by the contract.
- Recheck: Parse both XML headers and print MetaDataVersion StandardName, then verify every proposed target against the AE/SUPPAE metadata in sdtm_define.xml.
- Confidence: high

### 2. Distinct CRF questions converge on AECONTRT [local_conflict]
- Input gap: The contract names a three-column composite key but separately says comparison is by dataset and variable; it does not explain handling when different CRF fields map to the same target pair.
- Claim: The annotated AE form maps both “Was a Concomitant Medication given?” and “Was a Non-Drug Treatment given?” to AE.AECONTRT, with separate supplemental qualifiers AECMGIV and AENDGIV. Therefore target-pair deduplication can erase a field-level mapping; preserve and validate CRF-source identity using the declared composite key.
- Evidence:
  - Source: `input/source_documents/annotated_crf.pdf#PDF page 11 of 131, questions 11-12` - Question 11 is annotated “AECONTRT” and “AECMGIV in SUPPAE”; question 12 is annotated “AECONTRT” and “AENDGIV in SUPPAE”.
  - Source: `input/output_contract.json#composite_key and comparison` - The composite key is (crf_item_or_placeholder, sdtm_dataset, sdtm_variable), while the comparison note says rows are matched by (sdtm_dataset, sdtm_variable).
- Solver use: Build rows from visually verified CRF fields first, check uniqueness using the declared composite key, and separately report repeated dataset-variable pairs before writing the CSV. Do not silently collapse distinct source fields based only on target name.
- Risk if ignored: One of the two treatment questions may disappear, or a supplemental qualifier may be attached to the wrong visible field despite an apparently valid target list.
- Recheck: Filter the draft mapping for AE.AECONTRT and inspect each row beside rendered aCRF page 11; confirm that each source descriptor and associated SUPPAE qualifier matches the visual annotation.
- Confidence: high

## Writer updates

- None yet.
