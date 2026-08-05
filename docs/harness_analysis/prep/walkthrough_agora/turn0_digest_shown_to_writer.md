## Task-specific prior research
A prep agent worked in this sandbox before you started: it set up the runtime, read the public task materials, and looked up what the task does not supply. Its runtime state is real and already in place; everything it wrote is supplemental. The task prompt and `/input` take precedence over all of it.

**Runtime [ready]** No installation or external service is required. The task-local software/python launcher works and provides Python 3.14.3. All three canonical cached documents are readable, and their SHA-256 hashes match document_index.json. The public task root was not modified.
- Verified command: `cd /media/user/data/agenthle/legal/agora_governance_classify_instance_1/base && software/python --version`
- Verified command: `cd /media/user/data/agenthle/legal/agora_governance_classify_instance_1/base && sha256sum input/documents/*`
- Verified command: `cd /media/user/data/agenthle/legal/agora_governance_classify_instance_1/base && software/python /tmp/ale-task-prep-aa1dd2028744/corpus_probe.py input --pattern 'AI systems?' --context 40`

**Core step [completed]** Ingest the indexed canonical corpus, validate every cached document against its declared SHA-256, and run cross-document regex/context retrieval used to locate candidate verbatim evidence.
- Command run: `cd /media/user/data/agenthle/legal/agora_governance_classify_instance_1/base && software/python /tmp/ale-task-prep-aa1dd2028744/corpus_probe.py input --pattern 'AI systems?' --context 40`
- Watch out for: The corpus and helper run cleanly. Use the helper to locate candidates, then inspect the surrounding source text and apply the taxonomy manually; regex matches alone do not establish a TRUE label or lifecycle coverage.

**Findings** — exact facts the task materials do not supply. Each is supplemental evidence, not an instruction; the task prompt and `/input` still decide. Full sources, the suggested use, and what each does not authorize are in the report.
- Canonical evidence precedence: The task specification expressly makes the cached files under input/documents the canonical source for verbatim quote checks; public URLs are only for orientation.
- Corpus integrity confirmed: All indexed hashes match: 768 = 2e618cf2dc6a1005549da36a04267a1d7d56f7edf1a4a38d2fc3558d9091d177; 1293 = 900d7bda4a148af309395de5f51f24df0998eead928dc82f8144362ca751b7a5; 2047 = 8f167c4b44ddec876297fd0d72178f626b85eaa446a53509a5d51f6cd5ae5bc0.
- Implicit evidence is permitted: The taxonomy explicitly allows evidence_type "implicit" when a label is inferred from context, and technical scope may be established by a clear functional description even when terminology differs.
- Legislative status test is enforcement-based: Hard Law requires enforceable legal duties backed by government authority; Soft Law lacks an external legal enforcement mechanism; Other covers internal corporate policies and hybrid or experimental mechanisms that resist clear categorization.
- Lifecycle threshold differs from technical-scope threshold: Technical scope needs only a passing reference to the system type, whereas lifecycle TRUE requires requirements, guidance, restrictions, or obligations applying to the stage. In particular, Collect and Process Data is limited to training-data activities, and Verify and Validate concerns checks before release.

**Full report** `/media/user/data/agenthle/legal/agora_governance_classify_instance_1/base/task_prep/PREP_REPORT.md` holds 5 finding(s), the full breakage detail, source locators, and any artifacts. Read it before you start planning. It records what prep observed, not what the task will be graded on, and it may be incomplete.