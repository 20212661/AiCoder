"""Event types for the lightweight EventLog-Lite layer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

EventKind = Literal[
    "user_message",
    "assistant_text",
    "assistant_thought",
    "tool_call",
    "tool_result",
    "tool_error",
    "step_started",
    "step_finished",
    "summary_inserted",
    "compaction_applied",
    "verification_started",
    "verification_result",
    "verification_finished",
    "recovery_decision",
    "recovery_action_applied",
    "recovery_routed",
    "checkpoint_skip",
    "verification_suppressed",
]


@dataclass
class AgentEventRecord:
    """A single structured event in the agent execution log.

    Payload must be structured dict data (not a single big string).
    """

    event_id: str
    session_id: str
    iteration: int
    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
