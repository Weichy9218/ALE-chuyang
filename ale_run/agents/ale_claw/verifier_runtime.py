"""Read-only snapshots and isolated execution for frozen Verifier tests."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import shlex
import time
from pathlib import Path, PurePosixPath
from typing import Any

from .verifier import (
    MAX_SOURCE_BYTES,
    ArtifactSnapshot,
    FrozenTestSuite,
    VerificationResult,
    _canonical_json,
    _relocate_in_text,
    _sha256_text,
    lint_frozen_suite,
)

logger = logging.getLogger(__name__)

TEST_TIMEOUT_S = 120
MAX_PROCESS_OUTPUT_BYTES = 65_536
MAX_SNAPSHOT_MANIFEST_FILES = 400
_SCRIPT_STATUSES = frozenset({"pass", "fail", "unverifiable"})

# A single shell word is capped by the kernel at MAX_ARG_STRLEN (128 KiB), and
# run_command transports reach the VM as one `sh -c` string, so every command
# this module assembles stays well under that bound.
_COMMAND_BATCH_CHARS = 100_000
_B64_CHUNK_CHARS = 60_000
_BATCH_MANIFEST_CHARS = 45_000


def _b64_write_commands(target: str, content_b64: str) -> list[str]:
    """Commands that write base64 content to ``target`` in bounded chunks.

    The payload is appended piecewise to a sidecar file and decoded once, so
    no single command carries more than one chunk of base64.
    """
    quoted = shlex.quote(target)
    sidecar = shlex.quote(f"{target}.b64")
    chunks = [
        content_b64[index:index + _B64_CHUNK_CHARS]
        for index in range(0, len(content_b64), _B64_CHUNK_CHARS)
    ] or [""]
    commands = [f"printf %s {shlex.quote(chunks[0])} > {sidecar}"]
    commands.extend(
        f"printf %s {shlex.quote(chunk)} >> {sidecar}" for chunk in chunks[1:]
    )
    commands.append(f"base64 -d < {sidecar} > {quoted} && rm -f {sidecar}")
    return commands


async def _run_command_batches(
    interface: Any, commands: list[str], *, what: str
) -> None:
    """Run a command list in &&-joined batches bounded by _COMMAND_BATCH_CHARS.

    Commands are atomic units (never split); state lives on the VM filesystem,
    so splitting the sequence across shell invocations is safe. Any non-zero
    exit aborts the remainder.
    """
    batch: list[str] = []
    length = 0

    async def _flush() -> None:
        nonlocal batch, length
        if not batch:
            return
        result = await interface.run_command(" && ".join(batch))
        if getattr(result, "returncode", 1) != 0:
            raise RuntimeError(
                f"could not {what}: "
                f"{str(getattr(result, 'stderr', '') or '').strip()}"
            )
        batch = []
        length = 0

    for command in commands:
        if batch and length + len(command) + 4 > _COMMAND_BATCH_CHARS:
            await _flush()
        batch.append(command)
        length += len(command) + 4
    await _flush()


_LOCATE_BATCH_SOURCE = """import hashlib, json, pathlib, re, sys
entries = json.load(sys.stdin)
out = []
for entry in entries:
    try:
        root = pathlib.Path(entry['root']).resolve()
        path = pathlib.Path(entry['abs']).resolve(strict=True)
        path.relative_to(root)
        data = path.read_bytes()
        if len(data) > int(entry['max_bytes']):
            raise ValueError('source exceeds size limit')
        locator = entry['locator']
        quote = entry['quote']
        located = False
        if locator == 'file':
            located = True
        else:
            text = data.decode('utf-8')
            if path.suffix.lower() == '.json' and locator.startswith('/'):
                value = json.loads(text)
                for part in locator[1:].split('/') if locator != '/' else []:
                    part = part.replace('~1', '/').replace('~0', '~')
                    value = value[int(part)] if isinstance(value, list) else value[part]
                try:
                    located = json.loads(quote) == value
                except json.JSONDecodeError:
                    selected = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                    located = quote in selected
            else:
                match = re.fullmatch(r'lines:([1-9][0-9]*)-([1-9][0-9]*)', locator)
                if not match:
                    raise ValueError('invalid text locator')
                start, end = map(int, match.groups())
                if start > end or end - start >= 50:
                    raise ValueError('invalid text locator span')
                lines = text.splitlines()
                if end <= len(lines):
                    located = quote in '\\n'.join(lines[start - 1:end])
                if not located and text.count(quote) == 1 and quote.count('\\n') < 50:
                    located = True
        out.append({'sha256': hashlib.sha256(data).hexdigest(), 'located': located})
    except Exception as exc:
        out.append({'sha256': '', 'located': False,
                    'error': type(exc).__name__ + ': ' + str(exc)})
print(json.dumps(out))
"""


async def _locate_files_batch(
    interface: Any,
    task_root: str,
    entries: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Re-locate many public-file sources with one VM process per chunk.

    Semantics per entry match the freeze-time locator, including the
    unique-quote relocation rule; an unreadable or out-of-root path yields
    ``{'sha256': '', 'located': False}`` instead of failing the batch.
    """
    if not entries:
        return []
    payload: list[dict[str, Any]] = []
    for entry in entries:
        prefix = entry["path"].split("/", 1)[0]
        payload.append({
            "root": f"{task_root.rstrip('/')}/{prefix}",
            "abs": f"{task_root.rstrip('/')}/{entry['path']}",
            "locator": entry["locator"],
            "quote": entry["quote"],
            "max_bytes": MAX_SOURCE_BYTES,
        })
    chunks: list[list[dict[str, Any]]] = [[]]
    size = 0
    for item in payload:
        item_chars = len(json.dumps(item, ensure_ascii=True)) + 1
        if chunks[-1] and size + item_chars > _BATCH_MANIFEST_CHARS:
            chunks.append([])
            size = 0
        chunks[-1].append(item)
        size += item_chars
    results: list[dict[str, Any]] = []
    for chunk in chunks:
        encoded = base64.b64encode(
            json.dumps(chunk, ensure_ascii=True).encode("utf-8")
        ).decode("ascii")
        command = (
            f"printf %s {shlex.quote(encoded)} | base64 -d | "
            f"/usr/bin/python3 -c {shlex.quote(_LOCATE_BATCH_SOURCE)}"
        )
        result = await interface.run_command(command)
        if getattr(result, "returncode", 1) != 0:
            raise RuntimeError(
                "batch source locate failed: "
                f"{str(getattr(result, 'stderr', '') or '').strip()}"
            )
        receipts = json.loads(str(getattr(result, "stdout", "") or ""))
        if not isinstance(receipts, list) or len(receipts) != len(chunk):
            raise RuntimeError("batch source locate returned a malformed receipt")
        results.extend(receipts)
    return results


def _audit_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Describe staged files without duplicating their contents for the Auditor."""
    result = {key: value for key, value in manifest.items() if key != "tests"}
    tests: list[dict[str, Any]] = []
    for source in manifest["tests"]:
        test = {key: value for key, value in source.items() if key not in {"script", "fixtures"}}
        test["fixtures"] = {
            kind: [
                {
                    "path": f"fixtures/{source['check']}/{kind}/{item['path']}",
                    "encoding": item["encoding"],
                }
                for item in source["fixtures"][kind]
            ]
            for kind in ("valid", "invalid")
        }
        tests.append(test)
    result["tests"] = tests
    return result


async def stage_test_suite(
    *,
    interface: Any,
    task_root: str,
    manifest: dict[str, Any],
) -> FrozenTestSuite:
    """Stage candidate or final scripts and fixtures in a read-only directory."""
    frozen = "suite_sha256" in manifest
    if frozen:
        manifest = lint_frozen_suite(manifest)
        digest = manifest["suite_sha256"]
    else:
        digest = hashlib.sha256(_canonical_json(manifest).encode("utf-8")).hexdigest()
    token = hashlib.sha256(task_root.encode()).hexdigest()[:12]
    suite_path = f"/tmp/ale-verifier-{token}/suite-{digest[:16]}"
    manifest_path = f"{suite_path}/manifest.json"
    sandbox_source = Path(__file__).with_name("verifier_sandbox.py").read_bytes()
    sandbox_b64 = base64.b64encode(sandbox_source).decode("ascii")
    sandbox_hash = hashlib.sha256(sandbox_source).hexdigest()
    sandbox_path = f"{suite_path}/verifier_sandbox.py"
    commands = [
        f"if [ -e {shlex.quote(suite_path)} ]; then chmod -R u+w {shlex.quote(suite_path)}; fi",
        f"rm -rf {shlex.quote(suite_path)}",
        f"mkdir -p {shlex.quote(suite_path)}",
    ]
    if not frozen:
        manifest_bytes = _canonical_json(_audit_manifest(manifest)).encode("utf-8")
        manifest_b64 = base64.b64encode(manifest_bytes).decode("ascii")
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        commands.extend(_b64_write_commands(manifest_path, manifest_b64))
        commands.append(
            f"test \"$(sha256sum {shlex.quote(manifest_path)} | awk '{{print $1}}')\" "
            f"= {manifest_hash}"
        )
    commands.extend(_b64_write_commands(sandbox_path, sandbox_b64))
    commands.append(
        f"test \"$(sha256sum {shlex.quote(sandbox_path)} | awk '{{print $1}}')\" "
        f"= {sandbox_hash}"
    )
    for test in manifest["tests"]:
        script_target = f"{suite_path}/{test['script_path']}"
        script_b64 = base64.b64encode(test["script"].encode("utf-8")).decode("ascii")
        commands.append(
            f"mkdir -p {shlex.quote(str(PurePosixPath(script_target).parent))}"
        )
        commands.extend(_b64_write_commands(script_target, script_b64))
        commands.append(
            f"test \"$(sha256sum {shlex.quote(script_target)} | awk '{{print $1}}')\" "
            f"= {shlex.quote(test['script_sha256'])}"
        )
        for kind in ("valid", "invalid"):
            fixture_root = f"{suite_path}/fixtures/{test['check']}/{kind}"
            commands.append(f"mkdir -p {shlex.quote(fixture_root)}")
            for fixture_file in test["fixtures"][kind]:
                target = f"{fixture_root}/{fixture_file['path']}"
                content_base64 = (
                    base64.b64encode(fixture_file["content"].encode("utf-8")).decode("ascii")
                    if fixture_file["encoding"] == "utf8"
                    else fixture_file["content"]
                )
                commands.append(
                    f"mkdir -p {shlex.quote(str(PurePosixPath(target).parent))}"
                )
                commands.extend(_b64_write_commands(target, content_base64))
    commands.append(f"chmod -R a-w {shlex.quote(suite_path)}")
    await _run_command_batches(interface, commands, what="stage verifier suite")
    return FrozenTestSuite(path=suite_path, sha256=digest, manifest=manifest)


async def stage_verifier_report(
    interface: Any,
    *,
    task_root: str,
    filename: str,
    report: dict[str, Any],
) -> str | None:
    """Expose one complete verifier result to the Writer inside the task VM."""
    report_dir = task_root.rstrip("/") + "/verifier"
    report_path = f"{report_dir}/{filename}"
    try:
        await interface.create_dir(report_dir)
        await interface.write_text(
            report_path,
            json.dumps(report, indent=2, ensure_ascii=True) + "\n",
            append=False,
        )
    except Exception as exc:  # verifier reporting must not abort the writer
        logger.warning("could not stage verifier report at %s: %s", report_path, exc)
        return None
    return report_path


async def remove_test_suite(*, interface: Any, suite: FrozenTestSuite) -> None:
    """Remove a staged suite before the Writer can inspect it."""
    if not suite.path:
        return
    path = shlex.quote(suite.path)
    result = await interface.run_command(
        f"if [ -e {path} ]; then chmod -R u+w {path} && rm -rf {path}; fi"
    )
    if getattr(result, "returncode", 1) != 0:
        raise RuntimeError(f"could not remove staged verifier suite: {suite.path}")


async def _tree_hash(interface: Any, path: str) -> str:
    quoted = shlex.quote(path)
    command = (
        f"if [ -L {quoted} ]; then "
        f"printf 'link %s\\n' \"$(readlink -- {quoted})\" | sha256sum | awk '{{print $1}}'; "
        f"elif [ -d {quoted} ]; then cd {quoted} && "
        "fh=$(find . -type f -print0 | sort -z | xargs -0 -r sha256sum | "
        "sha256sum | awk '{print $1}') && "
        "ph=$(find . -printf '%y %P -> %l\\n' | sort | sha256sum | awk '{print $1}') && "
        "printf '%s %s\\n' \"$fh\" \"$ph\" | sha256sum | awk '{print $1}'; "
        f"elif [ -f {quoted} ]; then sha256sum {quoted} | sha256sum | awk '{{print $1}}'; "
        "else printf 'missing\\n' | sha256sum | awk '{print $1}'; fi"
    )
    result = await interface.run_command(command)
    value = str(getattr(result, "stdout", "") or "").strip()
    if getattr(result, "returncode", 1) != 0 or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RuntimeError(f"could not hash {path}")
    return value


async def snapshot_output(
    *,
    interface: Any,
    task_root: str,
    os_type: str,
    iteration: int | str,
) -> ArtifactSnapshot:
    """Copy ``output/`` into an immutable snapshot directory.

    ``iteration`` names the snapshot: post-DONE review rounds use 0, 1, ...;
    writer-triggered pre-submission checks use ``writer1``, ``writer2``, ... so
    the two families can never collide.
    """
    if os_type.lower() != "linux":
        raise RuntimeError("verifier requires Linux")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", str(iteration)):
        raise ValueError(f"invalid snapshot iteration label: {iteration!r}")
    token = hashlib.sha256(task_root.encode()).hexdigest()[:12]
    snapshot = f"/tmp/ale-verifier-{token}/snapshot-{iteration}"
    rejected_symlinks = f"{snapshot}-rejected-symlinks.txt"
    output = task_root.rstrip("/") + "/output"
    source_sha256 = await _tree_hash(interface, output)
    command = (
        f"rm -rf {shlex.quote(snapshot)} && rm -f {shlex.quote(rejected_symlinks)} && "
        f"mkdir -p {shlex.quote(snapshot)} && : > {shlex.quote(rejected_symlinks)} && "
        f"if [ -L {shlex.quote(output)} ]; then "
        f"printf '. -> %s\\n' \"$(readlink -- {shlex.quote(output)})\" > {shlex.quote(rejected_symlinks)}; "
        f"elif [ -d {shlex.quote(output)} ]; then cp -a {shlex.quote(output)}/. {shlex.quote(snapshot)}/; "
        f"elif [ -e {shlex.quote(output)} ]; then cp -a {shlex.quote(output)} {shlex.quote(snapshot)}/; fi && "
        f"cd {shlex.quote(snapshot)} && "
        f"find . -type l -printf '%P -> %l\\n' | sort >> {shlex.quote(rejected_symlinks)} && "
        "find . -type l -delete && "
        f"chmod -R a-w {shlex.quote(snapshot)} {shlex.quote(rejected_symlinks)} && "
        "n=$(find . -type f | wc -l) && "
        "fh=$(find . -type f -print0 | sort -z | xargs -0 -r sha256sum | "
        "sha256sum | awk '{print $1}') && "
        "ph=$(find . -printf '%y %P -> %l\\n' | sort | sha256sum | awk '{print $1}') && "
        "h=$(printf '%s %s\\n' \"$fh\" \"$ph\" | sha256sum | awk '{print $1}') && "
        "printf '%s %s\\n' \"$h\" \"$n\""
    )
    result = await interface.run_command(command)
    if getattr(result, "returncode", 1) != 0:
        raise RuntimeError(
            f"could not snapshot output: {str(getattr(result, 'stderr', '') or '').strip()}"
        )
    parts = str(getattr(result, "stdout", "") or "").strip().split()
    if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
        raise RuntimeError(f"invalid snapshot receipt: {parts!r}")
    if await _tree_hash(interface, output) != source_sha256:
        raise RuntimeError("writer output changed while snapshotting")
    return ArtifactSnapshot(
        path=snapshot,
        sha256=parts[0],
        source_sha256=source_sha256,
        file_count=int(parts[1]),
        rejected_symlinks_path=rejected_symlinks,
    )


async def snapshot_manifest(
    interface: Any, snapshot: ArtifactSnapshot
) -> list[dict[str, Any]]:
    """Per-file size and line count of one immutable snapshot.

    Recorded on every snapshot so the analyzer can see what a writer did after
    a signal arrived: whether the next output grew, shrank, or lost files.
    Deleting content is the cheapest way to pass a mechanical check, and it is
    exactly what the hidden rubric tends to punish, so the direction of change
    is the reading that matters. Cheap and read-only; failure yields [].
    """
    quoted = shlex.quote(snapshot.path)
    command = (
        f"cd {quoted} && find . -type f -printf '%P\\n' | sort | "
        f"head -n {MAX_SNAPSHOT_MANIFEST_FILES} | "
        "while IFS= read -r f; do "
        "printf '%s\\t%s\\t%s\\n' \"$(wc -c < \"$f\")\" \"$(wc -l < \"$f\")\" \"$f\"; "
        "done"
    )
    try:
        result = await interface.run_command(command)
    except Exception as exc:  # noqa: BLE001 - a manifest is diagnostics only
        logger.warning("could not read snapshot manifest: %s", exc)
        return []
    if getattr(result, "returncode", 1) != 0:
        return []
    entries: list[dict[str, Any]] = []
    for line in str(getattr(result, "stdout", "") or "").splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        try:
            entries.append({
                "path": parts[2],
                "bytes": int(parts[0]),
                "lines": int(parts[1]),
            })
        except ValueError:
            continue
    return entries


def _isolated_command(
    *,
    task_root: str,
    suite_path: str,
    output_path: str,
    argv: list[str],
) -> str:
    input_path = task_root.rstrip("/") + "/input"
    software_path = task_root.rstrip("/") + "/software"
    checks_path = f"{suite_path}/checks"
    sandbox_path = f"{suite_path}/verifier_sandbox.py"
    command = " ".join(shlex.quote(arg) for arg in argv)
    return (
        "set -eu; scratch=$(mktemp -d /tmp/ale-verifier-scratch.XXXXXX); "
        "trap 'rm -rf \"$scratch\"' EXIT; "
        f"timeout --signal=KILL {TEST_TIMEOUT_S}s /usr/bin/python3 "
        f"{shlex.quote(sandbox_path)} {shlex.quote(input_path)} "
        f"{shlex.quote(software_path)} {shlex.quote(output_path)} "
        f"{shlex.quote(checks_path)} \"$scratch\" -- {command}"
    )


async def _run_process(interface: Any, command: str) -> dict[str, Any]:
    started = time.monotonic()
    result = await interface.run_command(command)
    stdout = str(getattr(result, "stdout", "") or "")
    stderr = str(getattr(result, "stderr", "") or "")
    return {
        "returncode": getattr(result, "returncode", 1),
        "stdout": stdout[:MAX_PROCESS_OUTPUT_BYTES],
        "stderr": stderr[:MAX_PROCESS_OUTPUT_BYTES],
        "stdout_truncated": len(stdout) > MAX_PROCESS_OUTPUT_BYTES,
        "stderr_truncated": len(stderr) > MAX_PROCESS_OUTPUT_BYTES,
        "duration_s": time.monotonic() - started,
    }


def _normalize_script_result(receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("stdout_truncated") or receipt.get("stderr_truncated"):
        raise ValueError("test output exceeded the 65536-byte limit")
    returncode = receipt.get("returncode")
    if returncode != 0:
        if returncode == 124:
            raise ValueError(f"test timed out after {TEST_TIMEOUT_S} seconds")
        raise ValueError(f"test process exited with code {returncode}")
    try:
        value = json.loads(str(receipt.get("stdout") or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"test stdout is not JSON: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"status", "observed", "evidence"}:
        raise ValueError("test stdout has invalid fields")
    status = str(value["status"] or "").strip()
    observed = value["observed"]
    evidence = value["evidence"]
    empty_values = (None, "", [], {})
    if status not in _SCRIPT_STATUSES or observed in empty_values or evidence in empty_values:
        raise ValueError("test stdout has an invalid status or empty evidence")
    return {
        "status": status,
        "observed": observed,
        "evidence": evidence,
        "stderr": str(receipt.get("stderr") or ""),
    }


def _base_check(test: dict[str, Any]) -> dict[str, Any]:
    check = {
        "check": test["check"],
        "sources": test["sources"],
        "requirement": test["requirement"],
        "interpretation": test["interpretation"],
        "command": test["command"],
        "expected": test["expected"],
        "execution_mode": test["execution_mode"],
        "execution_reason": test["execution_reason"],
        "requested_blocking": test.get("requested_blocking", test["blocking"]),
        "blocking": test["blocking"],
    }
    if "validation" in test:
        check["validation"] = test["validation"]
    return check


def _error_check(
    test: dict[str, Any],
    observed: str,
    evidence: str,
    execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        **_base_check(test),
        "status": "error",
        "observed": observed,
        "evidence": evidence,
        "execution": execution,
        "blocking": False,
    }


def _execution_record(
    test: dict[str, Any],
    receipts: list[dict[str, Any]],
    *,
    reproducible: bool,
) -> dict[str, Any]:
    return {
        "mode": test["execution_mode"],
        "reason": test["execution_reason"],
        "command": test["command"],
        "runs": receipts,
        "consecutive_runs": len(receipts),
        "reproducible": reproducible,
    }


async def _run_test_twice(
    *,
    interface: Any,
    task_root: str,
    suite: FrozenTestSuite,
    output_path: str,
    test: dict[str, Any],
) -> dict[str, Any]:
    command = _isolated_command(
        task_root=task_root,
        suite_path=suite.path,
        output_path=output_path,
        argv=test["command"],
    )
    normalized: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    errors: list[str] = []
    for run in range(2):
        try:
            receipt = await _run_process(interface, command)
            receipts.append(receipt)
            normalized.append(_normalize_script_result(receipt))
        except Exception as exc:
            errors.append(f"run {run + 1}: {type(exc).__name__}: {exc}")
    if errors:
        evidence = "; ".join(errors)
        for index, receipt in enumerate(receipts):
            evidence += (
                f"; captured run {index + 1} stdout={receipt.get('stdout')!r} "
                f"stderr={receipt.get('stderr')!r}"
            )
        return _error_check(
            test,
            "test did not complete twice",
            evidence,
            _execution_record(test, receipts, reproducible=False),
        )
    if normalized[0] != normalized[1]:
        return _error_check(
            test,
            "consecutive runs returned different results",
            f"run 1: {_canonical_json(normalized[0])}; run 2: {_canonical_json(normalized[1])}",
            _execution_record(test, receipts, reproducible=False),
        )
    result = normalized[0]
    stderr = result.pop("stderr")
    evidence = result["evidence"]
    evidence_summary = evidence if isinstance(evidence, str) else _canonical_json(evidence)
    return {
        **_base_check(test),
        "status": result["status"],
        "observed": result["observed"],
        "evidence": (
            f"command: {shlex.join(test['command'])}; consecutive_runs: 2 identical; "
            f"stderr: {stderr.strip() or '<empty>'}; {evidence_summary}"
        ),
        "execution": _execution_record(test, receipts, reproducible=True),
    }


async def _environment_health(
    *,
    interface: Any,
    task_root: str,
    suite: FrozenTestSuite,
    output_path: str,
) -> tuple[bool, str]:
    preflight = await interface.run_command(
        "command -v timeout >/dev/null && "
        "/usr/bin/python3 -c \"import ctypes; ctypes.CDLL('libseccomp.so.2')\""
    )
    if getattr(preflight, "returncode", 1) != 0:
        return False, "Landlock runtime, libseccomp, or timeout is unavailable"
    command = _isolated_command(
        task_root=task_root,
        suite_path=suite.path,
        output_path=output_path,
        argv=["python3", "-c", "print('verifier-environment-healthy')"],
    )
    try:
        receipt = await _run_process(interface, command)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    healthy = (
        receipt.get("returncode") == 0
        and str(receipt.get("stdout") or "").strip() == "verifier-environment-healthy"
    )
    return healthy, str(receipt.get("stderr") or "").strip() or "isolated Python probe passed"


async def preflight_suite(
    *,
    interface: Any,
    task_root: str,
    suite: FrozenTestSuite,
) -> list[dict[str, Any]]:
    """Prove valid-pass, invalid-fail, and reproducibility before Writer runs."""
    results: list[dict[str, Any]] = []
    if not suite.manifest["tests"]:
        return results
    probe_path = f"{suite.path}/fixtures/{suite.manifest['tests'][0]['check']}/valid"
    healthy, health_evidence = await _environment_health(
        interface=interface,
        task_root=task_root,
        suite=suite,
        output_path=probe_path,
    )
    for test in suite.manifest["tests"]:
        valid_path = f"{suite.path}/fixtures/{test['check']}/valid"
        invalid_path = f"{suite.path}/fixtures/{test['check']}/invalid"
        if healthy:
            valid = await _run_test_twice(
                interface=interface,
                task_root=task_root,
                suite=suite,
                output_path=valid_path,
                test=test,
            )
            invalid = await _run_test_twice(
                interface=interface,
                task_root=task_root,
                suite=suite,
                output_path=invalid_path,
                test=test,
            )
        else:
            valid = _error_check(test, "environment unavailable", health_evidence)
            invalid = _error_check(test, "environment unavailable", health_evidence)
        reproducible = valid["status"] == "pass" and invalid["status"] == "fail"
        results.append({
            "check": test["check"],
            "environment_healthy": healthy,
            "checker_reproducible": reproducible,
            "valid_status": valid["status"],
            "invalid_status": invalid["status"],
            "execution_mode": test["execution_mode"],
            "environment": {
                "healthy": healthy,
                "evidence": health_evidence,
            },
            "evidence": (
                f"environment: {health_evidence}; valid fixture: {valid['evidence']}; "
                f"invalid fixture: {invalid['evidence']}"
            ),
        })
    return results


def _unverifiable_source_check(test: dict[str, Any]) -> dict[str, Any]:
    locators = "; ".join(
        f"{source['path']} {source['locator']}: {source['locate_evidence']}"
        for source in test["sources"]
    )
    return {
        **_base_check(test),
        "status": "unverifiable",
        "observed": "one or more cited sources could not be located",
        "evidence": f"mechanical locators: {locators}",
        "execution": None,
        "blocking": False,
    }


def _unverifiable_requirement(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "check": item["check"],
        "sources": item["sources"],
        "requirement": item["expected"],
        "interpretation": item["reason"],
        "command": [],
        "expected": item["expected"],
        "requested_blocking": False,
        "blocking": False,
        "status": "unverifiable",
        "observed": "public solve-time truth is unavailable",
        "evidence": item["reason"],
        "execution": None,
    }


def _overall(checks: list[dict[str, Any]]) -> str:
    """Zero-authority aggregate: describes coverage, never a verdict.

    There is deliberately no pass/fail here - an aggregate verdict would be a
    single green target to optimize toward, and no check carries the authority
    to back one. ``measured`` means at least one frozen check executed against
    the snapshot; ``error`` means checks existed but none could execute;
    ``unverifiable`` means nothing was executable at freeze time.
    """
    executed = [check for check in checks if check.get("execution") is not None]
    if executed:
        return "measured"
    if any(check["status"] == "error" for check in checks):
        return "error"
    return "unverifiable"


async def _verify_sources(
    *,
    interface: Any,
    task_root: str,
    task_prompt: str,
    manifest: dict[str, Any],
) -> None:
    """Confirm every frozen source still hashes and locates as at freeze time.

    This runs before every execution - every writer check and every review
    round - so file sources go to the VM as one batch process per chunk
    instead of one process per source. Semantics match the freeze-time
    locator, including the input/task_prompt.md fallback for prompt quotes.
    """
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for collection in (manifest["tests"], manifest["unverifiable"]):
        for item in collection:
            for expected in item["sources"]:
                key = (
                    expected["path"], expected["locator"],
                    expected["quote"], expected["sha256"],
                )
                unique.setdefault(key, {
                    "check": item["check"],
                    "sha256": expected["sha256"],
                    "located": bool(expected["located"]),
                })
    prompt_sha = _sha256_text(task_prompt)
    receipts: dict[tuple[str, str, str, str], tuple[str, bool]] = {}
    file_keys: list[tuple[str, str, str, str]] = []
    file_entries: list[dict[str, str]] = []
    fallback_keys: list[tuple[str, str, str, str]] = []
    fallback_entries: list[dict[str, str]] = []
    for key in unique:
        path, locator, quote, _expected_sha = key
        if path == "task_prompt":
            try:
                located, _corrected, _moved = _relocate_in_text(
                    task_prompt, locator, quote
                )
            except ValueError:
                located = False
            if located:
                receipts[key] = (prompt_sha, True)
            else:
                fallback_keys.append(key)
                fallback_entries.append({
                    "path": "input/task_prompt.md",
                    "locator": locator,
                    "quote": quote,
                })
        else:
            file_keys.append(key)
            file_entries.append(
                {"path": path, "locator": locator, "quote": quote}
            )
    for key, receipt in zip(
        file_keys,
        await _locate_files_batch(interface, task_root, file_entries),
    ):
        receipts[key] = (
            str(receipt.get("sha256") or ""), bool(receipt.get("located"))
        )
    for key, receipt in zip(
        fallback_keys,
        await _locate_files_batch(interface, task_root, fallback_entries),
    ):
        if receipt.get("located"):
            receipts[key] = (str(receipt.get("sha256") or ""), True)
        else:
            # The fallback did not resolve either; the source stands exactly
            # as frozen: prompt hash, not located.
            receipts[key] = (prompt_sha, False)
    for key, reference in unique.items():
        sha, located = receipts[key]
        if sha != reference["sha256"] or located != reference["located"]:
            raise RuntimeError(
                f"public source changed after suite freeze: {reference['check']}"
            )


async def execute_test_suite(
    *,
    interface: Any,
    task_root: str,
    task_prompt: str,
    suite: FrozenTestSuite,
    snapshot: ArtifactSnapshot,
) -> VerificationResult:
    """Run every eligible frozen test twice against one immutable snapshot."""
    started = time.monotonic()
    manifest = suite.manifest
    # Coverage describes what the frozen suite can measure at all: a check is
    # covered when it will actually execute against the snapshot, uncovered
    # when its sources failed to locate, its checker failed preflight, or the
    # requirement has no public solve-time oracle.
    def _executable(test: dict[str, Any]) -> bool:
        validation = test["validation"]
        return bool(
            validation["sources_located"]
            and validation["checker_reproducible"]
            and validation["environment_healthy"]
        )

    coverage = {
        "covered": [
            test["check"] for test in manifest["tests"] if _executable(test)
        ],
        "uncovered": [
            *[
                test["check"] for test in manifest["tests"]
                if not _executable(test)
            ],
            *[item["check"] for item in manifest["unverifiable"]],
        ],
    }
    checks: list[dict[str, Any]] = []
    try:
        normalized = lint_frozen_suite(manifest)
        if normalized["suite_sha256"] != suite.sha256:
            raise RuntimeError("frozen suite hash does not match its manifest")
        await _verify_sources(
            interface=interface,
            task_root=task_root,
            task_prompt=task_prompt,
            manifest=manifest,
        )
        if await _tree_hash(interface, snapshot.path) != snapshot.sha256:
            raise RuntimeError("artifact snapshot changed before verification")
        runnable = any(
            test["validation"]["sources_located"]
            and test["validation"]["checker_reproducible"]
            and test["validation"]["environment_healthy"]
            for test in manifest["tests"]
        )
        if runnable:
            # The sandbox wrapper runs outside its own jail, so it gets the
            # same re-verification the checker scripts get: a staged copy the
            # writer could have rewritten must not fake results.
            sandbox_expected = hashlib.sha256(
                Path(__file__).with_name("verifier_sandbox.py").read_bytes()
            ).hexdigest()
            sandbox_receipt = await interface.run_command(
                f"sha256sum {shlex.quote(suite.path + '/verifier_sandbox.py')} "
                "| awk '{print $1}'"
            )
            if (
                getattr(sandbox_receipt, "returncode", 1) != 0
                or str(getattr(sandbox_receipt, "stdout", "") or "").strip()
                != sandbox_expected
            ):
                raise RuntimeError("staged verifier sandbox changed after staging")
        for test in manifest["tests"]:
            validation = test["validation"]
            if not validation["sources_located"]:
                # No usable public anchor: a cited source failed to locate.
                # Running would measure against an expected with no standing,
                # so this stays a coverage gap.
                check = _unverifiable_source_check(test)
            elif not (
                validation["checker_reproducible"]
                and validation["environment_healthy"]
            ):
                # The Verifier itself could not run reliably; this is not evidence
                # about the output, so it stays a non-blocking execution error.
                check = _error_check(
                    test,
                    "checker did not pass its pre-freeze gate",
                    f"fixture preflight: {validation['fixture_evidence']}",
                )
            else:
                # Located and reproducible: run it. Every difference surfaces
                # as an advisory review item - nothing is blocking under the
                # zero-authority protocol.
                script = f"{suite.path}/{test['script_path']}"
                receipt = await interface.run_command(
                    f"sha256sum {shlex.quote(script)} | awk '{{print $1}}'"
                )
                if (
                    getattr(receipt, "returncode", 1) != 0
                    or str(getattr(receipt, "stdout", "") or "").strip()
                    != test["script_sha256"]
                ):
                    raise RuntimeError(f"frozen script changed: {test['check']}")
                check = await _run_test_twice(
                    interface=interface,
                    task_root=task_root,
                    suite=suite,
                    output_path=snapshot.path,
                    test=test,
                )
            checks.append(check)
        checks.extend(_unverifiable_requirement(item) for item in manifest["unverifiable"])
        if await _tree_hash(interface, snapshot.path) != snapshot.sha256:
            raise RuntimeError("artifact snapshot changed during verification")
        return VerificationResult(
            overall=_overall(checks),
            suite_sha256=suite.sha256,
            snapshot_sha256=snapshot.sha256,
            checks=checks,
            coverage=coverage,
            duration_s=time.monotonic() - started,
        )
    except Exception as exc:
        logger.warning("verifier executor failed: %s", exc)
        return VerificationResult(
            overall="error",
            suite_sha256=suite.sha256,
            snapshot_sha256=snapshot.sha256,
            checks=checks,
            coverage=coverage,
            duration_s=time.monotonic() - started,
            error=f"{type(exc).__name__}: {exc}",
        )
