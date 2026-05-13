"""Runner layer for agent model interaction — design doc §6."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aicoder.runners.base_agent_runner import BaseAgentRunner

_runner_registry: dict[str, "BaseAgentRunner"] = {}


def register_runner(session_id: str, runner: "BaseAgentRunner") -> None:
    _runner_registry[session_id] = runner


def get_runner(session_id: str) -> "BaseAgentRunner | None":
    return _runner_registry.get(session_id)


def unregister_runner(session_id: str) -> None:
    _runner_registry.pop(session_id, None)
