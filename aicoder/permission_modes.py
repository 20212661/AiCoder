"""Mode-aware tool permission helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .approval import ApprovalController
    from .tools.spec import ToolSpec


PermissionMode = Literal["sniff", "plan", "act"]
PermissionBehavior = Literal["allow", "ask", "deny"]

READ_ONLY_TOOLS = frozenset({
    "read_file",
    "search_files",
    "list_files",
    "list_code_defs",
})
PLAN_MODE_VISIBLE_TOOLS = frozenset((*READ_ONLY_TOOLS, "run_shell"))
PLAN_MODE_ALLOWED_TOOLS = PLAN_MODE_VISIBLE_TOOLS
FILE_EDIT_TOOLS = frozenset({"edit_file", "write_file"})
ACT_MODE_AUTO_APPROVED_TOOLS: frozenset[str] = frozenset()
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
    if mode in ("plan", "sniff"):
        return [tool for tool in tools if tool.name in PLAN_MODE_VISIBLE_TOOLS]
    return list(tools)


def can_use_tool_in_mode(
    tool_name: str,
    params: dict[str, str] | None,
    context: ToolPermissionContext,
    approval: "ApprovalController | None" = None,
) -> PermissionDecision:
    params = params or {}

    if context.mode in ("plan", "sniff"):
        if tool_name in FILE_EDIT_TOOLS:
            mode_label = "SNIFF" if context.mode == "sniff" else "PLAN"
            return PermissionDecision(
                behavior="deny",
                reason=(
                    f"{mode_label} MODE is read-only. Use read_file, search_files, "
                    "list_files, list_code_defs, or /act to implement changes."
                ),
            )
        if tool_name == "run_shell":
            command = params.get("command", "")
            if _is_plan_safe_shell_command(command, approval):
                return PermissionDecision(
                    behavior="allow",
                    reason="read-only mode allows inspection shell commands",
                )
            mode_label = "SNIFF" if context.mode == "sniff" else "PLAN"
            return PermissionDecision(
                behavior="deny",
                reason=(
                    f"{mode_label} MODE only allows read-only shell inspection commands. "
                    "Switch to /act before running mutating shell commands."
                ),
            )
        if tool_name in PLAN_MODE_ALLOWED_TOOLS:
            return PermissionDecision(
                behavior="allow",
                reason="read-only mode allows exploration tools",
            )

    if context.mode == "act":
        if tool_name in ACT_MODE_AUTO_APPROVED_TOOLS:
            return PermissionDecision(
                behavior="allow",
                reason="act mode allows direct file edits",
            )
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


def _is_plan_safe_shell_command(
    command: str,
    approval: "ApprovalController | None",
) -> bool:
    command = (command or "").strip()
    if not command or approval is None:
        return False
    return approval.is_command_safe(command)
