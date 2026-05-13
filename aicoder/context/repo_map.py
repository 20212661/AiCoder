"""Repo context builder — real implementation using ranker + renderer.

v1.3: Uses RepoRanker to collect and score files, then RepoRenderer to
produce compact LLM messages within the mode-specific token budget.

The interface is unchanged from v1.1:
    build_repo_context(coder, mode, budget_tokens) -> list[dict]

Internally:
    1. collect candidates via RepoRanker
    2. rank by priority
    3. render within budget
    4. return messages (or [] on failure)
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..coders.base_coder import Coder


def build_repo_context(
    coder: "Coder",
    mode: str,
    budget_tokens: int,
) -> list[dict[str, Any]]:
    """Build repo context messages within the given token budget.

    Pipeline: collect -> rank -> render -> return messages.
    Falls back to empty list on any failure — repo context must not
    crash the main chain.

    Args:
        coder: The Coder instance.
        mode: Current mode (sniff/plan/act) — controls ranking and rendering.
        budget_tokens: Max tokens for repo context (from ContextBudget).

    Returns:
        List of LLM message dicts, or empty list on failure.
    """
    if budget_tokens <= 0:
        return []

    try:
        from .repo_ranker import rank_repo_files
        from .repo_renderer import render_repo_context

        ranked = rank_repo_files(coder, mode)
        result = render_repo_context(ranked, budget_tokens, mode)
        return result.rendered_messages

    except Exception:
        # Graceful fallback: repo context failure must not break the main chain
        return []
