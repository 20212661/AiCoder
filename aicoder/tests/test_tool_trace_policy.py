"""Tests for Tool Trace Retention Policy."""
import pytest

from aicoder.agent_step_store import AgentStepStore
from aicoder.context.tool_trace_policy import (
    RetentionTier,
    ToolTraceDecision,
    ToolTraceRetentionReport,
    decide_tool_trace_retention,
    apply_retention_to_events,
)
from aicoder.context.condense import prune_history_events
from aicoder.events.types import AgentEventRecord
from aicoder.events.store import AgentEventStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_id: str = "ev-0",
    iteration: int = 0,
    kind: str = "tool_result",
    payload: dict | None = None,
) -> AgentEventRecord:
    return AgentEventRecord(
        event_id=event_id,
        session_id="s1",
        iteration=iteration,
        kind=kind,
        payload=payload or {},
    )


def _make_multi_iteration_events(num_iterations: int = 5) -> list[AgentEventRecord]:
    """Build events across multiple iterations with varied tool traces."""
    events: list[AgentEventRecord] = []
    for i in range(num_iterations):
        events.append(_make_event(f"ev-thought-{i}", iteration=i, kind="assistant_thought",
                                  payload={"thought": f"Step {i}"}))
        events.append(_make_event(f"ev-call-{i}", iteration=i, kind="tool_call",
                                  payload={"tool_name": "read_file", "tool_input": {"path": f"f{i}.py"}}))

        if i == num_iterations - 1:
            # Error in last iteration
            events.append(_make_event(f"ev-result-{i}", iteration=i, kind="tool_error",
                                      payload={"error": "file not found", "tool_name": "read_file"}))
        elif i == 0:
            # Long output in first iteration
            events.append(_make_event(f"ev-result-{i}", iteration=i, kind="tool_result",
                                      payload={"observation": "x" * 1000, "tool_name": "read_file"}))
        else:
            events.append(_make_event(f"ev-result-{i}", iteration=i, kind="tool_result",
                                      payload={"observation": f"contents of f{i}", "tool_name": "read_file"}))
    return events


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------


class TestClassifyEvents:
    def test_errors_are_must_keep(self):
        events = [
            _make_event("ev-1", kind="tool_error", payload={
                "error": "permission denied", "tool_name": "write_file",
            }),
        ]
        report = decide_tool_trace_retention(events, "act")
        assert report.total_traces == 1
        assert report.must_keep == 1
        assert report.decisions[0].tier == RetentionTier.MUST_KEEP
        assert "error" in report.decisions[0].reason

    def test_recent_traces_are_must_keep(self):
        events = [
            _make_event("ev-1", iteration=4, kind="tool_result",
                        payload={"observation": "ok", "tool_name": "read_file"}),
            _make_event("ev-2", iteration=3, kind="tool_result",
                        payload={"observation": "ok", "tool_name": "read_file"}),
        ]
        report = decide_tool_trace_retention(events, "act", recent_iterations=2)
        # Both iteration 3 and 4 are within recent range
        assert report.must_keep == 2

    def test_old_traces_summarize_or_trim(self):
        events = [
            _make_event("ev-1", iteration=0, kind="tool_result",
                        payload={"observation": "short output", "tool_name": "read_file"}),
        ]
        # With high recent threshold, iteration 0 is not recent
        report = decide_tool_trace_retention(events, "act", recent_iterations=0)
        # Old, short, non-critical → trim_aggressively
        assert report.trim_aggressively == 1

    def test_critical_tools_always_must_keep(self):
        events = [
            _make_event("ev-1", iteration=0, kind="tool_result",
                        payload={"observation": "wrote file", "tool_name": "edit_file"}),
        ]
        report = decide_tool_trace_retention(events, "act", recent_iterations=0)
        assert report.must_keep == 1
        assert "critical" in report.decisions[0].reason

    def test_long_output_summarize_only(self):
        events = [
            _make_event("ev-1", iteration=0, kind="tool_result",
                        payload={"observation": "x" * 800, "tool_name": "read_file"}),
        ]
        report = decide_tool_trace_retention(events, "act", recent_iterations=0)
        assert report.summarize_only == 1

    def test_summary_field_triggers_summarize(self):
        events = [
            _make_event("ev-1", iteration=0, kind="tool_result",
                        payload={"observation": "short", "summary": "Found 3 issues",
                                 "tool_name": "search_files"}),
        ]
        report = decide_tool_trace_retention(events, "act", recent_iterations=0)
        assert report.summarize_only == 1
        assert "summary" in report.decisions[0].reason

    def test_bulky_tools_get_summarize(self):
        events = [
            _make_event("ev-1", iteration=0, kind="tool_result",
                        payload={"observation": "f1.py\nf2.py\nf3.py", "tool_name": "list_files"}),
        ]
        report = decide_tool_trace_retention(events, "act", recent_iterations=0)
        assert report.summarize_only == 1

    def test_permission_denied_is_must_keep(self):
        events = [
            _make_event("ev-1", iteration=0, kind="tool_result",
                        payload={"error": "Permission denied", "tool_name": "write_file"}),
        ]
        report = decide_tool_trace_retention(events, "act", recent_iterations=0)
        assert report.must_keep == 1

    def test_non_tool_events_ignored(self):
        events = [
            _make_event("ev-1", kind="assistant_thought", payload={"thought": "hello"}),
            _make_event("ev-2", kind="step_started", payload={"mode": "act"}),
        ]
        report = decide_tool_trace_retention(events, "act")
        assert report.total_traces == 0


class TestReportProperties:
    def test_retention_ratio(self):
        events = [
            _make_event("ev-1", iteration=4, kind="tool_result",
                        payload={"observation": "ok", "tool_name": "read_file"}),
            _make_event("ev-2", iteration=0, kind="tool_result",
                        payload={"observation": "old", "tool_name": "read_file"}),
        ]
        report = decide_tool_trace_retention(events, "act", recent_iterations=2)
        assert "retention_ratio" in dir(report)
        assert "/" in report.retention_ratio

    def test_empty_report(self):
        report = ToolTraceRetentionReport()
        assert report.retention_ratio == "n/a"


class TestMixedScenario:
    def test_multi_iteration_classification(self):
        events = _make_multi_iteration_events(5)
        report = decide_tool_trace_retention(events, "act")

        assert report.total_traces == 5
        assert report.must_keep >= 1  # at least the error
        assert report.must_keep + report.summarize_only + report.trim_aggressively == 5

    def test_recent_critical_gets_highest_priority(self):
        """A recent error should be must_keep (error takes precedence)."""
        events = [
            _make_event("ev-1", iteration=4, kind="tool_error",
                        payload={"error": "crashed", "tool_name": "read_file"}),
        ]
        report = decide_tool_trace_retention(events, "act", recent_iterations=2)
        assert report.must_keep == 1
        assert report.decisions[0].reason == "error event"


# ---------------------------------------------------------------------------
# Apply retention tests
# ---------------------------------------------------------------------------


class TestApplyRetention:
    def test_must_keep_events_unchanged(self):
        events = [
            _make_event("ev-1", kind="tool_result",
                        payload={"observation": "full output text here", "tool_name": "read_file"}),
        ]
        report = ToolTraceRetentionReport(
            total_traces=1, must_keep=1,
            decisions=[ToolTraceDecision("ev-1", RetentionTier.MUST_KEEP, "recent")],
        )
        result = apply_retention_to_events(events, report)
        assert result[0].payload["observation"] == "full output text here"

    def test_summarize_only_trims_observation(self):
        events = [
            _make_event("ev-1", kind="tool_result",
                        payload={"observation": "x" * 500, "tool_name": "read_file"}),
        ]
        report = ToolTraceRetentionReport(
            total_traces=1, summarize_only=1,
            decisions=[ToolTraceDecision("ev-1", RetentionTier.SUMMARIZE_ONLY, "long",
                                         max_output_chars=200)],
        )
        result = apply_retention_to_events(events, report)
        obs = result[0].payload["observation"]
        assert len(obs) <= 203  # 200 + "..."
        assert result[0].payload.get("observation_truncated") is True
        assert result[0].payload["retention_tier"] == "summarize_only"

    def test_trim_aggressively_shortens_more(self):
        events = [
            _make_event("ev-1", kind="tool_result",
                        payload={"observation": "some output " * 20, "tool_name": "read_file"}),
        ]
        report = ToolTraceRetentionReport(
            total_traces=1, trim_aggressively=1,
            decisions=[ToolTraceDecision("ev-1", RetentionTier.TRIM_AGGRESSIVELY,
                                         "old", max_output_chars=50)],
        )
        result = apply_retention_to_events(events, report)
        obs = result[0].payload["observation"]
        assert len(obs) <= 53  # 50 + "..."
        assert result[0].payload["retention_tier"] == "trim_aggressively"

    def test_non_tool_events_pass_through(self):
        events = [
            _make_event("ev-1", kind="assistant_thought", payload={"thought": "hello"}),
        ]
        report = ToolTraceRetentionReport()
        result = apply_retention_to_events(events, report)
        assert len(result) == 1
        assert result[0].payload["thought"] == "hello"

    def test_no_decision_keeps_event(self):
        events = [
            _make_event("ev-1", kind="tool_result",
                        payload={"observation": "output", "tool_name": "read_file"}),
        ]
        report = ToolTraceRetentionReport()  # no decisions
        result = apply_retention_to_events(events, report)
        assert len(result) == 1
        assert result[0].payload["observation"] == "output"


# ---------------------------------------------------------------------------
# Integration with condense.py prune
# ---------------------------------------------------------------------------


class TestPruneWithRetentionPolicy:
    def test_prune_with_retention_flag(self):
        events = [
            _make_event("ev-1", iteration=0, kind="tool_result",
                        payload={"observation": "x" * 1000, "tool_name": "read_file",
                                 "tool_meta": {"success": True}}),
            _make_event("ev-2", iteration=3, kind="tool_result",
                        payload={"observation": "recent output", "tool_name": "read_file",
                                 "tool_meta": {"success": True}}),
        ]
        result = prune_history_events(events, "act", use_retention_policy=True)
        assert len(result) == 2
        # Old event should be trimmed (iteration 0, far from max_iter 3)
        # Recent event should be kept as-is
        assert result[1].payload["observation"] == "recent output"

    def test_prune_without_retention_unchanged(self):
        """Without use_retention_policy, old behavior preserved."""
        events = [
            _make_event("ev-1", kind="tool_result",
                        payload={"observation": "x" * 600, "tool_name": "read_file"}),
        ]
        result = prune_history_events(events, "act")
        assert result[0].payload.get("observation_truncated") is True
