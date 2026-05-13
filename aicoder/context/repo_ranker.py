"""Lightweight file ranking for repo context — score and prioritize files.

Picks which files deserve a spot in the limited repo context budget.
Scoring is simple and deterministic (no ML / PageRank in v1.3).

Priority tiers (higher = more important):
1. focused      — user explicitly added / current context files
2. recently_edited — files with git modifications (if repo available)
3. search_hit   — files mentioned in recent tool calls / observations
4. important_root_file — README, pyproject.toml, package.json, etc.
5. shallow_match — files in top-level directories matching task keywords
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from .repo_types import RepoFileHint

if TYPE_CHECKING:
    from ..coders.base_coder import Coder

# Priority scores per tier
_SCORE_FOCUSED = 1.0
_SCORE_RECENTLY_EDITED = 0.8
_SCORE_SEARCH_HIT = 0.6
_SCORE_IMPORTANT_ROOT = 0.5
_SCORE_SHALLOW = 0.2

# Root files that are important for understanding any project
_IMPORTANT_ROOT_FILES = frozenset({
    "README", "README.md", "README.txt", "README.rst",
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "requirements.txt", "Pipfile",
    "Dockerfile", "Makefile",
    "AGENTS.md", "CLAUDE.md",
    ".env.example", "tsconfig.json", "Cargo.toml",
    "go.mod", "Gemfile",
})


def collect_candidate_files(coder: "Coder") -> list[str]:
    """Collect all file paths that are candidates for repo context.

    Sources:
    1. abs_fnames (user-added files)
    2. abs_read_only_fnames
    3. Files from the workspace root (top 2 levels)
    """
    candidates: set[str] = set()

    # Focused files (in-chat)
    for abs_path in getattr(coder, "abs_fnames", set()):
        rel = _to_rel(abs_path, coder.root)
        if rel:
            candidates.add(rel)

    # Read-only files
    for abs_path in getattr(coder, "abs_read_only_fnames", set()):
        rel = _to_rel(abs_path, coder.root)
        if rel:
            candidates.add(rel)

    # Workspace scan (top 2 levels, skip common ignores)
    root = getattr(coder, "root", "")
    if root and os.path.isdir(root):
        candidates.update(_scan_workspace(root, max_depth=2))

    return sorted(candidates)


def rank_repo_files(
    coder: "Coder",
    mode: str,
) -> list[RepoFileHint]:
    """Score and rank candidate files for repo context.

    Returns a list of RepoFileHint sorted by score descending.
    The mode parameter controls how many candidates to consider:
    - sniff: broad (many candidates, shallow scan)
    - plan:  moderate
    - act:   narrow (fewer candidates, focused on what matters)
    """
    candidates = collect_candidate_files(coder)
    hints: list[RepoFileHint] = []

    focused = _get_focused_set(coder)
    recently_edited = _get_recently_edited(coder)
    search_hits = _get_search_hits(coder)

    for rel_path in candidates:
        score, reason = _score_file(
            rel_path, focused, recently_edited, search_hits, mode,
        )
        hints.append(RepoFileHint(path=rel_path, reason=reason, score=score))

    hints.sort(key=lambda h: h.score, reverse=True)

    # Mode-specific cap from ContextPolicy
    from .policies import get_context_policy
    policy = get_context_policy(mode)
    return hints[:policy.max_repo_candidates]


def _score_file(
    path: str,
    focused: set[str],
    recently_edited: set[str],
    search_hits: set[str],
    mode: str,
) -> tuple[float, str]:
    """Return (score, reason) for a single file."""
    basename = os.path.basename(path)

    if path in focused:
        return _SCORE_FOCUSED, "focused"

    if path in recently_edited:
        return _SCORE_RECENTLY_EDITED, "recently_edited"

    if path in search_hits:
        return _SCORE_SEARCH_HIT, "search_hit"

    if _is_important_root_file(path):
        return _SCORE_IMPORTANT_ROOT, "important_root_file"

    # Shallow match: top-level or near-top-level file
    depth = path.count(os.sep)
    if depth <= 1:
        return _SCORE_SHALLOW, "shallow_match"

    # Deeper files get a small bonus in sniff mode
    base = _SCORE_SHALLOW * 0.5 if mode == "sniff" else _SCORE_SHALLOW * 0.3
    return base, "deep_file"


def _get_focused_set(coder: "Coder") -> set[str]:
    """Get relative paths of user-added (focused) files."""
    result: set[str] = set()
    for abs_path in getattr(coder, "abs_fnames", set()):
        rel = _to_rel(abs_path, coder.root)
        if rel:
            result.add(rel)
    return result


def _get_recently_edited(coder: "Coder") -> set[str]:
    """Get files recently modified via git (if available)."""
    result: set[str] = set()
    repo = getattr(coder, "repo", None)
    if not repo:
        return result
    try:
        r = repo.repo
        # Get files changed in the last 5 commits
        for commit in list(r.iter_commits(max_count=5)):
            for diff in commit.diff(commit.parents[0] if commit.parents else None):
                path = diff.a_path or diff.b_path
                if path:
                    result.add(path)
    except Exception:
        pass
    return result


def _get_search_hits(coder: "Coder") -> set[str]:
    """Get files mentioned in recent tool observations (step store)."""
    result: set[str] = set()
    try:
        from ..context.history_view import _get_step_records
        steps = _get_step_records(coder)
        for step in steps[-10:]:
            for f in getattr(step, "files", []):
                if f:
                    rel = _to_rel(f, coder.root)
                    if rel:
                        result.add(rel)
            # Also check action_input for file paths
            action_input = getattr(step, "action_input", None)
            if isinstance(action_input, dict):
                p = action_input.get("path", "")
                if p:
                    rel = _to_rel(p, coder.root)
                    if rel:
                        result.add(rel)
    except Exception:
        pass
    return result


def _is_important_root_file(path: str) -> bool:
    """Check if file is a well-known project root file."""
    basename = os.path.basename(path)
    # Must be in root (no path separators)
    if os.sep in path:
        return False
    return basename in _IMPORTANT_ROOT_FILES


def _scan_workspace(root: str, max_depth: int = 2) -> set[str]:
    """Walk the workspace up to max_depth, returning relative file paths."""
    skip_dirs = {
        "node_modules", "__pycache__", ".git", ".venv", "venv", "env",
        "dist", "build", ".mypy_cache", ".pytest_cache", ".tox",
        "target", ".next", ".nuxt", "vendor",
    }
    result: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
        if depth >= max_depth:
            dirnames.clear()
            continue
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for fn in filenames:
            if fn.startswith("."):
                continue
            rel = os.path.join(rel_dir, fn) if rel_dir != "." else fn
            result.add(rel.replace("\\", "/"))
    return result


def _to_rel(abs_path: str, root: str) -> str | None:
    """Convert absolute path to relative, or None if outside root."""
    try:
        rel = os.path.relpath(abs_path, root).replace("\\", "/")
        if rel.startswith(".."):
            return None
        return rel
    except (ValueError, TypeError):
        return None
