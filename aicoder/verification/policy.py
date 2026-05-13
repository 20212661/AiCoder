"""Verification policy — mode-aware task selection and level configuration.

Maps agent mode to a VerificationLevel, and selects which tasks to run
based on the level, file changes, and allow/deny lists.

All decisions are deterministic and fully testable without IO or LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .types import VerificationLevel, VerificationTask


# ---------------------------------------------------------------------------
# Mode → level mapping
# ---------------------------------------------------------------------------

_MODE_VERIFICATION_LEVELS: dict[str, VerificationLevel] = {
    "sniff": "light",
    "plan": "light",
    "act": "standard",
}

_VERIFICATION_LEVEL_ORDER: dict[VerificationLevel, int] = {
    "light": 0,
    "standard": 1,
    "strict": 2,
}


def get_verification_level(mode: str) -> VerificationLevel:
    """Return the default VerificationLevel for a given agent mode."""
    return _MODE_VERIFICATION_LEVELS.get(mode, "standard")


# ---------------------------------------------------------------------------
# Policy configuration
# ---------------------------------------------------------------------------

@dataclass
class VerificationPolicy:
    """Configuration for what verification tasks to run.

    level_override: if set, overrides mode-based level selection.
    allowed_tasks:  if non-empty, only these task IDs are considered.
    blocked_tasks:  these task IDs are always excluded.
    file_trigger_patterns: file extensions that trigger verification.
    """

    level_override: VerificationLevel | None = None
    allowed_tasks: frozenset[str] = frozenset()
    blocked_tasks: frozenset[str] = frozenset()
    file_trigger_patterns: frozenset[str] = frozenset({".py", ".js", ".ts"})

    def effective_level(self, mode: str) -> VerificationLevel:
        if self.level_override is not None:
            return self.level_override
        return get_verification_level(mode)


# ---------------------------------------------------------------------------
# Built-in task registry
# ---------------------------------------------------------------------------

# Task levels: light = syntax/basic, standard = + lint, strict = + full tests
_BUILTIN_TASKS: list[VerificationTask] = [
    VerificationTask(
        task_id="syntax_check",
        name="Python Syntax Check",
        command="python -m py_compile {files}",
        required=True,
        timeout_ms=30_000,
        level="light",
    ),
    VerificationTask(
        task_id="import_check",
        name="Import Check",
        command="python -c \"import {modules}\"",
        required=False,
        timeout_ms=30_000,
        level="light",
    ),
    VerificationTask(
        task_id="lint",
        name="Lint",
        command="python -m flake8 {files} --max-line-length=120",
        required=False,
        timeout_ms=60_000,
        level="standard",
    ),
    VerificationTask(
        task_id="type_check",
        name="Type Check",
        command="python -m mypy {files} --no-error-summary",
        required=False,
        timeout_ms=90_000,
        level="standard",
    ),
    VerificationTask(
        task_id="test_subset",
        name="Related Tests",
        command="python -m pytest {test_files} -x -q --timeout=60",
        required=False,
        timeout_ms=120_000,
        level="strict",
    ),
]


def get_builtin_tasks() -> list[VerificationTask]:
    """Return a copy of the built-in verification tasks."""
    return list(_BUILTIN_TASKS)


# ---------------------------------------------------------------------------
# Task selection
# ---------------------------------------------------------------------------


def select_verification_tasks(
    mode: str,
    policy: VerificationPolicy | None = None,
    changed_files: list[str] | None = None,
    extra_tasks: list[VerificationTask] | None = None,
) -> list[VerificationTask]:
    """Select which verification tasks to run.

    Selection logic:
    1. Determine effective verification level from mode + policy override
    2. Filter tasks whose level <= effective level
    3. Apply allowed_tasks / blocked_tasks filters
    4. Skip verification if no changed files match trigger patterns

    Returns an ordered list of tasks to execute.
    """
    policy = policy or VerificationPolicy()
    level = policy.effective_level(mode)
    level_rank = _VERIFICATION_LEVEL_ORDER[level]

    # Check file triggers — skip if no matching files
    if changed_files is not None and policy.file_trigger_patterns:
        has_trigger = any(
            any(f.endswith(ext) for ext in policy.file_trigger_patterns)
            for f in changed_files
        )
        if not has_trigger and not extra_tasks:
            return []

    # Start with built-in + extra tasks
    candidates = list(_BUILTIN_TASKS)
    if extra_tasks:
        candidates.extend(extra_tasks)

    # Filter by level
    selected: list[VerificationTask] = []
    for task in candidates:
        task_rank = _VERIFICATION_LEVEL_ORDER.get(task.level, 1)
        if task_rank > level_rank:
            continue

        # Apply blocklist
        if task.task_id in policy.blocked_tasks:
            continue

        # Apply allowlist (if non-empty)
        if policy.allowed_tasks and task.task_id not in policy.allowed_tasks:
            continue

        selected.append(task)

    return selected


def should_suppress_verification(
    task_id: str,
    current_iteration: int,
    recent_results: list[dict],
) -> bool:
    """Decide whether to suppress a verification task due to recent failure.

    Suppresses when:
    - The same task_id failed in the same iteration (duplicate retry).

    Args:
        task_id: The verification task to check.
        current_iteration: The current loop iteration.
        recent_results: Prior verification results as dicts with
            keys: task_id, status, iteration.

    Returns:
        True if the task should be suppressed.
    """
    for r in recent_results:
        if r.get("task_id") == task_id and r.get("status") == "failed" and r.get("iteration") == current_iteration:
            return True
    return False
