"""LangGraph interrupt wrappers for human-in-the-loop approval.

Provides two modes:
1. **Native interrupt** (requires checkpointer): uses ``langgraph.types.interrupt``
   to pause graph execution. The graph is resumed with ``Command(resume=...)``.
2. **Blocking fallback** (no checkpointer): uses the existing IO approval methods
   to block until the user responds. This is the default when no checkpointer
   is configured.
"""
from __future__ import annotations

from typing import Any

from .state import AgentGraphState


def _has_checkpointer(state: AgentGraphState) -> bool:
    """Heuristic: if the state carries a session_id and the coder has a
    checkpointer-configured graph, we should use native interrupts.

    For now, detect via environment variable or coder flag.
    """
    import os

    return os.environ.get("AICODER_LANGGRAPH_CHECKPOINT") == "1"


def request_tool_approval(
    state: AgentGraphState,
    *,
    tool_name: str,
    desc: str,
    params_preview: str,
) -> bool:
    """Request user approval for a tool call.

    When a checkpointer is active, uses LangGraph ``interrupt()`` so the graph
    state is persisted. Otherwise falls back to blocking IO.

    Returns:
        True if approved, False if rejected.
    """
    if _has_checkpointer(state):
        return _interrupt_tool_approval(state, tool_name=tool_name, desc=desc, params_preview=params_preview)

    return _blocking_tool_approval(state, tool_name=tool_name, desc=desc, params_preview=params_preview)


def request_plan_approval(
    state: AgentGraphState,
    *,
    plan_text: str,
) -> bool:
    """Request user approval for a generated plan.

    Same interrupt/fallback logic as ``request_tool_approval``.
    """
    if _has_checkpointer(state):
        return _interrupt_plan_approval(state, plan_text=plan_text)

    return _blocking_plan_approval(state, plan_text=plan_text)


# ---------------------------------------------------------------------------
# Native interrupt path (requires checkpointer)
# ---------------------------------------------------------------------------

def _interrupt_tool_approval(state: AgentGraphState, *, tool_name: str, desc: str, params_preview: str) -> bool:
    from langgraph.types import interrupt

    response = interrupt({
        "kind": "tool",
        "tool_name": tool_name,
        "title": f"Allow tool call: {tool_name}?",
        "body": desc,
        "params_preview": params_preview,
    })
    return bool(response)


def _interrupt_plan_approval(state: AgentGraphState, *, plan_text: str) -> bool:
    from langgraph.types import interrupt

    response = interrupt({
        "kind": "plan",
        "title": "Approve this plan?",
        "body": plan_text[:2000],
    })
    return bool(response)


# ---------------------------------------------------------------------------
# Blocking fallback path (no checkpointer)
# ---------------------------------------------------------------------------

def _get_coder(state: AgentGraphState):
    from .state import get_registered_coder
    session_id = state.get("session_id", "")
    coder = get_registered_coder(session_id)
    if coder:
        return coder
    return state.get("_coder")


def _blocking_tool_approval(state: AgentGraphState, *, tool_name: str, desc: str, params_preview: str) -> bool:
    coder = _get_coder(state)
    if not coder:
        return False

    io = coder.io
    if hasattr(io, "request_structured_approval"):
        return io.request_structured_approval("tool", desc, params_preview)
    return io.confirm_ask(f"Allow tool call?\n  {desc}\n  {params_preview}")


def _blocking_plan_approval(state: AgentGraphState, *, plan_text: str) -> bool:
    coder = _get_coder(state)
    if not coder:
        return False

    preview = plan_text[:500]
    return coder.io.confirm_ask(f"Approve this plan?\n\n{preview}")
