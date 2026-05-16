"""Structured logging for pydantic-ai tool calls.

Wires a :class:`LoggingToolset` around every agent's composite toolset via the
:class:`LogToolCalls` capability so each tool invocation emits a structlog record
with name, duration, and outcome. Args and results are previewed only at DEBUG to
keep INFO logs scannable when ``retrieve_evidence`` returns long chunk lists.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets.wrapper import WrapperToolset

if TYPE_CHECKING:
    from pydantic_ai.tools import RunContext
    from pydantic_ai.toolsets import AbstractToolset
    from pydantic_ai.toolsets.abstract import ToolsetTool

logger = structlog.get_logger("rag_retrieval.observability")

_PREVIEW_CAP = 500


def _preview(value: Any) -> str:
    text = repr(value)
    if len(text) > _PREVIEW_CAP:
        return text[:_PREVIEW_CAP] + f"...(+{len(text) - _PREVIEW_CAP} chars)"
    return text


@dataclass
class LoggingToolset(WrapperToolset[Any]):
    """Wrap a toolset and emit a structlog event per tool call."""

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[Any],
        tool: ToolsetTool[Any],
    ) -> Any:
        agent_name = getattr(getattr(ctx, "agent", None), "name", None)
        started = time.perf_counter()
        try:
            result = await super().call_tool(name, tool_args, ctx, tool)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000.0
            logger.info(
                "agent_tool_call",
                tool=name,
                agent=agent_name,
                duration_ms=round(duration_ms, 2),
                status="error",
                error_type=type(exc).__name__,
                error=str(exc),
                args_preview=_preview(tool_args),
            )
            raise
        duration_ms = (time.perf_counter() - started) * 1000.0
        result_len = len(result) if isinstance(result, (list, tuple, dict, str)) else None
        logger.info(
            "agent_tool_call",
            tool=name,
            agent=agent_name,
            duration_ms=round(duration_ms, 2),
            status="ok",
            result_len=result_len,
        )
        logger.debug(
            "agent_tool_call_detail",
            tool=name,
            agent=agent_name,
            args_preview=_preview(tool_args),
            result_preview=_preview(result),
        )
        return result


@dataclass
class LogToolCalls(AbstractCapability[Any]):
    """Capability that installs :class:`LoggingToolset` over the agent's toolsets."""

    def get_wrapper_toolset(self, toolset: AbstractToolset[Any]) -> AbstractToolset[Any]:
        return LoggingToolset(wrapped=toolset)
