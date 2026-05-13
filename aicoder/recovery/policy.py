"""Recovery policy — configurable rules for failure recovery actions.

Defines what kinds of failures are retryable, how many retries are
allowed, and when to escalate or halt.  All decisions are deterministic
and fully testable without IO or LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


RecoveryAction = Literal["retry", "fallback", "halt"]


@dataclass
class RecoveryPolicy:
    """Configuration for recovery behavior after failures.

    Attributes:
        max_retries: Maximum consecutive retry attempts before halting.
        retryable_error_types: Error types eligible for automatic retry.
        halt_on_required_violation: Halt immediately when a required
            verification task fails (no retry).
        cooldown_hint: Suggestion to include in next_hint for retries.
    """

    max_retries: int = 3
    retryable_error_types: frozenset[str] = frozenset({
        "verification_failed",
        "tool_error",
        "timeout",
        "subprocess_error",
    })
    halt_on_required_violation: bool = False
    cooldown_hint: str = "Consider simplifying the change or checking syntax."

    def is_retryable(self, error_type: str) -> bool:
        return error_type in self.retryable_error_types


@dataclass
class RecoveryContext:
    """Input to the recovery decision engine.

    Carries information about the failure that just occurred.
    """

    error_type: str
    retry_count: int = 0
    tool_name: str = ""
    task_id: str = ""
    is_required: bool = False
    detail: str = ""


@dataclass
class RecoveryDecision:
    """Output of the recovery decision engine.

    Attributes:
        action: What to do next — retry, fallback, or halt.
        reason: Human-readable explanation of why this action was chosen.
        next_hint: Suggestion for the next step (used by the LLM).
        source_step_id: Step that triggered this decision (traceability).
        verification_task: Task ID of the verification that failed.
    """

    action: RecoveryAction
    reason: str
    next_hint: str = ""
    source_step_id: str = ""
    verification_task: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "reason": self.reason,
            "next_hint": self.next_hint,
            "source_step_id": self.source_step_id,
            "verification_task": self.verification_task,
        }
