"""Recovery decision engine — maps failure context to a recovery action.

The engine is a pure function: given a RecoveryContext and RecoveryPolicy,
it returns a deterministic RecoveryDecision.  No IO, no state mutation.
"""
from __future__ import annotations

from .policy import RecoveryAction, RecoveryContext, RecoveryDecision, RecoveryPolicy


def decide_recovery_action(
    context: RecoveryContext,
    policy: RecoveryPolicy | None = None,
) -> RecoveryDecision:
    """Decide what to do after a failure.

    Decision logic (evaluated in order):
    1. Permission / auth errors → halt (user intervention required)
    2. User rejection → halt (respect user choice)
    3. Required-task violation with halt_on_required_violation → halt
    4. Retryable error within budget → retry
    5. Retryable error over budget → halt
    6. Non-retryable error → fallback (try alternative approach)

    Returns:
        RecoveryDecision with action, reason, and next_hint.
    """
    policy = policy or RecoveryPolicy()
    error_type = context.error_type

    # 1. Permission / auth errors — never retry
    if error_type in ("permission_denied", "user_rejected", "blocked"):
        return RecoveryDecision(
            action="halt",
            reason=f"Non-retryable error: {error_type}. "
                   f"Requires user intervention or different approach.",
            next_hint="Try a different tool or switch to a more permissive mode.",
        )

    # 2. Required-task violation with strict policy
    if context.is_required and policy.halt_on_required_violation:
        return RecoveryDecision(
            action="halt",
            reason=f"Required task '{context.task_id}' failed. "
                   f"Policy mandates halt on required violations.",
            next_hint="Fix the issue manually or relax the required constraint.",
        )

    # 3. Retryable error within budget
    if policy.is_retryable(error_type) and context.retry_count < policy.max_retries:
        remaining = policy.max_retries - context.retry_count
        return RecoveryDecision(
            action="retry",
            reason=f"Retryable error '{error_type}'. "
                   f"Attempt {context.retry_count + 1}/{policy.max_retries}, "
                   f"{remaining} remaining.",
            next_hint=policy.cooldown_hint,
        )

    # 4. Retryable error over budget — escalate to halt
    if policy.is_retryable(error_type):
        return RecoveryDecision(
            action="halt",
            reason=f"Retry budget exhausted for '{error_type}'. "
                   f"{context.retry_count} attempts made (max {policy.max_retries}).",
            next_hint="Review the failing action and consider a different approach.",
        )

    # 5. Non-retryable error — try fallback
    return RecoveryDecision(
        action="fallback",
        reason=f"Non-retryable error: {error_type}. Attempting fallback.",
        next_hint="The current approach failed. Try an alternative strategy.",
    )
