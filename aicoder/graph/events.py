"""Graph event types emitted during workflow execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


GraphEventType = Literal[
    "phase",
    "mode",
    "assistant_token",
    "assistant_final",
    "tool_started",
    "tool_finished",
    "approval_requested",
    "approval_resolved",
    "error",
]


@dataclass
class GraphEvent:
    type: GraphEventType
    payload: dict[str, Any] = field(default_factory=dict)
