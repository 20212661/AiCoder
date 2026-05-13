"""Checkpoint recovery guard — idempotency protection for tool execution.

Scans persisted events to identify tool_call + tool_result pairs that
completed before a crash. On resume, completed tools are skipped and
their observations are restored instead of re-executed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from ..events.types import AgentEventRecord


def _tool_key(tool_name: str, params: dict, tool_call_id: str = "") -> str:
    """Generate a unique key for a tool invocation."""
    if tool_call_id:
        return f"tc:{tool_call_id}"
    # Fallback: hash name + sorted params for CoT runners
    params_str = json.dumps(params, sort_keys=True)
    h = hashlib.md5(f"{tool_name}:{params_str}".encode()).hexdigest()[:12]
    return f"cot:{tool_name}:{h}"


@dataclass
class CompletedTool:
    """Record of a completed tool invocation with its observation."""

    key: str
    tool_name: str
    tool_call_id: str = ""
    observation: dict[str, Any] = field(default_factory=dict)


class CheckpointGuard:
    """Tracks completed tool invocations to prevent re-execution on resume.

    Built from persisted events via ``from_events()``. Consulted by
    ``execute_tool_node`` to decide whether to skip a tool call.
    """

    def __init__(self) -> None:
        self._completed: dict[str, CompletedTool] = {}

    def is_completed(self, tool_name: str, params: dict, tool_call_id: str = "") -> bool:
        key = _tool_key(tool_name, params, tool_call_id)
        return key in self._completed

    def get_observation(self, tool_name: str, params: dict, tool_call_id: str = "") -> dict[str, Any] | None:
        key = _tool_key(tool_name, params, tool_call_id)
        ct = self._completed.get(key)
        return ct.observation if ct else None

    def mark_completed(self, tool_name: str, params: dict, tool_call_id: str = "", observation: dict[str, Any] | None = None) -> None:
        key = _tool_key(tool_name, params, tool_call_id)
        self._completed[key] = CompletedTool(
            key=key,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            observation=observation or {},
        )

    @property
    def completed_count(self) -> int:
        return len(self._completed)

    @classmethod
    def from_events(cls, events: list[AgentEventRecord]) -> CheckpointGuard:
        """Build a guard from persisted events.

        Scans for tool_call + (tool_result | tool_error) pairs.
        A tool is considered completed if it has both a tool_call and
        a corresponding result event in the same (iteration, step_id).
        """
        guard = cls()
        # Index: (iteration, step_id) -> tool_call info
        pending_calls: dict[tuple[int, str], dict[str, Any]] = {}

        for ev in events:
            if ev.kind == "tool_call":
                step_id = ev.payload.get("step_id", "")
                key = (ev.iteration, step_id)
                pending_calls[key] = {
                    "tool_name": ev.payload.get("tool_name", ""),
                    "tool_call_id": ev.payload.get("tool_call_id", ""),
                    "tool_input": ev.payload.get("tool_input", {}),
                }

            elif ev.kind in ("tool_result", "tool_error"):
                step_id = ev.payload.get("step_id", "")
                key = (ev.iteration, step_id)
                call_info = pending_calls.get(key)
                if call_info:
                    tool_name = call_info["tool_name"]
                    tool_call_id = call_info.get("tool_call_id", "")
                    params = call_info.get("tool_input", {})
                    if isinstance(params, str):
                        params = {"raw": params}
                    meta = ev.payload.get("tool_meta", {})
                    observation = {
                        "tool_name": tool_name,
                        "success": meta.get("success", ev.kind == "tool_result"),
                        "output": ev.payload.get("observation", ""),
                        "error": ev.payload.get("error", ""),
                        "rejected": meta.get("rejected", False),
                        "tool_call_id": tool_call_id,
                        **meta,
                    }
                    guard.mark_completed(
                        tool_name=tool_name,
                        params=params,
                        tool_call_id=tool_call_id,
                        observation=observation,
                    )

        return guard


# Module-level registry for guard instances (mirrors coder registry pattern)
_guard_registry: dict[str, CheckpointGuard] = {}


def register_guard(session_id: str, guard: CheckpointGuard) -> None:
    _guard_registry[session_id] = guard


def get_guard(session_id: str) -> CheckpointGuard | None:
    return _guard_registry.get(session_id)


def unregister_guard(session_id: str) -> None:
    _guard_registry.pop(session_id, None)
