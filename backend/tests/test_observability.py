"""Smoke tests for the LogToolCalls capability that wraps agent toolsets."""

from __future__ import annotations

from typing import Any

import pytest
import structlog
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from rag_retrieval.observability import LogToolCalls


def _build_agent_with_tool(tool_fn: Any) -> Agent[None, Any]:
    agent: Agent[None, Any] = Agent(model=TestModel(), capabilities=[LogToolCalls()])
    agent.tool_plain(tool_fn)
    return agent


def test_logging_toolset_emits_success_event() -> None:
    def echo(value: str) -> str:
        """Return the input unchanged."""
        return value

    agent = _build_agent_with_tool(echo)
    with structlog.testing.capture_logs() as captured:
        agent.run_sync("call echo")

    events = [e for e in captured if e.get("event") == "agent_tool_call"]
    assert len(events) == 1
    event = events[0]
    assert event["tool"] == "echo"
    assert event["status"] == "ok"
    assert isinstance(event["duration_ms"], float)


def test_logging_toolset_logs_and_reraises_errors() -> None:
    class BoomError(RuntimeError):
        pass

    def explode(_value: str) -> str:
        """Always raise."""
        raise BoomError("kaboom")

    agent = _build_agent_with_tool(explode)
    with structlog.testing.capture_logs() as captured, pytest.raises(Exception):  # noqa: PT011
        # TestModel will invoke `explode` once; pydantic-ai surfaces the failure
        # through its tool-retry machinery and ultimately raises.
        agent.run_sync("call explode")

    error_events = [
        e for e in captured if e.get("event") == "agent_tool_call" and e.get("status") == "error"
    ]
    assert error_events, "expected at least one error event"
    assert error_events[0]["tool"] == "explode"
    assert error_events[0]["error_type"] == "BoomError"
    assert "kaboom" in error_events[0]["error"]
