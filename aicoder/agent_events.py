"""Unified step-level event system for agent execution observability.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §11
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

StepEventType = Literal[
    "agent.step.created",
    "agent.step.thought",
    "agent.step.action",
    "agent.step.observation",
    "agent.step.final",
    "agent.step.error",
]


@dataclass
class StepEvent:
    """A single step-level event emitted during agent execution."""

    type: StepEventType
    step_id: str
    iteration: int
    data: dict[str, Any] = field(default_factory=dict)


def emit_step_event(io, event: StepEvent) -> None:
    """Emit a step event through the IO layer.

    RPC mode (JsonRpcIO): sends as ``agent/step`` notification.
    CLI mode (InputOutput): maps to tool_output / tool_error.
    """
    event_data = {
        "type": event.type,
        "step_id": event.step_id,
        "iteration": event.iteration,
        "data": event.data,
    }

    # RPC path: JsonRpcIO has _notify
    if hasattr(io, "_notify"):
        io._notify("agent/step", event_data)
        return

    # CLI fallback: map to existing IO methods
    event_type = event.type
    if event_type == "agent.step.error":
        io.tool_error(event.data.get("error", ""))
    elif event_type == "agent.step.final":
        io.print_assistant_output(event.data.get("final_answer", ""))
    else:
        label = event_type.rsplit(".", 1)[-1]
        text = event.data.get("thought") or event.data.get("observation") or ""
        if text:
            io.tool_output(f"[{label}] {text}")
