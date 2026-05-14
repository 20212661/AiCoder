"""Tests for quality metrics and debug observability — Phase 6."""
import pytest

from aicoder.debug.dump_helpers import (
    dump_quality_summary,
    dump_recovery_metrics,
    dump_verification_metrics,
)
from aicoder.events.store import AgentEventStore
from aicoder.events.types import AgentEventRecord


def _make_event(event_id, iteration, kind, payload, session_id="test"):
    return AgentEventRecord(
        event_id=event_id,
        session_id=session_id,
        iteration=iteration,
        kind=kind,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Verification metrics
# ---------------------------------------------------------------------------


class TestDumpVerificationMetrics:
    def test_empty_coder(self):
        """No events returns zero metrics."""
        from unittest.mock import MagicMock
        coder = MagicMock()
        coder.session_id = "test"
        # No runner → no events
        result = dump_verification_metrics(coder)
        assert result["task_count"] == 0
        assert result["pass_rate"] == 0.0
        assert result["rounds"] == 0

    def test_all_passed(self):
        """All passed tasks produce 1.0 pass rate."""
        from unittest.mock import MagicMock, patch
        from aicoder.context.history_view import _get_event_records

        events = [
            _make_event("v1", 0, "verification_result", {"task_id": "syntax", "status": "passed", "duration_ms": 100}),
            _make_event("v2", 0, "verification_result", {"task_id": "lint", "status": "passed", "duration_ms": 200}),
            _make_event("v3", 0, "verification_finished", {"all_passed": True, "pass_count": 2, "fail_count": 0}),
        ]
        coder = MagicMock()
        coder.session_id = "test"
        with patch("aicoder.context.history_view._get_event_records", return_value=events):
            # Also need to patch in dump_verification_metrics's import
            result = dump_verification_metrics(coder)
        assert result["task_count"] == 2
        assert result["pass_count"] == 2
        assert result["pass_rate"] == 1.0
        assert result["mean_duration_ms"] == 150.0
        assert result["rounds"] == 1

    def test_mixed_results(self):
        """Mixed pass/fail results."""
        from unittest.mock import MagicMock, patch

        events = [
            _make_event("v1", 0, "verification_result", {"task_id": "syntax", "status": "passed", "duration_ms": 50}),
            _make_event("v2", 0, "verification_result", {"task_id": "lint", "status": "failed", "duration_ms": 300}),
            _make_event("v3", 0, "verification_result", {"task_id": "type_check", "status": "error", "duration_ms": 0}),
            _make_event("v4", 0, "verification_finished", {"all_passed": False, "pass_count": 1, "fail_count": 1}),
        ]
        coder = MagicMock()
        with patch("aicoder.context.history_view._get_event_records", return_value=events):
            result = dump_verification_metrics(coder)
        assert result["task_count"] == 3
        assert result["pass_count"] == 1
        assert result["fail_count"] == 1
        assert result["error_count"] == 1
        assert result["pass_rate"] == pytest.approx(0.333, abs=0.01)
        assert result["fail_rate"] == pytest.approx(0.333, abs=0.01)

    def test_by_task_breakdown(self):
        """Per-task metrics are correct."""
        from unittest.mock import MagicMock, patch

        events = [
            _make_event("v1", 0, "verification_result", {"task_id": "syntax", "status": "passed"}),
            _make_event("v2", 0, "verification_result", {"task_id": "syntax", "status": "failed"}),
            _make_event("v3", 0, "verification_result", {"task_id": "lint", "status": "passed"}),
        ]
        coder = MagicMock()
        with patch("aicoder.context.history_view._get_event_records", return_value=events):
            result = dump_verification_metrics(coder)
        assert result["by_task"]["syntax"]["total"] == 2
        assert result["by_task"]["syntax"]["passed"] == 1
        assert result["by_task"]["syntax"]["failed"] == 1
        assert result["by_task"]["lint"]["total"] == 1


# ---------------------------------------------------------------------------
# Recovery metrics
# ---------------------------------------------------------------------------


class TestDumpRecoveryMetrics:
    def test_empty_coder(self):
        from unittest.mock import MagicMock
        coder = MagicMock()
        result = dump_recovery_metrics(coder)
        assert result["total_decisions"] == 0
        assert result["retry_rate"] == 0.0

    def test_retry_and_halt(self):
        from unittest.mock import MagicMock, patch

        events = [
            _make_event("r1", 0, "recovery_decision", {"action": "retry", "reason": "retryable"}),
            _make_event("r2", 0, "recovery_decision", {"action": "retry", "reason": "retryable"}),
            _make_event("r3", 0, "recovery_decision", {"action": "halt", "reason": "exhausted"}),
        ]
        coder = MagicMock()
        with patch("aicoder.context.history_view._get_event_records", return_value=events):
            result = dump_recovery_metrics(coder)
        assert result["total_decisions"] == 3
        assert result["retry_count"] == 2
        assert result["halt_count"] == 1
        assert result["retry_rate"] == pytest.approx(0.667, abs=0.01)
        assert result["halt_rate"] == pytest.approx(0.333, abs=0.01)

    def test_all_halt(self):
        from unittest.mock import MagicMock, patch

        events = [
            _make_event("r1", 0, "recovery_decision", {"action": "halt", "reason": "denied"}),
            _make_event("r2", 0, "recovery_decision", {"action": "halt", "reason": "denied"}),
        ]
        coder = MagicMock()
        with patch("aicoder.context.history_view._get_event_records", return_value=events):
            result = dump_recovery_metrics(coder)
        assert result["halt_rate"] == 1.0
        assert result["retry_rate"] == 0.0


# ---------------------------------------------------------------------------
# Quality summary
# ---------------------------------------------------------------------------


class TestDumpQualitySummary:
    def test_healthy(self):
        from unittest.mock import MagicMock, patch

        events = [
            _make_event("v1", 0, "verification_result", {"task_id": "syntax", "status": "passed", "duration_ms": 100}),
            _make_event("v2", 0, "verification_finished", {"all_passed": True}),
        ]
        coder = MagicMock()
        with patch("aicoder.context.history_view._get_event_records", return_value=events):
            result = dump_quality_summary(coder)
        assert result["health"] == "healthy"
        assert result["verification"]["pass_rate"] == 1.0

    def test_degraded(self):
        from unittest.mock import MagicMock, patch

        # 2 failed out of 3 = fail_rate > 0.5
        events = [
            _make_event("v1", 0, "verification_result", {"task_id": "syntax", "status": "passed"}),
            _make_event("v2", 0, "verification_result", {"task_id": "lint", "status": "failed"}),
            _make_event("v3", 0, "verification_result", {"task_id": "type", "status": "failed"}),
        ]
        coder = MagicMock()
        with patch("aicoder.context.history_view._get_event_records", return_value=events):
            result = dump_quality_summary(coder)
        assert result["health"] == "degraded"

    def test_critical(self):
        from unittest.mock import MagicMock, patch

        # All failed = fail_rate > 0.8
        events = [
            _make_event("v1", 0, "verification_result", {"task_id": "syntax", "status": "failed"}),
            _make_event("v2", 0, "verification_result", {"task_id": "lint", "status": "failed"}),
            _make_event("v3", 0, "verification_result", {"task_id": "type", "status": "failed"}),
        ]
        coder = MagicMock()
        with patch("aicoder.context.history_view._get_event_records", return_value=events):
            result = dump_quality_summary(coder)
        assert result["health"] == "critical"

    def test_no_data_is_healthy(self):
        from unittest.mock import MagicMock
        coder = MagicMock()
        result = dump_quality_summary(coder)
        assert result["health"] == "healthy"
        assert result["verification"]["task_count"] == 0
        assert result["recovery"]["total_decisions"] == 0


# ---------------------------------------------------------------------------
# Output format stability
# ---------------------------------------------------------------------------


class TestMetricsFormatStability:
    def test_verification_keys_stable(self):
        from unittest.mock import MagicMock
        coder = MagicMock()
        result = dump_verification_metrics(coder)
        expected_keys = {
            "task_count", "pass_count", "fail_count", "error_count",
            "pass_rate", "fail_rate", "mean_duration_ms", "rounds",
            "by_task",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_recovery_keys_stable(self):
        from unittest.mock import MagicMock
        coder = MagicMock()
        result = dump_recovery_metrics(coder)
        expected_keys = {
            "total_decisions", "retry_count", "fallback_count",
            "halt_count", "retry_rate", "halt_rate",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_summary_keys_stable(self):
        from unittest.mock import MagicMock
        coder = MagicMock()
        result = dump_quality_summary(coder)
        assert "verification" in result
        assert "recovery" in result
        assert "health" in result
