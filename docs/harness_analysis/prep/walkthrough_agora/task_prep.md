# Task-specific prep

Supplemental preparation done in this sandbox before you started. The task prompt and `/input` take precedence; discard anything here that conflicts with them.

## Runtime [ready]

No installation or external service is required. The task-local software/python launcher works and provides Python 3.14.3. All three canonical cached documents are readable, and their SHA-256 hashes match document_index.json. The public task root was not modified.

Verified commands:
- `cd /media/user/data/agenthle/legal/agora_governance_classify_instance_1/base && software/python --version`
- `cd /media/user/data/agenthle/legal/agora_governance_classify_instance_1/base && sha256sum input/documents/*`
- `cd /media/user/data/agenthle/legal/agora_governance_classify_instance_1/base && software/python /tmp/ale-task-prep-aa1dd2028744/corpus_probe.py input --pattern 'AI systems?' --context 40`

## Core step attempt [completed]

This step was actually run in this sandbox before you started. It is a measurement of what this task does, not a reading of what it says, and it is the one thing here you cannot get by rereading the prompt.

- Step: Ingest the indexed canonical corpus, validate every cached document against its declared SHA-256, and run cross-document regex/context retrieval used to locate candidate verbatim evidence.
- Command: `cd /media/user/data/agenthle/legal/agora_governance_classify_instance_1/base && software/python /tmp/ale-task-prep-aa1dd2028744/corpus_probe.py input --pattern 'AI systems?' --context 40`

Watch out for: The corpus and helper run cleanly. Use the helper to locate candidates, then inspect the surrounding source text and apply the taxonomy manually; regex matches alone do not establish a TRUE label or lifecycle coverage.

## Findings

### 1. Canonical evidence precedence
- Observation: The task specification expressly makes the cached files under input/documents the canonical source for verbatim quote checks; public URLs are only for orientation.
- Writer action: Copy evidence from the cached text, preserving its exact characters, spacing, punctuation, and OCR artifacts rather than substituting cleaner wording from a public webpage or PDF.
- Source: `input/task_spec.md#Inputs`

### 2. Corpus integrity confirmed
- Observation: All indexed hashes match: 768 = 2e618cf2dc6a1005549da36a04267a1d7d56f7edf1a4a38d2fc3558d9091d177; 1293 = 900d7bda4a148af309395de5f51f24df0998eead928dc82f8144362ca751b7a5; 2047 = 8f167c4b44ddec876297fd0d72178f626b85eaa446a53509a5d51f6cd5ae5bc0.
- Writer action: Treat the present files as the intended corpus; no document retrieval or conversion is needed.
- Source: `input/document_index.json`
- Source: `runtime:sha256sum input/documents/*`

### 3. Implicit evidence is permitted
- Observation: The taxonomy explicitly allows evidence_type "implicit" when a label is inferred from context, and technical scope may be established by a clear functional description even when terminology differs.
- Writer action: Use "implicit" only where the quoted passage supports the concept without naming it directly; do not force every supported label to "explicit" merely because the task_spec schema illustration shows that value.
- Source: `input/taxonomy_and_instructions.md#STEP 2 — CLASSIFY EACH DOCUMENT`
- Source: `input/taxonomy_and_instructions.md#TAXONOMY 2: TECHNICAL SCOPE`

### 4. Legislative status test is enforcement-based
- Observation: Hard Law requires enforceable legal duties backed by government authority; Soft Law lacks an external legal enforcement mechanism; Other covers internal corporate policies and hybrid or experimental mechanisms that resist clear categorization.
- Writer action: Classify the instrument represented by the cached text under these tests rather than inferring status solely from words such as “Act” or “Policy.”
- Source: `input/taxonomy_and_instructions.md#TAXONOMY 1: LEGISLATIVE STATUS`
- Do not infer: This finding does not select a legislative-status label for any document.

### 5. Lifecycle threshold differs from technical-scope threshold
- Observation: Technical scope needs only a passing reference to the system type, whereas lifecycle TRUE requires requirements, guidance, restrictions, or obligations applying to the stage. In particular, Collect and Process Data is limited to training-data activities, and Verify and Validate concerns checks before release.
- Writer action: Do not promote a lifecycle stage merely because a related word appears; read the passage for governed activity, timing, and training-data context.
- Source: `input/taxonomy_and_instructions.md#TAXONOMY 2: TECHNICAL SCOPE`
- Source: `input/taxonomy_and_instructions.md#TAXONOMY 3: AI LIFECYCLE STAGE`


## Artifacts

- `task_prep/artifacts/corpus_probe.py` - Tested read-only corpus resolver that loads document_index.json, verifies each cached file's SHA-256, and prints regex matches with configurable source context. It was first tested on synthetic scratch data and then successfully run on all three real documents.
