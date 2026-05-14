"""Unified mode definitions — backward-compatible API.

The canonical source of truth is now ``aicoder.modes.config``.  This
module re-exports the legacy ``ModeDefinition`` class and helper
functions so that existing callers keep working, but internally
everything delegates to ``get_mode_config()``.
"""
from __future__ import annotations

from dataclasses import dataclass

from .modes.config import (
    ACT_MODE as _ACT_CFG,
    PLAN_MODE as _PLAN_CFG,
    SNIFF_MODE as _SNIFF_CFG,
    ALL_TOOLS,
    FILE_EDIT_TOOLS,
    READ_ONLY_TOOLS,
    get_mode_config,
    ModeConfig,
)


# ---------------------------------------------------------------------------
# Legacy ModeDefinition — kept for backward compatibility
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModeDefinition:
    """Canonical definition for a single execution mode.

    .. deprecated::
        Prefer :class:`aicoder.modes.config.ModeConfig` for new code.
    """
    name: str
    label: str
    description: str
    visible_tools: frozenset[str]
    editable: bool
    shell_policy: str  # "readonly" | "safe" | "all"
    prompt_summary: str


def _config_to_definition(cfg: ModeConfig) -> ModeDefinition:
    """Convert a new ModeConfig to the legacy ModeDefinition shape."""
    return ModeDefinition(
        name=cfg.name,
        label=cfg.label,
        description=cfg.prompt_style,
        visible_tools=cfg.visible_tools,
        editable=cfg.editable,
        shell_policy=cfg.shell_policy,
        prompt_summary=cfg.prompt_style,
    )


MODE_DEFINITIONS: dict[str, ModeDefinition] = {
    "sniff": _config_to_definition(_SNIFF_CFG),
    "plan": _config_to_definition(_PLAN_CFG),
    "act": _config_to_definition(_ACT_CFG),
}


def get_mode_def(mode: str) -> ModeDefinition:
    """Get the mode definition, defaulting to 'act' for unknown modes."""
    cfg = get_mode_config(mode)
    return _config_to_definition(cfg)


def get_visible_tools(mode: str) -> frozenset[str]:
    """Tool names visible to the LLM in the given mode."""
    return get_mode_config(mode).visible_tools


def is_edit_allowed(mode: str) -> bool:
    """Whether file editing is allowed in the given mode."""
    return get_mode_config(mode).editable


def get_shell_policy(mode: str) -> str:
    """Shell command policy for the given mode."""
    return get_mode_config(mode).shell_policy
