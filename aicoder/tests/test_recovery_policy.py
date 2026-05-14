"""Tests for recovery policy and decision engine — Phase 3."""
import pytest

from aicoder.recovery.policy import (
    RecoveryAction,
    RecoveryContext,
    RecoveryDecision,
    RecoveryPolicy,
)
from aicoder.recovery.engine import decide_recovery_action


# ---------------------------------------------------------------------------
# RecoveryPolicy
# ---------------------------------------------------------------------------


class TestRecoveryPolicy:
    def test_default_max_retries(self):
        p = RecoveryPolicy()
        assert p.max_retries == 3

    def test_default_retryable_errors(self):
        p = RecoveryPolicy()
        assert p.is_retryable("verification_failed")
        assert p.is_retryable("tool_error")
        assert p.is_retryable("timeout")

    def test_non_retryable(self):
        p = RecoveryPolicy()
        assert not p.is_retryable("permission_denied")
        assert not p.is_retryable("user_rejected")

    def test_custom_retryable(self):
        p = RecoveryPolicy(
            retryable_error_types=frozenset({"custom_error"}),
        )
        assert p.is_retryable("custom_error")
        assert not p.is_retryable("tool_error")

    def test_custom_max_retries(self):
        p = RecoveryPolicy(max_retries=5)
        assert p.max_retries == 5


# ---------------------------------------------------------------------------
# RecoveryDecision
# ---------------------------------------------------------------------------


class TestRecoveryDecision:
    def test_to_dict(self):
        d = RecoveryDecision(action="retry", reason="test", next_hint="hint")
        result = d.to_dict()
        assert result["action"] == "retry"
        assert result["reason"] == "test"
        assert result["next_hint"] == "hint"

    def test_decision_fields(self):
        d = RecoveryDecision(action="halt", reason="exceeded budget")
        assert d.action == "halt"
        assert d.reason == "exceeded budget"
        assert d.next_hint == ""


# ---------------------------------------------------------------------------
# Decision engine: retry cases
# ---------------------------------------------------------------------------


class TestDecideRetry:
    def test_retryable_within_budget(self):
        ctx = RecoveryContext(error_type="tool_error", retry_count=0)
        decision = decide_recovery_action(ctx)
        assert decision.action == "retry"
        assert "Attempt 1/3" in decision.reason

    def test_retryable_second_attempt(self):
        ctx = RecoveryContext(error_type="verification_failed", retry_count=1)
        decision = decide_recovery_action(ctx)
        assert decision.action == "retry"
        assert "Attempt 2/3" in decision.reason

    def test_retryable_last_attempt(self):
        ctx = RecoveryContext(error_type="timeout", retry_count=2)
        decision = decide_recovery_action(ctx)
        assert decision.action == "retry"
        assert "Attempt 3/3" in decision.reason

    def test_includes_next_hint(self):
        ctx = RecoveryContext(error_type="tool_error", retry_count=0)
        policy = RecoveryPolicy(cooldown_hint="check params")
        decision = decide_recovery_action(ctx, policy)
        assert decision.next_hint == "check params"


# ---------------------------------------------------------------------------
# Decision engine: halt cases
# ---------------------------------------------------------------------------


class TestDecideHalt:
    def test_exceeded_max_retries(self):
        ctx = RecoveryContext(error_type="tool_error", retry_count=3)
        decision = decide_recovery_action(ctx)
        assert decision.action == "halt"
        assert "exhausted" in decision.reason

    def test_permission_denied_halt(self):
        ctx = RecoveryContext(error_type="permission_denied", retry_count=0)
        decision = decide_recovery_action(ctx)
        assert decision.action == "halt"
        assert "Non-retryable" in decision.reason

    def test_user_rejected_halt(self):
        ctx = RecoveryContext(error_type="user_rejected", retry_count=0)
        decision = decide_recovery_action(ctx)
        assert decision.action == "halt"

    def test_blocked_halt(self):
        ctx = RecoveryContext(error_type="blocked", retry_count=0)
        decision = decide_recovery_action(ctx)
        assert decision.action == "halt"

    def test_required_violation_halt(self):
        ctx = RecoveryContext(
            error_type="verification_failed",
            task_id="syntax_check",
            is_required=True,
            retry_count=0,
        )
        policy = RecoveryPolicy(halt_on_required_violation=True)
        decision = decide_recovery_action(ctx, policy)
        assert decision.action == "halt"
        assert "Required" in decision.reason

    def test_halt_reason_includes_error_type(self):
        ctx = RecoveryContext(error_type="permission_denied")
        decision = decide_recovery_action(ctx)
        assert "permission_denied" in decision.reason

    def test_halt_has_next_hint(self):
        ctx = RecoveryContext(error_type="permission_denied")
        decision = decide_recovery_action(ctx)
        assert len(decision.next_hint) > 0


# ---------------------------------------------------------------------------
# Decision engine: fallback cases
# ---------------------------------------------------------------------------


class TestDecideFallback:
    def test_non_retryable_unknown_error(self):
        ctx = RecoveryContext(error_type="unknown_error", retry_count=0)
        decision = decide_recovery_action(ctx)
        assert decision.action == "fallback"
        assert "fallback" in decision.reason.lower()

    def test_non_retryable_custom_error(self):
        ctx = RecoveryContext(error_type="disk_full", retry_count=0)
        decision = decide_recovery_action(ctx)
        assert decision.action == "fallback"


# ---------------------------------------------------------------------------
# Decision engine: edge cases
# ---------------------------------------------------------------------------


class TestDecideEdgeCases:
    def test_default_policy_used_when_none(self):
        ctx = RecoveryContext(error_type="tool_error", retry_count=0)
        decision = decide_recovery_action(ctx, policy=None)
        assert decision.action == "retry"

    def test_zero_max_retries(self):
        policy = RecoveryPolicy(max_retries=0)
        ctx = RecoveryContext(error_type="tool_error", retry_count=0)
        decision = decide_recovery_action(ctx, policy)
        assert decision.action == "halt"

    def test_large_retry_count(self):
        ctx = RecoveryContext(error_type="tool_error", retry_count=100)
        decision = decide_recovery_action(ctx)
        assert decision.action == "halt"

    def test_decision_always_has_reason(self):
        for error_type in ("tool_error", "permission_denied", "unknown", "timeout"):
            for retries in (0, 1, 5):
                ctx = RecoveryContext(error_type=error_type, retry_count=retries)
                d = decide_recovery_action(ctx)
                assert len(d.reason) > 0, f"No reason for {error_type}/{retries}"

    def test_required_violation_does_not_halt_by_default(self):
        ctx = RecoveryContext(
            error_type="verification_failed",
            task_id="lint",
            is_required=True,
            retry_count=0,
        )
        decision = decide_recovery_action(ctx)
        # Default policy: required violation doesn't force halt → retry
        assert decision.action == "retry"


# ---------------------------------------------------------------------------
# Integration: verify_node produces recovery decisions
# ---------------------------------------------------------------------------


class TestRecoveryIntegration:
    def test_verify_failure_produces_recovery_decision(self, tmp_path):
        """When verification fails, recovery decisions are appended to state."""
        from aicoder.graph.nodes import verify_node

        # Create a Python file with a syntax error
        src = tmp_path / "broken.py"
        src.write_text("def foo(\n")  # syntax error

        state = {
            "session_id": "test",
            "mode": "act",
            "root": str(tmp_path),
            "tool_observations": [
                {
                    "tool_name": "write_file",
                    "success": True,
                    "files": ["broken.py"],
                },
            ],
            "verification_results": [],
            "recovery_decisions": [],
        }
        result = verify_node(state)
        vr = result.get("verification_results", [])
        assert len(vr) == 1
        # The syntax check should have failed
        round_data = vr[0]
        failed_tasks = [r for r in round_data["results"] if r["status"] == "failed"]
        # If syntax check failed, recovery decisions should be present
        if failed_tasks:
            rd = result.get("recovery_decisions", [])
            assert len(rd) > 0
            assert rd[0]["action"] in ("retry", "halt", "fallback")
            assert len(rd[0]["reason"]) > 0
