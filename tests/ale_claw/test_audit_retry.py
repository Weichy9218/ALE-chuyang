"""The reviewer audit must survive a transient boyue gateway blip.

Regression for the sec_10k guard run of 2026-08-05: 2 of 3 reviewer passes hit
`audit_error` because a single LLM call in the audit sub-agent exhausted
litellm's in-call retries (503 ServiceUnavailable / a spurious 401) and killed
the whole audit — silently degrading a "reviewer" run to a "base" run. The
whole-audit retry re-runs the fresh audit after a cooldown on transient failures
(incl. spurious auth, since the writer already validated the key), and surfaces
genuine quota/bug errors fast. Cooldowns are patched out so the test is instant.
"""
from __future__ import annotations

import asyncio

import pytest

import ale_run.agents.ale_claw.reviewer_audit as ra
from ale_run.agents.ale_claw.reviewer_audit import (
    _audit_error_is_transient,
    run_reviewer_audit_with_retry,
)


@pytest.mark.parametrize(
    "message, transient",
    [
        ("litellm.ServiceUnavailableError ... bad_response_status_code Retried 24 times", True),
        ("litellm.AuthenticationError invalid subscription key ... 401 Retried 24 times", True),
        ("Request timed out", True),
        ("APIConnectionError: connection error", True),
        ("insufficient_quota: exceeded your current quota", False),
        ("ValueError: bad json from auditor", False),
    ],
)
def test_error_classification(message, transient):
    assert _audit_error_is_transient(Exception(message)) is transient


def _patch_sleep(monkeypatch):
    slept: list[float] = []

    async def _fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(ra.asyncio, "sleep", _fake_sleep)
    return slept


def test_transient_error_retries_then_succeeds(monkeypatch):
    slept = _patch_sleep(monkeypatch)
    calls = {"n": 0}

    async def _flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("ServiceUnavailableError 503 bad_response_status_code")
        return ("VERDICT", "USAGE", "raw")

    monkeypatch.setattr(ra, "run_reviewer_audit", _flaky)
    out = asyncio.run(run_reviewer_audit_with_retry(max_attempts=3, base_cooldown_s=1.0))
    assert out == ("VERDICT", "USAGE", "raw")
    assert calls["n"] == 3          # failed twice, succeeded on the third
    assert len(slept) == 2          # cooled down before each retry
    assert slept[1] > slept[0]      # escalating cooldown


def test_terminal_error_surfaces_without_retry(monkeypatch):
    slept = _patch_sleep(monkeypatch)
    calls = {"n": 0}

    async def _quota(**kwargs):
        calls["n"] += 1
        raise Exception("insufficient_quota: exceeded your current quota")

    monkeypatch.setattr(ra, "run_reviewer_audit", _quota)
    with pytest.raises(Exception, match="quota"):
        asyncio.run(run_reviewer_audit_with_retry(max_attempts=3, base_cooldown_s=1.0))
    assert calls["n"] == 1          # no retry on a terminal error
    assert slept == []


def test_transient_exhaustion_surfaces_after_all_attempts(monkeypatch):
    slept = _patch_sleep(monkeypatch)
    calls = {"n": 0}

    async def _always_503(**kwargs):
        calls["n"] += 1
        raise Exception("ServiceUnavailableError 503")

    monkeypatch.setattr(ra, "run_reviewer_audit", _always_503)
    with pytest.raises(Exception, match="503"):
        asyncio.run(run_reviewer_audit_with_retry(max_attempts=3, base_cooldown_s=1.0))
    assert calls["n"] == 3          # tried the full budget
    assert len(slept) == 2          # cooled down between the 3 attempts, not after the last
