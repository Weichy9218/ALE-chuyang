---
name: replay-safe-evidence-driven-node-recovery
description: Use when a recovery script must be replayed on a fresh <workspace> and reconstruct a manifest plus safely reclaim storage from paths declared by the task input.
category: computer-use-execution
version: 1
scientist_model: gpt-5.5
created_at: 2026-08-04T00:00:00+00:00
---

## Operating method

1. **Parse authoritative runtime inputs.** Load `<workspace>/config.json` and `<workspace>/logs/service.log` when `safe_recover.py` executes. Read primary shard paths from `feature_index_relpaths`, supporting the documented singular fallback if present. Extract auxiliary paths only from anchored records matching `AUX_INDEX=<relative-path>`. Preserve a deterministic order, such as config order followed by log-discovered paths, while deduplicating.

2. **Confine every path before use.** Reject absolute paths, `..` traversal, and any normalized path outside `<workspace>`. Use `lstat()` so a symlink is distinguishable from its target. Required shard paths must exist as regular, non-symlink files. Do not traverse `/protected` or any directory outside the two permitted cleanup roots.

3. **Reconstruct the manifest from live files.** Validate each required shard's exact `FIDXv1\n` prefix. Obtain its size from `stat().st_size` and compute SHA-256 in chunks, for example with `hashlib.sha256()` and repeated 1 MiB reads. Populate the exact manifest schema consumed by `<workspace>/app/service.py`; do not copy values from an old manifest, notes, or rollback scripts. Each digest must match `^[0-9a-f]{64}$` and each recorded size must equal the live file size.

4. **Protect path and inode dependencies.** Before cleanup, store every required normalized path and `(st_dev, st_ino)` pair. Enumerate only `<workspace>/cache` and `<workspace>/trash` using `os.scandir()` or `os.walk(..., followlinks=False)`. A cleanup candidate must be a regular non-symlink file, satisfy the task instruction's explicit safe-debris classification, not be a keep marker, not be a required path, and not share an inode with a required shard.

5. **Perform deterministic threshold cleanup.** Sort qualified candidates by a documented stable key. Unlink whole candidates one at a time and add the candidate's pre-unlink `st_size` only after `unlink()` succeeds. Stop once `bytes_freed >= config["min_free_bytes"]`. If all qualified debris is insufficient, fail rather than deleting an unclassified or protected object.

6. **Write only the contracted artifacts.** Generate `<workspace>/state/feature_manifest.json`, `<workspace>/cleanup_summary.json`, and `<workspace>/incident_report.md` from runtime results, using the exact formats required by the instruction and consumer. The summary's deleted-file list and `bytes_freed` must reflect successful operations, not the intended plan. Keep `safe_recover.py` self-contained and copy that script to the specified output directory.

7. **Numeric acceptance condition.** A successful run must have `bytes_freed >= config["min_free_bytes"]`; every manifest size must equal `os.stat(path).st_size`; every SHA-256 must be 64 lowercase hexadecimal characters computed from that file; and all required shard path/inode identities must remain present after cleanup.

## Yield condition

Yield only with fresh, verbatim evidence for the concrete work just landed: list every required artifact, reopen/parse it, and confirm the numeric acceptance check above passed on the actual outputs. If incomplete, preserve partial outputs and state the single highest-priority remaining repair; do not claim completion. Never access or guess the hidden reference.
