"""Mode-aware context budget and policy definitions.

Token budgets for repo map, history, focused files, and tool trace
are derived from ModeConfig.memory_policy — never hardcoded elsewhere.

ContextPolicy defines HOW each mode selects and renders context (detail level,
symbols, snippets, file preference), while ContextBudget defines HOW MUCH
token budget each section receives.

v1.3: ContextPolicy is consumed by repo_ranker, repo_renderer, and packer.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..modes.config import get_mode_config


@dataclass(frozen=True)
class ContextBudget:
    """Token allocation for each context section.

    These budgets are applied INSIDE pack_context() only — budget logic must
    not leak into graph nodes or runners.
    """

    repo_map_tokens: int
    history_tokens: int
    focused_file_tokens: int
    tool_trace_tokens: int
    reserve_tokens: int = 4096


@dataclass(frozen=True)
class ContextPolicy:
    """Content selection and rendering policy per mode.

    Controls WHAT gets into context and at what detail level — consumed by
    repo_ranker (candidate limits), repo_renderer (symbols/snippets), and
    packer (trace observability).
    """

    repo_detail_level: str       # "full" | "moderate" | "minimal"
    include_symbols: bool
    include_snippets: bool
    max_snippet_chars: int
    focused_file_preference: str  # "breadth" | "balanced" | "depth"
    max_repo_candidates: int

    @property
    def mode_goal(self) -> str:
        return {
            "full": "breadth scan — maximize file coverage",
            "moderate": "focused analysis — balanced coverage",
            "minimal": "minimal background — maximize file content",
        }.get(self.repo_detail_level, "unknown")


# Per-mode policy instances
_SNIFF_POLICY = ContextPolicy(
    repo_detail_level="full",
    include_symbols=True,
    include_snippets=True,
    max_snippet_chars=100,
    focused_file_preference="breadth",
    max_repo_candidates=40,
)

_PLAN_POLICY = ContextPolicy(
    repo_detail_level="moderate",
    include_symbols=True,
    include_snippets=True,
    max_snippet_chars=200,
    focused_file_preference="balanced",
    max_repo_candidates=25,
)

_ACT_POLICY = ContextPolicy(
    repo_detail_level="minimal",
    include_symbols=False,
    include_snippets=False,
    max_snippet_chars=0,
    focused_file_preference="depth",
    max_repo_candidates=15,
)

_POLICY_REGISTRY: dict[str, ContextPolicy] = {
    "sniff": _SNIFF_POLICY,
    "plan": _PLAN_POLICY,
    "act": _ACT_POLICY,
}


def get_context_policy(mode: str) -> ContextPolicy:
    """Return the ContextPolicy for *mode*, defaulting to ``act``."""
    return _POLICY_REGISTRY.get(mode, _ACT_POLICY)


def get_context_budget_for_mode(mode: str) -> ContextBudget:
    """Derive the context budget from the mode's MemoryPolicy."""
    cfg = get_mode_config(mode)
    mp = cfg.memory_policy
    return ContextBudget(
        repo_map_tokens=mp.repo_map_tokens,
        history_tokens=mp.history_tokens,
        focused_file_tokens=mp.focused_file_tokens,
        tool_trace_tokens=mp.tool_trace_tokens,
    )
