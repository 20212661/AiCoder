"""Centralized mode configuration.

Every module that needs mode behavior (permissions, prompts, context
budgets, UI) must derive its logic from the definitions here.  No module
may invent its own mode-specific rules independently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ModeName = Literal["sniff", "plan", "act"]


@dataclass(frozen=True)
class MemoryPolicy:
    """Token budget and behaviour knobs for context packing."""

    repo_map_tokens: int
    history_tokens: int
    focused_file_tokens: int
    tool_trace_tokens: int
    enable_summary: bool = False
    enable_prune: bool = False


@dataclass(frozen=True)
class ModeConfig:
    """Canonical definition for a single execution mode."""

    name: ModeName
    label: str
    editable: bool
    visible_tools: frozenset[str]
    shell_policy: str  # "readonly" | "safe" | "all"
    prompt_style: str
    output_style: str
    memory_policy: MemoryPolicy


# ---------------------------------------------------------------------------
# Tool sets (shared with mode_definitions.py during transition)
# ---------------------------------------------------------------------------

ALL_TOOLS = frozenset({
    "read_file", "search_files", "list_files", "list_code_defs",
    "run_shell", "edit_file", "write_file",
})

READ_ONLY_TOOLS = frozenset({
    "read_file", "search_files", "list_files", "list_code_defs",
})

FILE_EDIT_TOOLS = frozenset({"edit_file", "write_file"})

# ---------------------------------------------------------------------------
# Three canonical mode instances
# ---------------------------------------------------------------------------

SNIFF_MODE = ModeConfig(
    name="sniff",
    label="SNIFF",
    editable=False,
    visible_tools=READ_ONLY_TOOLS | {"run_shell"},
    shell_policy="readonly",
    prompt_style=(
        "SNIFF mode: read-only investigation. "
        "Use read_file, search_files, list_files, list_code_defs, "
        "and read-only run_shell (ls, cat, git status, etc.). "
        "No file edits. Output in sniff-report format. "
        "Switch to /plan for structured proposals or /act to implement."
    ),
    output_style="structured-report",
    memory_policy=MemoryPolicy(
        repo_map_tokens=8000,
        history_tokens=16000,
        focused_file_tokens=4000,
        tool_trace_tokens=4000,
        enable_summary=True,
        enable_prune=True,
    ),
)

PLAN_MODE = ModeConfig(
    name="plan",
    label="PLAN",
    editable=False,
    visible_tools=READ_ONLY_TOOLS | {"run_shell"},
    shell_policy="readonly",
    prompt_style=(
        "PLAN mode: read-only planning. "
        "Use read_file, search_files, list_files, list_code_defs, "
        "and read-only run_shell (ls, cat, git status, etc.). "
        "No file edits. End with a concise plan and switch to /act."
    ),
    output_style="plan-proposal",
    memory_policy=MemoryPolicy(
        repo_map_tokens=6000,
        history_tokens=12000,
        focused_file_tokens=6000,
        tool_trace_tokens=6000,
        enable_summary=True,
        enable_prune=False,
    ),
)

ACT_MODE = ModeConfig(
    name="act",
    label="ACT",
    editable=True,
    visible_tools=ALL_TOOLS,
    shell_policy="safe",
    prompt_style=(
        "ACT mode: full implementation. All tools available. "
        "File edits and shell commands require approval unless auto-approved."
    ),
    output_style="implementation",
    memory_policy=MemoryPolicy(
        repo_map_tokens=4000,
        history_tokens=20000,
        focused_file_tokens=8000,
        tool_trace_tokens=8000,
        enable_summary=False,
        enable_prune=False,
    ),
)

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

_MODE_REGISTRY: dict[str, ModeConfig] = {
    "sniff": SNIFF_MODE,
    "plan": PLAN_MODE,
    "act": ACT_MODE,
}


def get_mode_config(mode: str) -> ModeConfig:
    """Return the ModeConfig for *mode*, defaulting to ``act``."""
    return _MODE_REGISTRY.get(mode, ACT_MODE)


def is_read_only_mode(mode: str) -> bool:
    """Return True when the mode does not allow file edits."""
    return not get_mode_config(mode).editable
