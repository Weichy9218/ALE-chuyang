"""A raising tool must not end the episode.

Regression for the 26-task runs of 2026-07-21: `delegate_general` raised a
scheduling TimeoutError, `_handle_item` only caught ToolError/JSONDecodeError/
TypeError, so the exception unwound through `run()` into the deployer and the
whole unit was scored null after the writer had already done most of its work.
"""
from __future__ import annotations

import asyncio

import pytest
from agent.tools.base import BaseTool

from ale_run.agents.ale_claw.harness.agent_loop import OpenClawComputerAgent


class _RaisingTool(BaseTool):
    name = "boom"

    @property
    def description(self) -> str:
        return "always raises"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def call(self, params, **kwargs):
        raise TimeoutError()


def _agent() -> OpenClawComputerAgent:
    agent = OpenClawComputerAgent.__new__(OpenClawComputerAgent)
    agent.tools = [_RaisingTool()]
    agent.telemetry_enabled = False
    agent.callbacks = []
    return agent


def test_tool_exception_becomes_tool_error_not_a_dead_run() -> None:
    agent = _agent()
    item = {"type": "function_call", "name": "boom", "arguments": "{}",
            "call_id": "call_1"}

    out = asyncio.run(agent._handle_item(item, None, None))

    assert out, "the loop must return something the agent can read"
    blob = str(out)
    assert "boom" in blob
    assert "TimeoutError" in blob


def test_tool_exception_does_not_propagate() -> None:
    agent = _agent()
    item = {"type": "function_call", "name": "boom", "arguments": "{}",
            "call_id": "call_2"}
    try:
        asyncio.run(agent._handle_item(item, None, None))
    except Exception as exc:  # noqa: BLE001 - that is exactly the regression
        pytest.fail(f"tool exception escaped the loop: {exc!r}")
