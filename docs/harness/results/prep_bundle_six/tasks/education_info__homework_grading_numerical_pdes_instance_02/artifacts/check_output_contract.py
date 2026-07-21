#!/usr/bin/env python3
"""Read-only, task-local structural/cross-file checker for grading outputs."""
from __future__ import annotations
import argparse, csv, json, math, re, sys
from decimal import Decimal, InvalidOperation
from pathlib import Path


def load_json(path: Path, findings: list[str]):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        findings.append(f"{path.name}: cannot parse JSON: {e}")
        return None


def read_csv(path: Path, expected_header: list[str], findings: list[str]):
    try:
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
    except Exception as e:
        findings.append(f"{path.name}: cannot parse CSV: {e}")
        return []
    if not rows:
        findings.append(f"{path.name}: empty CSV")
        return []
    if rows[0] != expected_header:
        findings.append(f"{path.name}: header {rows[0]!r} != {expected_header!r}")
    width = len(expected_header)
    for n, row in enumerate(rows[1:], 2):
        if len(row) != width:
            findings.append(f"{path.name}:{n}: {len(row)} columns, expected {width}")
    return [r for r in rows[1:] if len(r) == width]


def id_multiset_check(label: str, ids: list[str], expected: set[str], findings: list[str]):
    seen = set(ids)
    duplicates = sorted({x for x in ids if ids.count(x) > 1})
    if duplicates:
        findings.append(f"{label}: duplicate student_id(s): {duplicates}")
    if seen != expected:
        findings.append(f"{label}: missing={sorted(expected-seen)}, unexpected={sorted(seen-expected)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task_root", help="task base containing input/")
    ap.add_argument("output_dir", help="candidate output directory (read only)")
    args = ap.parse_args()
    root, out = Path(args.task_root), Path(args.output_dir)
    findings: list[str] = []

    contract = load_json(root / "input/starter_project/output_contract.json", findings)
    rubric = load_json(root / "input/released/rubric.json", findings)
    if not isinstance(contract, dict) or not isinstance(rubric, dict):
        for x in findings: print("FINDING", x)
        return 2

    required = contract.get("required_outputs", [])
    actual = sorted(p.name for p in out.iterdir()) if out.is_dir() else []
    if not out.is_dir(): findings.append(f"output directory not found: {out}")
    if sorted(required) != actual:
        findings.append(f"output entries: missing={sorted(set(required)-set(actual))}, extra={sorted(set(actual)-set(required))}")
    for name in required:
        if not (out / name).is_file(): findings.append(f"{name}: missing or not a regular file")

    expected_ids = {p.stem for p in (root / "input/released/submissions").glob("*.md")}
    maxima = {k: Decimal(str(v["points"])) for k, v in rubric["problems"].items()}

    grades = read_csv(out / "grades.csv", contract["grades_csv_header"], findings) if (out/"grades.csv").is_file() else []
    id_multiset_check("grades.csv", [r[0] for r in grades], expected_ids, findings)
    score_cols = [("1a", 1), ("1b", 2), ("2a", 3), ("2b", 4)]
    for line, row in enumerate(grades, 2):
        values = []
        for part, col in score_cols:
            try:
                val = Decimal(row[col])
                if not val.is_finite(): raise InvalidOperation
                if val < 0 or val > maxima[part]:
                    findings.append(f"grades.csv:{line}: problem_{part}={val} outside [0,{maxima[part]}]")
                values.append(val)
            except (InvalidOperation, ValueError):
                findings.append(f"grades.csv:{line}: problem_{part} is not a finite decimal: {row[col]!r}")
        try:
            total = Decimal(row[5])
            if not total.is_finite(): raise InvalidOperation
            if len(values) == 4 and total != sum(values, Decimal(0)):
                findings.append(f"grades.csv:{line}: total_score={total} but part sum={sum(values, Decimal(0))}")
        except (InvalidOperation, ValueError):
            findings.append(f"grades.csv:{line}: total_score is not a finite decimal: {row[5]!r}")

    tags = read_csv(out / "error_tags.csv", contract["error_tags_csv_header"], findings) if (out/"error_tags.csv").is_file() else []
    tag_ids = [r[0] for r in tags]
    unexpected_tag_ids = sorted(set(tag_ids) - expected_ids)
    if unexpected_tag_ids: findings.append(f"error_tags.csv: unexpected student_id(s): {unexpected_tag_ids}")
    allowed_tags = set(rubric.get("error_tags", {}))
    bad_tags = sorted({r[1] for r in tags if r[1] not in allowed_tags})
    if bad_tags: findings.append(f"error_tags.csv: tags absent from rubric error_tags: {bad_tags}")

    feedback = load_json(out/"per_student_feedback.json", findings) if (out/"per_student_feedback.json").is_file() else None
    if isinstance(feedback, dict):
        keys = set(feedback)
        if keys != expected_ids:
            findings.append(f"per_student_feedback.json: missing={sorted(expected_ids-keys)}, unexpected={sorted(keys-expected_ids)}")
        limit = int(rubric.get("feedback_style", {}).get("max_words_per_student", 70))
        for sid, text in feedback.items():
            if not isinstance(text, str):
                findings.append(f"per_student_feedback.json:{sid}: value is not a string")
            else:
                # Deterministic diagnostic tokenization; rubric does not define 'word'.
                count = len(re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE))
                if count > limit: findings.append(f"per_student_feedback.json:{sid}: diagnostic word count {count} > {limit}")
    elif feedback is not None:
        findings.append("per_student_feedback.json: top level is not an object")

    manifest = load_json(out/"grader_manifest.json", findings) if (out/"grader_manifest.json").is_file() else None
    if isinstance(manifest, dict):
        missing = sorted(set(contract["manifest_required_keys"]) - set(manifest))
        if missing: findings.append(f"grader_manifest.json: missing required keys: {missing}")
    elif manifest is not None:
        findings.append("grader_manifest.json: top level is not an object")

    summary = out/"common_mistakes_summary.md"
    if summary.is_file():
        try:
            if not summary.read_text(encoding="utf-8").strip(): findings.append("common_mistakes_summary.md: empty")
        except Exception as e: findings.append(f"common_mistakes_summary.md: cannot read UTF-8: {e}")

    print(f"CHECKED expected_students={sorted(expected_ids)} findings={len(findings)}")
    for x in findings: print("FINDING", x)
    return 1 if findings else 0

if __name__ == "__main__":
    sys.exit(main())
