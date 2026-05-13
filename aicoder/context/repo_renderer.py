"""Repo Renderer — turn ranked file hints into compact LLM context messages.

Renders each file as a short summary line (path + reason + optional symbols),
never the full file content. Snips snippets to a few lines. Honors token budget.

v1.3: Detail flags (include_symbols, include_snippets, max_snippet_chars)
are derived from ContextPolicy instead of hardcoded mode checks.
"""
from __future__ import annotations

from typing import Any

from .repo_types import RepoFileHint, RepoContextBuildResult
from .policies import get_context_policy

# Rough token estimate: ~4 chars per token
_CHARS_PER_TOKEN = 4

# Max lines for a single file entry
_MAX_ENTRY_LINES = 6


def render_repo_context(
    hints: list[RepoFileHint],
    budget_tokens: int,
    mode: str,
) -> RepoContextBuildResult:
    """Render ranked file hints into compact LLM messages within budget.

    Each file gets at most:
    - Line 1: path — reason
    - Line 2: Contains: symbol1, symbol2, ...  (if symbols present)
    - Line 3: snippet (short, if present)

    Files are added in score order until budget is exhausted.
    """
    if not hints:
        return RepoContextBuildResult()

    policy = get_context_policy(mode)

    budget_chars = budget_tokens * _CHARS_PER_TOKEN
    included: list[RepoFileHint] = []
    lines: list[str] = []
    used_chars = 0

    # Header
    header = "# Project Map\n"
    used_chars += len(header)

    for hint in hints:
        entry_lines = _render_entry(
            hint,
            include_symbols=policy.include_symbols,
            include_snippets=policy.include_snippets,
            max_snippet_chars=policy.max_snippet_chars,
        )
        entry_text = "\n".join(entry_lines)
        entry_chars = len(entry_text) + 1  # +1 for newline separator

        if used_chars + entry_chars > budget_chars:
            break

        lines.append(entry_text)
        used_chars += entry_chars
        included.append(hint)

    if not lines:
        return RepoContextBuildResult()

    full_text = header + "\n".join(lines) + "\n"
    token_est = len(full_text) // _CHARS_PER_TOKEN

    messages = [
        {"role": "user", "content": full_text},
        {"role": "assistant", "content": "Ok, I see the project structure."},
    ]

    return RepoContextBuildResult(
        files=included,
        rendered_messages=messages,
        token_estimate=token_est,
    )


def _render_entry(
    hint: RepoFileHint,
    include_symbols: bool,
    include_snippets: bool,
    max_snippet_chars: int,
) -> list[str]:
    """Render one file entry as a list of short lines."""
    lines: list[str] = []

    # Line 1: path — reason
    lines.append(f"- {hint.path} — {hint.reason}")

    # Line 2: symbols (if present and policy allows)
    if include_symbols and hint.symbols:
        sym_text = ", ".join(hint.symbols[:8])
        lines.append(f"  Contains: {sym_text}")

    # Line 3: snippet (if present and policy allows)
    if include_snippets and hint.snippet and max_snippet_chars > 0:
        snippet = hint.snippet[:max_snippet_chars]
        if len(hint.snippet) > max_snippet_chars:
            snippet += "..."
        lines.append(f"  Snippet: {snippet}")

    # Cap at max lines
    return lines[:_MAX_ENTRY_LINES]
