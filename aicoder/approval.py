"""
Auto-approval system — 3-tier permission model.

Modeled after Cline's AutoApprovalSettings + CommandPermissionController.

Tier 1: Global bypass
  - yolo mode          → approve everything
  - auto_approve_all   → approve everything

Tier 2: Per-category settings
  - read_files          → auto-approve file reads
  - edit_files          → auto-approve file edits
  - execute_safe_cmds   → auto-approve known-safe commands
  - execute_all_cmds    → auto-approve ALL commands
  - list_files          → auto-approve directory listings
  - search_files        → auto-approve regex searches
  - list_code_defs      → auto-approve code definition extraction

Tier 3: Extra guards
  - block_dangerous_cmds → always ask for dangerous commands
  - command_allowlist    → explicit list of allowed commands
  - blocklist            → explicit list of blocked paths/patterns
"""
from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass
class AutoApprovalSettings:
    """Per-category auto-approval flags."""

    # Global
    yolo: bool = False
    auto_approve_all: bool = False

    # Per tool category
    read_files: bool = False
    edit_files: bool = False
    execute_safe_cmds: bool = True    # safe commands auto-approved by default
    execute_all_cmds: bool = False
    list_files: bool = True            # low-risk, auto-approved by default
    search_files: bool = True
    list_code_defs: bool = True

    # Extra guards
    block_dangerous_cmds: bool = True
    command_allowlist: list[str] = field(default_factory=list)
    blocklist: list[str] = field(default_factory=list)  # blocked paths/patterns

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "AutoApprovalSettings":
        if not d:
            return cls()
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})


# ---------------------------------------------------------------------------
# Tool → category mapping
# ---------------------------------------------------------------------------

TOOL_CATEGORY_MAP: dict[str, str] = {
    "read_file": "read_files",
    "write_file": "edit_files",
    "edit_file": "edit_files",
    "run_shell": "execute_safe_cmds",  # handled separately
    "list_files": "list_files",
    "search_files": "search_files",
    "list_code_defs": "list_code_defs",
}

# Tools that should always show a diff/confirmation even when auto-approved
ALWAYS_SHOW_RESULT = {"write_file", "edit_file", "run_shell"}


# ---------------------------------------------------------------------------
# Command safety classification
# ---------------------------------------------------------------------------

# Commands that are known-safe — auto-approve when execute_safe_cmds is True
SAFE_COMMAND_PATTERNS: list[str] = [
    # Navigation / inspection
    r"^(ls|dir)\b",
    r"^(cat|type)\b",
    r"^(pwd|cd)\b",
    r"^(echo|printf)\b",
    r"^(head|tail)\b",
    r"^(find)\b",
    r"^(grep|rg)\b",
    r"^(wc|sort|uniq)\b",
    r"^(file|stat)\b",
    # Git read-only
    r"^git\s+(status|log|diff|branch|show|rev-parse|remote\s+-v)\b",
    r"^git\s+(stash\s+list|tag|describe|ls-files)\b",
    # Package managers (list/info only)
    r"^(npm|pnpm|yarn)\s+(list|info|why|outdated)\b",
    r"^(pip|pip3)\s+(list|show|freeze)\b",
    r"^(cargo)\s+(check|tree)\b",
    r"^(go)\s+(env|version|list)\b",
    # Version checks
    r"^(node|python|python3|ruby|perl|rustc|gcc|clang)\s+(--version|-v|-V)\b",
    r"^(git|docker|kubectl)\s+(--version|version)\b",
    # Environment
    r"^(env|printenv|set|export)\b",
    r"^(which|where|whereis|type)\b",
]

# Commands that are ALWAYS dangerous — require explicit approval
DANGEROUS_COMMAND_PATTERNS: list[tuple[str, str]] = [
    (r"\brm\s+-rf\s+/", "DESTRUCTIVE: rm -rf on root"),
    (r"\brm\s+-rf\s+~", "DESTRUCTIVE: rm -rf on home"),
    (r"\brm\s+-rf\s+\*", "DESTRUCTIVE: recursive force delete"),
    (r">\s*/dev/sd[a-z]", "DESTRUCTIVE: raw disk write"),
    (r"\bdd\s+if=", "DESTRUCTIVE: raw disk copy (dd)"),
    (r"\bchmod\s+-R\s+777\s+/", "DESTRUCTIVE: chmod 777 on root"),
    (r"\bgit\s+push\s+--force\b.*\b(main|master)\b", "DESTRUCTIVE: force push to main"),
    (r":\(\)\s*\{\s*:\|:&\s*\}\s*;", "FORK BOMB detected"),
    (r"\bformat\s+[A-Z]:", "DESTRUCTIVE: disk format"),
    (r"\bshutdown\b", "DESTRUCTIVE: system shutdown"),
    (r"\breboot\b", "DESTRUCTIVE: system reboot"),
    (r"\bdel\s+/[fsq].*\\WINDOWS", "DESTRUCTIVE: Windows system file deletion"),
]


# ---------------------------------------------------------------------------
# Permission controller
# ---------------------------------------------------------------------------

class ApprovalController:
    """Central permission decision engine."""

    def __init__(self, settings: AutoApprovalSettings | None = None):
        self.settings = settings or AutoApprovalSettings()

    # ---- public API --------------------------------------------------------

    def should_auto_approve(self, tool_name: str, params: dict | None = None) -> tuple[bool, str]:
        """Return (auto_approve: bool, reason: str)."""
        params = params or {}

        # Tier 1: global bypass
        if self.settings.yolo or self.settings.auto_approve_all:
            return True, "global bypass (yolo / auto-approve-all)"

        # Tier 2: per-category
        category = TOOL_CATEGORY_MAP.get(tool_name)
        if category is None:
            return False, f"unknown tool category: {tool_name}"

        # run_shell has special handling
        if tool_name == "run_shell":
            return self._check_command(params.get("command", ""))

        # Other tools: check the category flag
        if getattr(self.settings, category, False):
            return True, f"auto-approved: {category}"

        # Tier 3: blocklist check for file tools
        if tool_name in ("write_file", "edit_file"):
            path = params.get("path", "") or params.get("file_path", "")
            if self._is_blocked(path):
                return False, f"path in blocklist: {path}"

        return False, f"requires approval ({category})"

    def is_command_safe(self, command: str) -> bool:
        """Check if a shell command is in the safe list."""
        for pattern in SAFE_COMMAND_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False

    def is_command_dangerous(self, command: str) -> tuple[bool, str]:
        """Check if a shell command matches known-dangerous patterns."""
        for pattern, warning in DANGEROUS_COMMAND_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True, warning
        return False, ""

    def command_in_allowlist(self, command: str) -> bool:
        """Check if a command matches any entry in the explicit allowlist."""
        if not self.settings.command_allowlist:
            return False
        cmd_base = command.strip().split()[0] if command.strip() else ""
        for allowed in self.settings.command_allowlist:
            if allowed == cmd_base or command.strip().startswith(allowed):
                return True
        return False

    # ---- internals ---------------------------------------------------------

    def _check_command(self, command: str) -> tuple[bool, str]:
        """Full command approval check."""
        # Always allow safe commands when execute_safe_cmds is on
        if self.settings.execute_safe_cmds and self.is_command_safe(command):
            return True, "safe command auto-approved"

        # Always allow commands in the explicit allowlist
        if self.command_in_allowlist(command):
            return True, "command in allowlist"

        # Always approve when execute_all_cmds is on and command is not dangerous
        if self.settings.execute_all_cmds:
            is_dangerous, warning = self.is_command_dangerous(command)
            if not is_dangerous:
                return True, "all commands auto-approved"
            if self.settings.block_dangerous_cmds:
                return False, warning
            return True, "dangerous command allowed (block_dangerous_cmds disabled)"

        # Block dangerous commands
        if self.settings.block_dangerous_cmds:
            is_dangerous, warning = self.is_command_dangerous(command)
            if is_dangerous:
                return False, warning

        return False, "requires approval"

    def _is_blocked(self, path: str) -> bool:
        if not self.settings.blocklist or not path:
            return False
        for pattern in self.settings.blocklist:
            try:
                if re.search(pattern, path):
                    return True
            except re.error:
                if pattern in path:
                    return True
        return False


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    return Path.home() / ".aicoder" / "approval_settings.json"


def load_approval_settings() -> AutoApprovalSettings:
    path = _config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return AutoApprovalSettings.from_dict(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return AutoApprovalSettings()


def save_approval_settings(settings: AutoApprovalSettings) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings.to_dict(), f, ensure_ascii=False, indent=2)
