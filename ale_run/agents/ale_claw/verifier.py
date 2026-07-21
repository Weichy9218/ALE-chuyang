"""Build, audit, and freeze tests derived from a task's public contract."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import shlex
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

logger = logging.getLogger(__name__)

VERIFIER_PROTOCOL_VERSION = "public-verifier-v18"
MAX_TESTS = 6
MAX_UNVERIFIABLE_REQUIREMENTS = 8
MAX_SCRIPT_BYTES = 50_000
MAX_SUITE_SCRIPT_BYTES = 200_000
MAX_FIXTURE_FILE_BYTES = 100_000
MAX_SUITE_FIXTURE_BYTES = 400_000
MAX_SOURCE_BYTES = 20_000_000
MAX_SOURCE_QUOTE_CHARS = 4_000
MAX_SOURCES_PER_CHECK = 12
MAX_INLINE_REPORT_CHARS = 20_000
VERIFIER_AGENT_TOOL_NAMES = frozenset({"read", "exec", "analyze_image"})

_CHECK_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,79}$")
_TEXT_LOCATOR_RE = re.compile(r"^lines:([1-9][0-9]*)-([1-9][0-9]*)$")
_EXECUTION_MODES = frozenset({"task_software", "public_recompute", "simulation"})
_PRIVATE_SOURCE_WORDS = ("hidden", "evaluator", "grader")


@dataclass
class AgentUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    duration_s: float = 0.0
    llm_turns: int = 0
    tool_calls: int = 0
    tool_call_counts: dict[str, int] = field(default_factory=dict)

    def add(self, other: AgentUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.duration_s += other.duration_s
        self.llm_turns += other.llm_turns
        self.tool_calls += other.tool_calls
        for name, count in other.tool_call_counts.items():
            self.tool_call_counts[name] = self.tool_call_counts.get(name, 0) + count


@dataclass(frozen=True)
class FrozenTestSuite:
    path: str
    sha256: str
    manifest: dict[str, Any]


@dataclass
class VerifierBuildResult:
    status: str
    suite: FrozenTestSuite | None = None
    candidate: dict[str, Any] | None = None
    usage: AgentUsage = field(default_factory=AgentUsage)
    dropped: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class ArtifactSnapshot:
    path: str
    sha256: str
    source_sha256: str
    file_count: int
    rejected_symlinks_path: str | None = None


@dataclass
class VerificationResult:
    overall: str
    suite_sha256: str
    snapshot_sha256: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, list[str]] = field(default_factory=dict)
    duration_s: float = 0.0
    error: str | None = None

    @property
    def hard_mismatches(self) -> list[dict[str, Any]]:
        """Blocking assertions whose frozen check ran and observed a difference.

        These carry hard authority: the public source entails the expected result,
        so the Writer must either reconcile the output or dispute the test.
        """
        return [
            check for check in self.checks
            if check["blocking"] and check["status"] == "fail"
        ]

    @property
    def review_items(self) -> list[dict[str, Any]]:
        """Advisory observations from a reproducible check without blocking authority.

        The check executed against the snapshot and observed a difference, but it
        is not a hard public requirement (partial-coverage checker, simulation, or
        a proxy metric). The Writer reviews and decides; it is never forced.
        """
        return [
            check for check in self.checks
            if not check["blocking"]
            and check["status"] == "fail"
            and check.get("execution") is not None
        ]

    @property
    def execution_errors(self) -> list[dict[str, Any]]:
        """Checks the Verifier could not turn into a verdict (env/dep/checker).

        These are Verifier-side problems, not evidence the output is wrong, so they
        never force a review round. They are surfaced as context only.
        """
        return [check for check in self.checks if check["status"] == "error"]

    @property
    def coverage_gaps(self) -> list[dict[str, Any]]:
        """Requirements with no public solve-time oracle (unverifiable)."""
        return [check for check in self.checks if check["status"] == "unverifiable"]

    @property
    def needs_review(self) -> bool:
        """Whether any safe, reproducible observation warrants a Writer round."""
        return bool(self.hard_mismatches or self.review_items)

    @property
    def failure_signature(self) -> tuple[str, ...]:
        """Sorted names of the hard mismatches, for repair-loop bookkeeping."""
        return tuple(sorted(check["check"] for check in self.hard_mismatches))

    def metadata(self) -> dict[str, Any]:
        data = asdict(self)
        data["failure_signature"] = list(self.failure_signature)
        data["needs_review"] = self.needs_review
        data["categories"] = {
            "hard_mismatches": [check["check"] for check in self.hard_mismatches],
            "review_items": [check["check"] for check in self.review_items],
            "execution_errors": [check["check"] for check in self.execution_errors],
            "coverage_gaps": [check["check"] for check in self.coverage_gaps],
        }
        return data


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _parse_json_object(text: str) -> dict[str, Any]:
    """Extract the one JSON object from an agent response.

    Tolerates code fences and surrounding prose: a builder that writes a
    sentence before its JSON has made a formatting slip, not an unusable
    suite. Prefers an object with nothing after it (the unambiguous case);
    otherwise takes the largest candidate, which for a builder response is
    the suite rather than an inline example.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    decoder = json.JSONDecoder()
    best: dict[str, Any] | None = None
    best_size = -1
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        if not stripped[index + end:].strip():
            return value
        if end > best_size:
            best, best_size = value, end
    if best is None:
        raise ValueError("response does not contain one JSON object")
    return best


def _check_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        raise ValueError(f"{label} lacks fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{label} has unknown fields: {', '.join(sorted(unknown))}")


def _safe_relative_path(value: Any, *, label: str) -> PurePosixPath:
    path = PurePosixPath(str(value or "").strip())
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError(f"{label} is unsafe")
    return path


def _relative_path(value: Any, *, prefix: str, label: str) -> str:
    path = _safe_relative_path(value, label=label)
    if path.parts[0] != prefix:
        raise ValueError(f"{label} must be under {prefix}/")
    return path.as_posix()


def _source(value: Any, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} source must be an object")
    _check_keys(
        value,
        required={"path", "locator", "quote"},
        optional={"sha256", "located", "locate_evidence"},
        label=f"{label} source",
    )
    path = str(value["path"] or "").strip()
    locator = str(value["locator"] or "").strip()
    quote = str(value["quote"] or "").strip()
    if path != "task_prompt":
        prefix = path.split("/", 1)[0]
        if prefix not in {"input", "software"}:
            raise ValueError(f"{label} source must be task_prompt, input/, or software/")
        path = _relative_path(path, prefix=prefix, label=f"{label} source path")
    lowered = f"{path} {locator}".lower()
    if any(word in lowered for word in _PRIVATE_SOURCE_WORDS):
        raise ValueError(f"{label} refers to a private source")
    if not locator or len(quote) > MAX_SOURCE_QUOTE_CHARS:
        raise ValueError(
            f"{label} needs a locator and a quote of at most "
            f"{MAX_SOURCE_QUOTE_CHARS} characters"
        )
    if locator == "file":
        if path == "task_prompt" or quote:
            raise ValueError(f"{label} file locator requires a public file and empty quote")
    elif not quote:
        raise ValueError(f"{label} quote cannot be empty")
    elif path.endswith(".json"):
        if not locator.startswith("/"):
            raise ValueError(f"{label} JSON source locator must be a JSON Pointer")
    else:
        match = _TEXT_LOCATOR_RE.fullmatch(locator)
        if not match or int(match.group(2)) - int(match.group(1)) >= 50:
            raise ValueError(f"{label} text locator must be lines:N-M spanning at most 50 lines")
    return {"path": path, "locator": locator, "quote": quote}


def _sources(value: Any, *, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_SOURCES_PER_CHECK:
        raise ValueError(
            f"{label} sources must contain 1-{MAX_SOURCES_PER_CHECK} source objects"
        )
    sources = [_source(item, label=f"{label} source {index}") for index, item in enumerate(value)]
    identities = {(item["path"], item["locator"], item["quote"]) for item in sources}
    if len(identities) != len(sources):
        raise ValueError(f"{label} has duplicate sources")
    return sources


def _fixture_files(
    value: Any,
    *,
    label: str,
) -> tuple[list[dict[str, str]], int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty file array")
    files: list[dict[str, str]] = []
    paths: set[str] = set()
    total = 0
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"{label} file {index} must be an object")
        _check_keys(
            raw,
            required={"path", "encoding", "content"},
            optional=set(),
            label=f"{label} file {index}",
        )
        path = _safe_relative_path(raw["path"], label=label).as_posix()
        if path in paths:
            raise ValueError(f"{label} has duplicate path {path}")
        encoding = str(raw["encoding"] or "").strip()
        raw_content = raw["content"]
        if not isinstance(raw_content, str):
            raise ValueError(f"{label} file {path} content must be a string")
        if encoding == "utf8":
            content = raw_content.encode("utf-8")
            normalized = raw_content
        elif encoding == "base64":
            try:
                content = base64.b64decode(raw_content, validate=True)
            except ValueError as exc:
                raise ValueError(f"{label} file {path} has invalid base64") from exc
            normalized = base64.b64encode(content).decode("ascii")
        else:
            raise ValueError(f"{label} file {path} encoding must be utf8 or base64")
        if len(content) > MAX_FIXTURE_FILE_BYTES:
            raise ValueError(f"{label} file {path} exceeds {MAX_FIXTURE_FILE_BYTES} bytes")
        total += len(content)
        paths.add(path)
        files.append({"path": path, "encoding": encoding, "content": normalized})
    return sorted(files, key=lambda item: item["path"]), total


def lint_candidate_suite(value: dict[str, Any]) -> dict[str, Any]:
    """Validate the Builder's untrusted candidate suite."""
    if not isinstance(value, dict):
        raise ValueError("candidate suite must be an object")
    _check_keys(
        value,
        required={"reason", "tests", "unverifiable"},
        optional=set(),
        label="candidate suite",
    )
    reason = str(value["reason"] or "").strip()
    raw_tests = value["tests"]
    raw_unverifiable = value["unverifiable"]
    if not reason:
        raise ValueError("candidate suite reason cannot be empty")
    if not isinstance(raw_tests, list) or not isinstance(raw_unverifiable, list):
        raise ValueError("candidate suite tests and unverifiable must be arrays")
    if not raw_tests and not raw_unverifiable:
        raise ValueError("candidate suite must contain a test or unverifiable requirement")
    # Over-length lists are truncated rather than rejected: the excess items are
    # recorded, the ones within budget still reach the writer.
    overflow_tests = raw_tests[MAX_TESTS:]
    overflow_unverifiable = raw_unverifiable[MAX_UNVERIFIABLE_REQUIREMENTS:]
    raw_tests = raw_tests[:MAX_TESTS]
    raw_unverifiable = raw_unverifiable[:MAX_UNVERIFIABLE_REQUIREMENTS]

    ids: set[str] = set()
    script_bytes = 0
    fixture_bytes = 0
    tests: list[dict[str, Any]] = []
    dropped: list[str] = []
    if overflow_tests:
        dropped.append(f"tests: {len(overflow_tests)} beyond the {MAX_TESTS} cap")
    if overflow_unverifiable:
        dropped.append(
            f"unverifiable: {len(overflow_unverifiable)} beyond the "
            f"{MAX_UNVERIFIABLE_REQUIREMENTS} cap"
        )
    for index, raw in enumerate(raw_tests):
        try:
            test = _lint_one_test(raw, index, ids)
        except ValueError as exc:
            # One malformed test is not a reason to confiscate the writer's
            # whole `verify` tool: drop the item, keep the rest of the suite.
            dropped.append(f"test[{index}]: {exc}")
            continue
        size = len(test["script"].encode("utf-8"))
        fixture_size = sum(
            len(item["content"].encode("utf-8"))
            for kind in ("valid", "invalid")
            for item in test["fixtures"][kind]
        )
        if script_bytes + size > MAX_SUITE_SCRIPT_BYTES:
            dropped.append(f"test[{index}]: suite script budget exhausted")
            continue
        if fixture_bytes + fixture_size > MAX_SUITE_FIXTURE_BYTES:
            dropped.append(f"test[{index}]: suite fixture budget exhausted")
            continue
        script_bytes += size
        fixture_bytes += fixture_size
        tests.append(test)
        ids.add(test["check"])

    unverifiable: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_unverifiable):
        try:
            unverifiable.append(_lint_one_unverifiable(raw, index, ids))
        except ValueError as exc:
            dropped.append(f"unverifiable[{index}]: {exc}")
            continue
        ids.add(unverifiable[-1]["check"])
    if not tests and not unverifiable:
        raise ValueError(
            "no usable test or unverifiable requirement survived lint: "
            + "; ".join(dropped[:5])
        )
    return {
        "reason": reason,
        "tests": tests,
        "unverifiable": unverifiable,
        "dropped": dropped,
    }


def _lint_one_test(raw: Any, index: int, ids: set[str]) -> dict[str, Any]:
    """Validate one candidate test; raising drops only this item."""
    if not isinstance(raw, dict):
        raise ValueError("must be an object")
    _check_keys(
        raw,
        required={
            "check", "sources", "requirement", "interpretation", "expected",
            "execution_mode", "execution_reason", "script", "fixtures",
            "blocking",
        },
        optional=set(),
        label=f"test {index}",
    )
    check = str(raw["check"] or "").strip()
    if not _CHECK_RE.fullmatch(check) or check in ids:
        raise ValueError(f"invalid or duplicate test check: {check!r}")
    requirement = str(raw["requirement"] or "").strip()
    interpretation = str(raw["interpretation"] or "").strip()
    expected = str(raw["expected"] or "").strip()
    execution_mode = str(raw["execution_mode"] or "").strip()
    execution_reason = str(raw["execution_reason"] or "").strip()
    script = str(raw["script"] or "")
    if not requirement or not interpretation or not expected:
        raise ValueError(f"test {check} has an empty contract field")
    if not isinstance(raw["blocking"], bool):
        raise ValueError(f"test {check} blocking must be boolean")
    if execution_mode not in _EXECUTION_MODES or not execution_reason:
        raise ValueError(f"test {check} has an invalid execution method")
    if not script.strip() or len(script.encode("utf-8")) > MAX_SCRIPT_BYTES:
        raise ValueError(f"test {check} script must be 1-{MAX_SCRIPT_BYTES} bytes")
    fixtures = raw["fixtures"]
    if not isinstance(fixtures, dict):
        raise ValueError(f"test {check} fixtures must be an object")
    _check_keys(
        fixtures,
        required={"valid", "invalid"},
        optional=set(),
        label=f"test {check} fixtures",
    )
    valid, _ = _fixture_files(fixtures["valid"], label=f"test {check} valid fixture")
    invalid, _ = _fixture_files(
        fixtures["invalid"], label=f"test {check} invalid fixture"
    )
    if _canonical_json(valid) == _canonical_json(invalid):
        raise ValueError(f"test {check} valid and invalid fixtures are identical")
    return {
        "check": check,
        "sources": _sources(raw["sources"], label=f"test {check}"),
        "requirement": requirement,
        "interpretation": interpretation,
        "command": ["python3", f"{check}.py"],
        "expected": expected,
        "execution_mode": execution_mode,
        "execution_reason": execution_reason,
        "script_path": f"checks/{check}.py",
        "script": script,
        "script_sha256": _sha256_text(script),
        "fixtures": {"valid": valid, "invalid": invalid},
        "blocking": raw["blocking"],
    }


def _lint_one_unverifiable(raw: Any, index: int, ids: set[str]) -> dict[str, Any]:
    """Validate one unverifiable requirement; raising drops only this item."""
    if not isinstance(raw, dict):
        raise ValueError("must be an object")
    _check_keys(
        raw,
        required={"check", "sources", "expected", "reason"},
        optional=set(),
        label=f"unverifiable requirement {index}",
    )
    check = str(raw["check"] or "").strip()
    expected = str(raw["expected"] or "").strip()
    item_reason = str(raw["reason"] or "").strip()
    if not _CHECK_RE.fullmatch(check) or check in ids:
        raise ValueError(f"invalid or duplicate unverifiable check: {check!r}")
    if not expected or not item_reason:
        raise ValueError(f"unverifiable requirement {check} has an empty field")
    return {
        "check": check,
        "sources": _sources(raw["sources"], label=f"requirement {check}"),
        "expected": expected,
        "reason": item_reason,
    }


def lint_frozen_suite(value: dict[str, Any]) -> dict[str, Any]:
    """Verify the content hash on a suite produced by this build."""
    if not isinstance(value, dict):
        raise ValueError("frozen suite must be an object")
    _check_keys(
        value,
        required={"version", "reason", "tests", "unverifiable", "suite_sha256"},
        optional=set(),
        label="frozen suite",
    )
    if value["version"] != 1:
        raise ValueError("unsupported frozen suite version")
    content = {key: value[key] for key in ("version", "reason", "tests", "unverifiable")}
    digest = _sha256_text(_canonical_json(content))
    if value["suite_sha256"] != digest:
        raise ValueError("suite_sha256 does not match the frozen suite")
    return json.loads(json.dumps({**content, "suite_sha256": digest}))


_LOCATE_SOURCE = """import hashlib, json, pathlib, re, sys
root = pathlib.Path(sys.argv[1]).resolve()
path = pathlib.Path(sys.argv[2]).resolve(strict=True)
path.relative_to(root)
data = path.read_bytes()
if len(data) > int(sys.argv[5]):
    raise ValueError('source exceeds size limit')
locator = sys.argv[3]
quote = sys.argv[4]
located = False
relocated = False
if locator == 'file':
    located = True
else:
    text = data.decode('utf-8')
if locator != 'file' and path.suffix.lower() == '.json' and locator.startswith('/'):
    value = json.loads(text)
    for part in locator[1:].split('/') if locator != '/' else []:
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    try:
        located = json.loads(quote) == value
    except json.JSONDecodeError:
        selected = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        located = quote in selected
elif locator != 'file':
    match = re.fullmatch(r'lines:([1-9][0-9]*)-([1-9][0-9]*)', locator)
    if not match:
        raise ValueError('invalid text locator')
    start, end = map(int, match.groups())
    if start > end or end - start >= 50:
        raise ValueError('invalid text locator span')
    lines = text.splitlines()
    if end <= len(lines):
        located = quote in '\\n'.join(lines[start - 1:end])
    # The quote is the fact; the locator is only its coordinates. When the
    # quote appears exactly once in the file, a wrong line number is a
    # mechanical error and is corrected here instead of killing the source.
    if not located and text.count(quote) == 1:
        span = quote.count('\\n')
        if span < 50:
            first = text.count('\\n', 0, text.find(quote)) + 1
            locator = 'lines:%d-%d' % (first, first + span)
            located = True
            relocated = True
print(json.dumps({
    'sha256': hashlib.sha256(data).hexdigest(),
    'located': located,
    'locator': locator,
    'relocated': relocated,
}))
"""


def _relocate_in_text(text: str, locator: str, quote: str) -> tuple[bool, str, bool]:
    """Locate a quote in host-side text, correcting a uniquely-wrong locator."""
    match = _TEXT_LOCATOR_RE.fullmatch(locator)
    if not match:
        raise ValueError("invalid text locator")
    start, end = map(int, match.groups())
    if start > end or end - start >= 50:
        raise ValueError("invalid text locator span")
    lines = text.splitlines()
    located = end <= len(lines) and quote in "\n".join(lines[start - 1:end])
    if not located and text.count(quote) == 1:
        span = quote.count("\n")
        if span < 50:
            first = text.count("\n", 0, text.find(quote)) + 1
            return True, f"lines:{first}-{first + span}", True
    return located, locator, False


async def _locate_source(
    *,
    interface: Any,
    task_root: str,
    task_prompt: str,
    source: dict[str, str],
) -> dict[str, Any]:
    path = source["path"]
    locator = source["locator"]
    quote = source["quote"]
    relocated = False
    try:
        if path == "task_prompt":
            located, locator, relocated = _relocate_in_text(
                task_prompt, locator, quote
            )
            digest = _sha256_text(task_prompt)
            if not located:
                fallback = await _locate_source(
                    interface=interface,
                    task_root=task_root,
                    task_prompt=task_prompt,
                    source={
                        "path": "input/task_prompt.md",
                        "locator": locator,
                        "quote": quote,
                    },
                )
                if fallback["located"]:
                    fallback["locate_evidence"] = (
                        "citation resolved to the public input/task_prompt.md; "
                        + fallback["locate_evidence"]
                    )
                    return fallback
        else:
            prefix = path.split("/", 1)[0]
            public_root = f"{task_root.rstrip('/')}/{prefix}"
            absolute = f"{task_root.rstrip('/')}/{path}"
            command = (
                f"/usr/bin/python3 -c {shlex.quote(_LOCATE_SOURCE)} "
                f"{shlex.quote(public_root)} {shlex.quote(absolute)} "
                f"{shlex.quote(locator)} {shlex.quote(quote)} {MAX_SOURCE_BYTES}"
            )
            result = await interface.run_command(command)
            if getattr(result, "returncode", 1) != 0:
                raise RuntimeError(str(getattr(result, "stderr", "") or "").strip())
            receipt = json.loads(str(getattr(result, "stdout", "") or ""))
            digest = str(receipt["sha256"])
            located = bool(receipt["located"])
            corrected = str(receipt.get("locator") or locator)
            relocated = bool(receipt.get("relocated")) and corrected != locator
            if relocated:
                locator = corrected
        if relocated:
            evidence = (
                "quote found once; locator corrected from "
                f"{source['locator']} to {locator}"
            )
        elif located:
            evidence = "quote and locator found"
        else:
            evidence = "quote or locator not found"
        return {
            **source,
            "locator": locator,
            "sha256": digest,
            "located": located,
            "locate_evidence": evidence,
        }
    except Exception as exc:
        return {
            **source,
            "sha256": "",
            "located": False,
            "locate_evidence": f"{type(exc).__name__}: {exc}",
        }


async def locate_suite_sources(
    *,
    interface: Any,
    task_root: str,
    task_prompt: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    located = json.loads(json.dumps(candidate))
    for collection in (located["tests"], located["unverifiable"]):
        for item in collection:
            item["sources"] = [
                await _locate_source(
                    interface=interface,
                    task_root=task_root,
                    task_prompt=task_prompt,
                    source=source,
                )
                for source in item["sources"]
            ]
    return located


def build_suite_system_prompt(task_root: str, sampling_seed: str) -> str:
    return f"""# Public Test Builder

Build candidate pre-submission tests before the Writer starts.

Public task root: {task_root}
Fixed sampling seed: {sampling_seed}

Use only the task prompt, input/, software/, and task-specified software. Do not
inspect output/, Prep, solver state, hidden references, evaluator/grader code,
prior runs, scores, or answers.

Anchor every test in the task's deliverable contract - the obligations the task
states about the deliverable, under the exact names the task uses. The contract
is where mechanical tests earn their keep: required files at their stated paths,
required fields with their stated spellings, identifiers that must be preserved
verbatim, stated counts, units, orderings, encodings, and cross-file consistency
the task demands. Copy every such name letter-for-letter from the public
materials into the checker; a test that paraphrases a contract name measures the
paraphrase, not the contract. Name each check after the contract obligation it
verifies (for example `contract.submission_csv.required_columns`), so the report
reads as a coverage map of the contract. Prefer covering more of the contract
with simple presence/spelling/count/consistency checks over deep-verifying one
obligation while the rest go unmeasured.

For every test:
- Cite source as path, locator, and an exact quote. Cite the input/... or
  software/... file you actually read. Use task_prompt only for requirements not
  present in a public file. JSON locators must
  be JSON Pointers. Text and task_prompt locators use lines:N-M and may span at
  most 50 lines. Count exact line numbers before returning the suite. Keep each
  quote at or below {MAX_SOURCE_QUOTE_CHARS} characters.
- Each test has a non-empty sources array. Include every normative rule and
  public data source needed to derive the complete expected result; do not cite
  unrelated material. Each entry is
  {{"path":"input/spec.md","locator":"lines:1-4","quote":"..."}}.
  Keep the test atomic even when its proof needs multiple sources, and use at
  most {MAX_SOURCES_PER_CHECK} sources per check.
  For an opaque or binary data file used in recomputation, use locator="file"
  and quote="" so the Harness freezes its whole-file hash.
- State the public requirement, your interpretation, the argv command, and the
  observable expected result. Do not add unstated thresholds, tolerance, order,
  exactness, ranges, field relationships, or rules inferred only from examples.
  If expected selects Yes, No, Unknown, or another enumerated label, sources
  must define how the task's proposition maps to that label. Missing facts and
  ordinary-language convention do not define a label mapping.
- Prefer the task's real validator, test suite, CLI, service, or software when
  it is available on this pgl environment. Otherwise recompute the public
  requirement deterministically. Use simulation only as non-blocking evidence.
  Record execution_mode as task_software, public_recompute, or simulation, and
  give a concrete execution_reason. Do not replace available task software with
  a mock merely because a mock is easier to run.
- If the task explicitly requires the Writer to start or use available software,
  include at least one task_software test that exercises it. If no sound frozen
  test can do so, register that runtime requirement as unverifiable instead of
  silently replacing it with static heuristics.
- Generate one deterministic Python checker. The harness stages it as
  checks/<check>.py and runs python3 <check>.py from checks/. Do not return a
  command or script_path. The checker may invoke task-native software. It reads
  paths from VERIFIER_INPUT,
  VERIFIER_SOFTWARE, and VERIFIER_OUTPUT. No network, current time, unseeded
  randomness, or process-dependent ordering.
- The script prints one JSON object with exactly status, observed, and
  evidence. Status is exactly pass, fail, or unverifiable. Report what you
  measured, not why it happened; the Writer derives root cause itself.
- Supply a small valid fixture that must pass and an invalid fixture with one
  explicit requirement violation that must fail. Fixture paths are relative to
  VERIFIER_OUTPUT. Each fixture is a non-empty array of file objects with exactly
  path, encoding, and content. Use encoding=utf8 and ordinary content unless a
  file is genuinely binary; only binary content uses base64. Example:
  fixtures={{"valid":[{{"path":"result.csv","encoding":"utf8","content":"id\\n1\\n"}}],
  "invalid":[{{"path":"result.csv","encoding":"utf8","content":"bad\\n"}}]}}.
  The harness runs both before freezing.
- Prefer a few atomic hard checks. A universal requirement such as "all IDs" or
  "every producer" must be checked exhaustively; a sample, keyword proxy, or
  unrelated aggregate cannot stand in for it. Split unrelated requirements, and
  mark a requirement unverifiable when the checker cannot prove the full claim.
- Set blocking=true only for an explicit public hard requirement. This records
  your reading for the audit trail; every result reaches the Writer as an
  advisory measurement, never a verdict. Put goals without public solve-time
  truth in unverifiable. Choose any sample locators now using the fixed seed
  and embed them in the script.

Return one JSON object with reason, tests, and unverifiable. A test has exactly:
check, sources, requirement, interpretation, expected, execution_mode,
execution_reason, script, fixtures={{valid, invalid}}, and blocking.
An unverifiable item has
exactly check, sources, expected, and reason. Use at most {MAX_TESTS} tests and
{MAX_UNVERIFIABLE_REQUIREMENTS} unverifiable items."""


def build_suite_request(task_prompt: str) -> str:
    return f"Build the candidate public test suite for this task:\n\n{task_prompt.strip()}"


def locate_failures(candidate: dict[str, Any]) -> list[dict[str, str]]:
    """List every source the harness could not mechanically locate."""
    failures: list[dict[str, str]] = []
    for collection in (candidate["tests"], candidate["unverifiable"]):
        for item in collection:
            for source in item["sources"]:
                if not source.get("located"):
                    failures.append({
                        "check": item["check"],
                        "path": source["path"],
                        "locator": source["locator"],
                        "quote": source["quote"],
                        "locate_evidence": source.get("locate_evidence", ""),
                    })
    return failures


def build_locate_repair_request(raw_suite: str, failures: list[dict[str, str]]) -> str:
    """One bounded, mechanical repair round for sources that failed to locate.

    The evidence is purely mechanical (quote not found at/near the cited
    location), so handing it back to the Builder adds no information about the
    Writer, the Prep, or any hidden material.
    """
    return (
        "The harness could not mechanically locate these sources of your "
        "candidate suite. For each one, reopen the cited file, then either fix "
        "the quote so it is an exact verbatim excerpt (the locator is corrected "
        "automatically when the quote is unique), fix the path, or - if the "
        "public materials do not actually state it - move that requirement to "
        "unverifiable. Change nothing else: keep every other test, script, "
        "fixture, and field exactly as submitted, and return the complete "
        "corrected suite as one JSON object in the same schema.\n\n"
        f"LOCATE FAILURES:\n{json.dumps(failures, indent=2, ensure_ascii=True)}\n\n"
        f"YOUR CANDIDATE SUITE:\n{raw_suite.strip()}"
    )


async def _run_fresh_agent(
    *,
    label: str,
    task: str,
    system_prompt: str,
    model: str,
    summary_model: str,
    tools: list,
    registry: Any,
    parent_session_dir: Path,
    max_steps: int,
    thinking_params: dict[str, Any] | None,
    summary_runtime: Any | None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> tuple[str, AgentUsage]:
    from .harness.subagent.subagent_registry import SubagentType
    from .harness.subagent.subagent_session import GeneralSubagentSession

    run = registry.register(type=SubagentType.GENERAL, task=task, label=label, model=model)
    registry.mark_running(run.run_id)
    session = GeneralSubagentSession(
        run_id=run.run_id,
        task=task,
        model=model,
        tools=tools,
        registry=registry,
        summary_model=summary_model,
        parent_session_dir=parent_session_dir,
        memory_store=None,
        max_steps=max_steps,
        thinking_params=thinking_params,
        summary_runtime=summary_runtime,
        allowed_tool_names=VERIFIER_AGENT_TOOL_NAMES,
        system_prompt=system_prompt,
        api_key=api_key,
        api_base=api_base,
    )
    registry.attach_inbox(run.run_id, session.inbox)
    started = time.monotonic()
    try:
        text = (await session.run()).strip()
        if text.startswith("(subagent reached max steps"):
            raise RuntimeError(f"{label} reached max steps")
        registry.complete(run.run_id, text, session.usage)
        return text, AgentUsage(
            input_tokens=session.usage.input_tokens,
            output_tokens=session.usage.output_tokens,
            duration_s=time.monotonic() - started,
            llm_turns=session.llm_turns,
            tool_calls=session.tool_call_count,
            tool_call_counts=dict(sorted(session.tool_call_counts.items())),
        )
    except Exception as exc:
        registry.fail(run.run_id, str(exc), session.usage)
        raise


def finalize_suite(
    candidate: dict[str, Any],
    preflight: list[dict[str, Any]],
) -> dict[str, Any]:
    """Freeze the suite with mechanical validation only, zero authority.

    Every result reaches the Writer as an advisory measurement: ``blocking`` is
    always false, and the builder's own reading is preserved as
    ``requested_blocking`` for the audit trail. The semantic audit (entailment,
    checker-requirement alignment, source status) existed only to justify hard
    authority; with no hard authority there is nothing for it to license, so
    the freeze needs only the mechanical facts: are the sources located, does
    the checker pass its fixtures, is the environment healthy.
    """
    preflight_by_check = {item["check"]: item for item in preflight}
    tests: list[dict[str, Any]] = []
    for test in candidate["tests"]:
        fixture = preflight_by_check[test["check"]]
        validation = {
            "sources_located": all(
                source["located"] for source in test["sources"]
            ),
            "checker_reproducible": fixture["checker_reproducible"],
            "environment_healthy": fixture["environment_healthy"],
            "environment": fixture["environment"],
            "fixture_evidence": fixture["evidence"],
        }
        tests.append({
            **test,
            "requested_blocking": test["blocking"],
            "blocking": False,
            "validation": validation,
        })
    content = {
        "version": 1,
        "reason": candidate["reason"],
        "tests": tests,
        "unverifiable": candidate["unverifiable"],
    }
    return {**content, "suite_sha256": _sha256_text(_canonical_json(content))}


async def build_candidate_suite(
    *,
    interface: Any,
    os_type: str,
    task_id: str,
    task_root: str,
    task_prompt: str,
    model: str,
    summary_model: str,
    tools: list,
    registry: Any,
    parent_session_dir: Path,
    max_steps: int,
    thinking_params: dict[str, Any] | None = None,
    summary_runtime: Any | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> VerifierBuildResult:
    """Phase A: generate, lint, and locate the candidate suite.

    Runs concurrently with prep and reads only the public task surface. The
    content of the standard - tests, expected values, sources - is fixed here,
    before prep has produced anything, so concurrency preserves independence.
    Environment-dependent gates are deliberately left to phase B.
    """
    if os_type.lower() != "linux":
        return VerifierBuildResult(status="error", error="verifier requires Linux")
    usage = AgentUsage()
    try:
        raw, builder_usage = await _run_fresh_agent(
            label="verifier-builder",
            task=build_suite_request(task_prompt),
            system_prompt=build_suite_system_prompt(
                task_root,
                _sha256_text(f"{task_id}\n{task_prompt}")[:16],
            ),
            model=model,
            summary_model=summary_model,
            tools=tools,
            registry=registry,
            parent_session_dir=parent_session_dir,
            max_steps=max_steps,
            thinking_params=thinking_params,
            summary_runtime=summary_runtime,
            api_key=api_key,
            api_base=api_base,
        )
        usage.add(builder_usage)
        candidate = lint_candidate_suite(_parse_json_object(raw))
        candidate = await locate_suite_sources(
            interface=interface,
            task_root=task_root,
            task_prompt=task_prompt,
            candidate=candidate,
        )
        failures = locate_failures(candidate)
        if failures:
            # One bounded mechanical repair round: quote/path errors the
            # auto-relocator cannot fix (the quote is nowhere in the file)
            # would otherwise sink the whole check as `missing` at the gate.
            try:
                repair_raw, repair_usage = await _run_fresh_agent(
                    label="verifier-builder-locate-repair",
                    task=build_locate_repair_request(raw, failures),
                    system_prompt=build_suite_system_prompt(
                        task_root,
                        _sha256_text(f"{task_id}\n{task_prompt}")[:16],
                    ),
                    model=model,
                    summary_model=summary_model,
                    tools=tools,
                    registry=registry,
                    parent_session_dir=parent_session_dir,
                    max_steps=max_steps,
                    thinking_params=thinking_params,
                    summary_runtime=summary_runtime,
                    api_key=api_key,
                    api_base=api_base,
                )
                usage.add(repair_usage)
                repaired = lint_candidate_suite(_parse_json_object(repair_raw))
                repaired = await locate_suite_sources(
                    interface=interface,
                    task_root=task_root,
                    task_prompt=task_prompt,
                    candidate=repaired,
                )
                # Adopt only on a strict improvement in locate failures that
                # does not cost usable items elsewhere.
                if (
                    len(locate_failures(repaired)) < len(failures)
                    and len(repaired.get("dropped") or [])
                    <= len(candidate.get("dropped") or [])
                ):
                    candidate = repaired
            except Exception as exc:  # noqa: BLE001 - keep the original suite
                logger.warning(
                    "builder locate repair failed; keeping original suite: %s", exc
                )
        return VerifierBuildResult(
            status="candidate", candidate=candidate, usage=usage
        )
    except Exception as exc:
        logger.warning("verifier candidate build failed: %s", exc)
        return VerifierBuildResult(
            status="error", usage=usage, error=f"{type(exc).__name__}: {exc}"
        )


async def finalize_candidate_suite(
    *,
    interface: Any,
    task_root: str,
    candidate: dict[str, Any],
    usage: AgentUsage | None = None,
) -> VerifierBuildResult:
    """Phase B: fixture preflight and freeze - after prep, before its staging.

    ``environment_healthy`` and ``checker_reproducible`` are statements about
    the sandbox the executor will use, and prep spends its whole session
    changing that sandbox. Measuring them before prep froze checkers as
    permanently unusable whenever they depended on a runtime prep was about to
    install. Running here measures the environment the writer actually gets.

    This phase is purely mechanical. The semantic Auditor was removed with hard
    authority: its three judgments (entailment, checker alignment, source
    status) existed only to license a blocking verdict, and no verdict here is
    blocking. What remains is what an advisory measurement still needs - the
    checker starts, discriminates its own fixtures, and runs in a healthy
    environment.
    """
    usage = usage or AgentUsage()
    try:
        from .verifier_runtime import preflight_suite, remove_test_suite, stage_test_suite

        staged_candidate = await stage_test_suite(
            interface=interface,
            task_root=task_root,
            manifest=candidate,
        )
        try:
            preflight = await preflight_suite(
                interface=interface,
                task_root=task_root,
                suite=staged_candidate,
            )
        finally:
            await remove_test_suite(interface=interface, suite=staged_candidate)
        manifest = lint_frozen_suite(finalize_suite(candidate, preflight))
        suite = FrozenTestSuite(
            path="",
            sha256=manifest["suite_sha256"],
            manifest=manifest,
        )
        return VerifierBuildResult(
            status="ready",
            suite=suite,
            usage=usage,
            dropped=list(candidate.get("dropped") or []),
        )
    except Exception as exc:
        logger.warning("verifier suite freeze failed: %s", exc)
        return VerifierBuildResult(
            status="error",
            usage=usage,
            error=f"{type(exc).__name__}: {exc}",
        )


async def build_test_suite(
    *,
    interface: Any,
    os_type: str,
    task_id: str,
    task_root: str,
    task_prompt: str,
    model: str,
    summary_model: str,
    tools: list,
    registry: Any,
    parent_session_dir: Path,
    max_steps: int,
    thinking_params: dict[str, Any] | None = None,
    summary_runtime: Any | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> VerifierBuildResult:
    """Run both build phases back to back.

    The deployer calls the phases separately so the freeze can wait for prep;
    this single-shot path serves tests and callers with no prep phase, where
    back-to-back is identical.
    """
    candidate_result = await build_candidate_suite(
        interface=interface,
        os_type=os_type,
        task_id=task_id,
        task_root=task_root,
        task_prompt=task_prompt,
        model=model,
        summary_model=summary_model,
        tools=tools,
        registry=registry,
        parent_session_dir=parent_session_dir,
        max_steps=max_steps,
        thinking_params=thinking_params,
        summary_runtime=summary_runtime,
        api_key=api_key,
        api_base=api_base,
    )
    if candidate_result.candidate is None:
        return candidate_result
    return await finalize_candidate_suite(
        interface=interface,
        task_root=task_root,
        candidate=candidate_result.candidate,
        usage=candidate_result.usage,
    )


_DISPUTE_RE = re.compile(r"^[ \t]*VERIFIER_DISPUTE\s+([a-z0-9_.-]+)\b", re.MULTILINE)


def parse_disputes(text: str, known_checks: set[str]) -> set[str]:
    return {
        match.group(1) for match in _DISPUTE_RE.finditer(text)
        if match.group(1) in known_checks
    }


def _feedback_value(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=True)


def _source_lines(sources: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"Source {index}: {source['path']} {source['locator']}\n"
        f"Source {index} SHA-256: {source.get('sha256', '')}\n"
        f"Source {index} quote: {source['quote']}"
        for index, source in enumerate(sources, 1)
    )


def _hard_section(item: dict[str, Any]) -> str:
    return (
        "INPUT DETAIL TO RECHECK\n"
        f"Check: {item['check']}\n"
        f"{_source_lines(item['sources'])}\n"
        f"Verifier interpretation: {item['interpretation']}\n\n"
        "OBSERVED FAILURE\n"
        f"Command: {shlex.join(item['command'])}\n"
        f"Observed: {_feedback_value(item['observed'])}\n"
        f"Expected: {_feedback_value(item['expected'])}\n"
        f"Evidence: {_feedback_value(item['evidence'])}"
    )


def _advisory_section(item: dict[str, Any]) -> str:
    caveat = ""
    if item.get("execution_mode") == "simulation":
        caveat = (
            "\nChecker caveat: this observation comes from a simulation, not "
            "the task software."
        )
    return (
        "ADVISORY REVIEW ITEM\n"
        f"Check: {item['check']}\n"
        f"{_source_lines(item['sources'])}\n"
        f"Verifier interpretation: {item['interpretation']}\n"
        f"Command: {shlex.join(item['command'])}\n"
        f"Observed: {_feedback_value(item['observed'])}\n"
        f"Expected: {_feedback_value(item['expected'])}\n"
        f"Evidence: {_feedback_value(item['evidence'])}"
        f"{caveat}\n"
        "Authority: advisory. Expected is the builder's reading of the public "
        "materials, not a verdict. Reopen /input and decide whether to change "
        "output; you are not required to."
    )


def _context_lines(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {item['check']} ({item['status']}): {_feedback_value(item['observed'])}"
        for item in items
    )


def build_feedback_prompt(
    result: VerificationResult,
    *,
    report_path: str | None = None,
    pre_submission: bool = False,
) -> str:
    """Render every safe observation source-first and link the complete report.

    Hard mismatches must be reconciled or disputed; advisory review items invite
    Writer judgment; execution errors and coverage gaps are context only. With
    ``pre_submission=True`` the closing instruction addresses a Writer that is
    still working: it measured its own draft and decides what to do with its
    remaining budget, instead of being called back after DONE.
    """
    sections = [_hard_section(item) for item in result.hard_mismatches]
    sections.extend(_advisory_section(item) for item in result.review_items)
    if result.execution_errors:
        sections.append(
            "EXECUTION ERRORS (the Verifier could not produce a verdict; not scored)\n"
            f"{_context_lines(result.execution_errors)}"
        )
    if result.coverage_gaps:
        sections.append(
            "COVERAGE GAPS (no public solve-time oracle; not scored)\n"
            f"{_context_lines(result.coverage_gaps)}"
        )
    status_summary = ", ".join(
        f"{item['check']}={item['status']}" for item in result.checks
    ) or "no checks"
    if report_path:
        report = f"Complete report: {report_path}"
    else:
        # Fallback when the VM report file could not be staged. Evidence
        # fields can each run to 64 KB, so the inline copy is capped rather
        # than allowed to flood the writer's context.
        inline = json.dumps(result.metadata(), indent=2, ensure_ascii=True)
        if len(inline) > MAX_INLINE_REPORT_CHARS:
            inline = (
                inline[:MAX_INLINE_REPORT_CHARS]
                + "\n... (truncated; the full report is in the harness run "
                "directory)"
            )
        report = "Complete report (inline):\n" + inline
    sections.append(
        "COMPLETE VERIFIER REPORT\n"
        f"Overall: {result.overall}\n"
        f"Checks: {status_summary}\n"
        f"{report}"
    )
    if pre_submission:
        instruction = (
            "WRITER INSTRUCTION\n"
            "This is a pre-submission measurement of your current `output/` "
            "snapshot against tests frozen from the public task materials, not "
            "a grade: every item is advisory and the verifier holds no "
            "authority over your output. For each review item, reopen every "
            "cited public source and confirm its quote applies, then reproduce "
            "the command and trace the first divergence through your code or "
            "data flow before you change anything. Change output only where "
            "you conclude the task actually requires it; write "
            "`VERIFIER_DISPUTE <check>` with public counterevidence to silence "
            "an item you judge wrong. Execution errors and coverage gaps "
            "require no action. Passing checks cover only the publicly "
            "testable part of the task; an all-pass result does not mean the "
            "task is complete."
        )
    else:
        instruction = (
            "WRITER INSTRUCTION\n"
            "Do not modify output immediately. These are advisory measurements "
            "of your final submission against tests frozen from the public "
            "task materials; the verifier holds no authority over your output. "
            "For each review item, reopen every cited public source and "
            "confirm its quote applies to the final submission, then reproduce "
            "the frozen test and trace the first divergence through your code "
            "or data flow. Change output only where you conclude the task "
            "actually requires it, without violating other task requirements; "
            "write `VERIFIER_DISPUTE <check>` with public counterevidence to "
            "silence an item you judge wrong. Execution errors and coverage "
            "gaps are informational and require no action."
        )
    return "\n\n".join(sections + [instruction])
