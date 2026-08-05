"""Shared extraction of the one JSON object an agent response must contain.

Both prep and the verifier builder promise to return exactly one JSON object.
The two callers differ in one policy only, so this is one implementation with
one switch instead of two drifting copies.
"""
from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(text: str, *, allow_trailing: bool = False) -> dict[str, Any]:
    """Return the JSON object in ``text``.

    Tolerates code fences and leading prose: an agent that writes a sentence
    before its JSON has made a formatting slip, not an unusable response.

    With ``allow_trailing`` False the object must be the last thing in the
    response - the prep contract is one object and nothing after it. With True,
    an object followed by prose is also accepted and the largest candidate
    wins, which for a builder response is the suite rather than an inline
    example.
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
        if allow_trailing and end > best_size:
            best, best_size = value, end
    if best is None:
        raise ValueError("response does not contain one JSON object")
    return best
