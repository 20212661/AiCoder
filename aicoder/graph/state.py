"""Graph state definition for the LangGraph agent workflow."""
from __future__ import annotations

from typing import Any, Literal, TypedDict


PermissionMode = Literal["sniff", "plan", "act"]
RunPhase = Literal[
    "idle",
    "preparing",
    "planning",
    "waiting_approval",
    "acting",
    "tool_running",
    "verifying",
    "summarizing",
    "done",
    "error",
]


class ApprovalRequest(TypedDict, total=False):
    id: str
    kind: Literal["plan", "tool", "command"]
    title: str
    body: str
    tool_name: str
    params: dict[str, Any]
    diff: str
    mode: PermissionMode


class ToolObservation(TypedDict, total=False):
    tool_name: str
    params: dict[str, Any]
    success: bool
    output: str
    error: str
    rejected: bool
    # v1.2: structured fields for condensation and observability
    tool_call_id: str
    error_type: str
    summary: str
    recommended_next: str
    files: list[str]
    iteration: int


# Module-level coder registry — keeps Coder instances out of serializable state
_coder_registry: dict[str, Any] = {}


def register_coder(session_id: str, coder) -> None:
    _coder_registry[session_id] = coder


def get_registered_coder(session_id: str):
    return _coder_registry.get(session_id)


def unregister_coder(session_id: str) -> None:
    _coder_registry.pop(session_id, None)


class AgentGraphState(TypedDict, total=False):
    session_id: str
    user_input: str
    messages: list[dict[str, Any]]
    mode: PermissionMode
    phase: RunPhase
    root: str
    current_plan: str
    approved_plan: str
    approval_request: ApprovalRequest
    approval_response: bool
    pending_tool_calls: list[dict[str, Any]]
    tool_observations: list[ToolObservation]
    final_response: str
    error: str
    loop_count: int
    max_loops: int
    runner_type: str
    verification_results: list[dict[str, Any]]
    recovery_decisions: list[dict[str, Any]]
    last_recovery_route: dict[str, Any]
    # v1.7: Session Federation fields (optional — absent when no federation)
    task_thread_id: str
    federation_context: str
    federation_trace: dict[str, Any]
