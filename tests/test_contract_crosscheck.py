"""Mechanical reconciliation of the prep contract and the frozen suite."""
from __future__ import annotations

from ale_run.agents.ale_claw.contract_crosscheck import (
    crosscheck_contract,
    normalize_locator_path,
    render_crosscheck_note,
)


def test_locator_normalization_extracts_citable_paths() -> None:
    assert normalize_locator_path("task_prompt") == "task_prompt"
    assert normalize_locator_path("task_prompt#lines:3-4") == "task_prompt"
    assert normalize_locator_path("input/spec.md#lines:1-2") == "input/spec.md"
    assert normalize_locator_path("input/spec.md lines 4-5") == "input/spec.md"
    assert normalize_locator_path("./software/run.py:") == "software/run.py"
    assert normalize_locator_path("the schema section") is None
    assert normalize_locator_path("") is None
    assert normalize_locator_path("#lines:1-2") is None


def _manifest() -> dict:
    return {
        "tests": [{
            "check": "schema.columns",
            "sources": [
                {"path": "task_prompt", "locator": "lines:1-1", "quote": "q"},
                {"path": "input/schema.json", "locator": "/required", "quote": "q"},
            ],
        }],
        "unverifiable": [{
            "check": "quality.accuracy",
            "sources": [
                {"path": "input/rules.md", "locator": "lines:2-2", "quote": "q"},
            ],
        }],
    }


def _contract() -> list[dict[str, str]]:
    return [
        {"requirement": "a", "locator": "task_prompt#lines:1-2", "check": "", "note": ""},
        {"requirement": "b", "locator": "input/schema.json#/required", "check": "", "note": ""},
        {"requirement": "c", "locator": "input/mapping.csv#rows", "check": "", "note": ""},
        {"requirement": "d", "locator": "somewhere in the pdf", "check": "", "note": ""},
        {"requirement": "e", "locator": "", "check": "", "note": ""},
    ]


def test_crosscheck_compares_cited_file_coverage() -> None:
    crosscheck = crosscheck_contract(_contract(), _manifest())

    assert crosscheck["prep_items"] == 5
    assert crosscheck["verifier_tests"] == 1
    assert crosscheck["shared_paths"] == ["input/schema.json", "task_prompt"]
    assert crosscheck["prep_only_paths"] == ["input/mapping.csv"]
    assert crosscheck["verifier_only_paths"] == ["input/rules.md"]
    assert crosscheck["prep_unparsed_locators"] == 1
    assert crosscheck["prep_missing_locators"] == 1


def test_crosscheck_note_surfaces_both_directions() -> None:
    note = render_crosscheck_note(crosscheck_contract(_contract(), _manifest()))

    assert "## Contract cross-check (mechanical)" in note
    assert "`input/rules.md`" in note
    assert "reread them against the task prompt" in note
    assert "`input/mapping.csv`" in note
    assert "only your own checking does" in note.lower()
    assert "does not judge either reading" in note


def test_crosscheck_note_is_silent_when_coverage_matches() -> None:
    manifest = _manifest()
    contract = [
        {"requirement": "a", "locator": "task_prompt", "check": "", "note": ""},
        {"requirement": "b", "locator": "input/schema.json", "check": "", "note": ""},
        {"requirement": "c", "locator": "input/rules.md#lines:2-2", "check": "", "note": ""},
    ]

    assert render_crosscheck_note(crosscheck_contract(contract, manifest)) == ""
