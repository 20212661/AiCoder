"""Structured types for repo context — file hints, build results, policy flags.

Repo context is NOT a full-text dump. It is a compressed summary of the
project, where each file entry carries metadata explaining why it was
selected (reason, score, optional symbols/snippet).

Design reference: docs/aiCoder-v1.3-实现级任务拆解.md §5
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RepoFileHint:
    """One file selected for repo context, with scoring and metadata."""

    path: str
    reason: str  # e.g. "focused", "recently_edited", "important_root_file"
    score: float = 0.0
    symbols: list[str] = field(default_factory=list)
    snippet: str = ""


@dataclass
class RepoContextBuildResult:
    """Output of repo context construction — structured result for packer."""

    files: list[RepoFileHint] = field(default_factory=list)
    rendered_messages: list[dict] = field(default_factory=list)
    token_estimate: int = 0
