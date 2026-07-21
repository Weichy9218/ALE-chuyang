"""Mechanical cross-check between the prep contract and the frozen suite.

The prep contract checklist and the verifier's frozen tests are two
independent readings of the same public task surface. Their agreement is
cheap confidence; their disagreement is exactly the "easy to misread" signal
the prep `note` field tries to guess at. Free text cannot be aligned
semantically by code, so this module compares the one thing both sides state
mechanically: which public files each reading cites. It judges neither side,
grants no authority, and runs only when both artifacts exist (the
prep+verifier arm).
"""
from __future__ import annotations

from typing import Any

_PUBLIC_PREFIXES = ("input/", "software/")


def normalize_locator_path(locator: str) -> str | None:
    """Reduce a prep locator string to a citable public path, or None.

    Prep locators are free text of the form ``task_prompt`` or
    ``input/path#fragment``. The verifier's source paths are already
    normalized, so mapping both sides onto ``task_prompt | input/... |
    software/...`` makes them comparable at file granularity.
    """
    value = (locator or "").strip().lstrip("./").lstrip("/")
    if not value:
        return None
    # Free text may append a fragment ("#lines:3-8") or a description after a
    # space/colon; the citable path is the first token before either.
    value = value.split("#", 1)[0].strip()
    if not value:
        return None
    value = value.split()[0].rstrip(":,;")
    if value == "task_prompt" or value.startswith("task_prompt"):
        return "task_prompt"
    if value.startswith(_PUBLIC_PREFIXES):
        return value.rstrip("/")
    return None


def crosscheck_contract(
    contract: list[dict[str, str]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Compare cited-file coverage of the prep contract and the frozen suite."""
    prep_paths: set[str] = set()
    unmatched_items = 0
    uncited_items = 0
    for item in contract:
        path = normalize_locator_path(item.get("locator", ""))
        if path is None:
            if (item.get("locator") or "").strip():
                unmatched_items += 1
            else:
                uncited_items += 1
            continue
        prep_paths.add(path)

    verifier_paths: set[str] = set()
    for collection in (manifest.get("tests") or [], manifest.get("unverifiable") or []):
        for entry in collection:
            for source in entry.get("sources") or []:
                path = source.get("path")
                if path:
                    verifier_paths.add(str(path))

    return {
        "prep_items": len(contract),
        "verifier_tests": len(manifest.get("tests") or []),
        "verifier_unverifiable": len(manifest.get("unverifiable") or []),
        "shared_paths": sorted(prep_paths & verifier_paths),
        "prep_only_paths": sorted(prep_paths - verifier_paths),
        "verifier_only_paths": sorted(verifier_paths - prep_paths),
        "prep_unparsed_locators": unmatched_items,
        "prep_missing_locators": uncited_items,
    }


def render_crosscheck_note(crosscheck: dict[str, Any]) -> str:
    """Writer-facing note; empty when the comparison says nothing actionable."""
    verifier_only = crosscheck["verifier_only_paths"]
    prep_only = crosscheck["prep_only_paths"]
    if not verifier_only and not prep_only:
        return ""
    lines = [
        "## Contract cross-check (mechanical)",
        "",
        "The prep checklist and a frozen public test suite were compiled "
        "independently from the same public materials. Comparing only which "
        "files each cites:",
        f"- Cited by both: {len(crosscheck['shared_paths'])} file(s).",
    ]
    if verifier_only:
        joined = ", ".join(f"`{path}`" for path in verifier_only)
        lines.append(
            f"- Cited by frozen tests but absent from the checklist: {joined}. "
            "The checklist may have missed obligations stated there; reread "
            "them against the task prompt."
        )
    if prep_only:
        joined = ", ".join(f"`{path}`" for path in prep_only)
        lines.append(
            f"- On the checklist with no frozen test citing them: {joined}. "
            "No pre-submission test covers these; only your own checking does."
        )
    lines.append(
        "This compares file coverage only. It does not judge either reading, "
        "and the task prompt and `/input` still outrank both."
    )
    return "\n".join(lines)
