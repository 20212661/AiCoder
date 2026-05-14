"""Mode-aware tool permission helpers.

All mode semantics are derived from ``aicoder.modes.config`` — the single
source of truth.  This module provides the permission decision logic
that the graph permission_node and ToolExecutor consult.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .modes.config import (
    FILE_EDIT_TOOLS,
    get_mode_config,
    is_read_only_mode,
)
from .mode_definitions import (
    get_visible_tools,
)

if TYPE_CHECKING:
    from .approval import ApprovalController
    from .tools.spec import ToolSpec


PermissionMode = Literal["sniff", "plan", "act"]
PermissionBehavior = Literal["allow", "ask", "deny"]

# Re-export for backward compatibility
PLAN_MODE_VISIBLE_TOOLS = get_mode_config("plan").visible_tools
PLAN_MODE_ALLOWED_TOOLS = PLAN_MODE_VISIBLE_TOOLS
ACT_MODE_AUTO_APPROVED_COMMANDS = frozenset({
    "mkdir",
    "touch",
})


@dataclass(frozen=True)
class ToolPermissionContext:
    mode: PermissionMode = "act"


@dataclass(frozen=True)
class PermissionDecision:
    behavior: PermissionBehavior
    reason: str = ""


def get_visible_tool_specs(
    tools: list["ToolSpec"],
    mode: PermissionMode,
) -> list["ToolSpec"]:
    """Filter tool specs to only those visible in the given mode."""
    visible = get_visible_tools(mode)
    return [tool for tool in tools if tool.name in visible]


def can_use_tool_in_mode(
    tool_name: str,
    params: dict[str, str] | None,
    context: ToolPermissionContext,
    approval: "ApprovalController | None" = None,
) -> PermissionDecision:
    """Decide whether a tool call is allowed in the current mode."""
    params = params or {}
    cfg = get_mode_config(context.mode)

    # Read-only modes (sniff, plan): deny file edits, restrict shell
    if not cfg.editable:
        if tool_name in FILE_EDIT_TOOLS:
            return PermissionDecision(
                behavior="deny",
                reason=(
                    f"{cfg.label} MODE is read-only. "
                    "Use read_file, search_files, list_files, list_code_defs, "
                    "run_shell (read-only), or switch to /act to implement changes."
                ),
            )
        if tool_name == "run_shell":
            command = params.get("command", "")
            if _is_safe_shell_command(command, approval):
                return PermissionDecision(
                    behavior="allow",
                    reason=f"{cfg.label} mode allows inspection shell commands",
                )
            return PermissionDecision(
                behavior="deny",
                reason=(
                    f"{cfg.label} MODE only allows read-only shell inspection commands. "
                    "Switch to /act before running mutating shell commands."
                ),
            )
        if tool_name in cfg.visible_tools:
            return PermissionDecision(
                behavior="allow",
                reason="read-only mode allows exploration tools",
            )

    # Act mode: allow with approval checks
    if context.mode == "act":
        if tool_name == "run_shell":
            command = (params.get("command", "") or "").strip()
            base_cmd = command.split()[0].lower() if command else ""
            if (
                approval is not None
                and command
                and approval.is_command_safe(command)
            ) or base_cmd in ACT_MODE_AUTO_APPROVED_COMMANDS:
                return PermissionDecision(
                    behavior="allow",
                    reason="act mode auto-approves routine shell commands",
                )

    return PermissionDecision(behavior="ask", reason="")


def _is_safe_shell_command(
    command: str,
    approval: "ApprovalController | None",
) -> bool:
    """Check if a shell command is safe for read-only modes."""
    command = (command or "").strip()
    if not command or approval is None:
        return False
    return approval.is_command_safe(command)
