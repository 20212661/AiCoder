"""Tests for v1.5 condensation pipeline upgrade.

Validates that the condensation pipeline now produces structured SummaryBlock
objects while maintaining backward compatibility with CondensedBlock consumers.
"""
import pytest

from aicoder.agent_step_store import AgentStepStore
from aicoder.context.condense import (
    CondensedBlock,
    summarize_history_events,
    apply_condensation_to_history_view,
    build_condensation_snapshot,
    prune_history_events,
)
from aicoder.context.summarizer import (
    summarize_events_deterministic,
    summarize_events_with_llm,
    build_summary_block,
)
from aicoder.context.summary_types import SummaryBlock, CondensationSnapshot
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


def _make_many_events(count: int) -> list[AgentEventRecord]:
    """Build a realistic sequence of events across multiple iterations."""
    store = AgentEventStore(session_id="s1")
    step_store = AgentStepStore(session_id="s1")

    for i in range(count):
        step = step_store.create_step(iteration=i, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step,
            thought=f"Thinking about step {i}",
            action_name="read_file",
            action_input={"path": f"/tmp/file{i}.py"},
        )
        step_store.update_step_after_tool(
            step,
            observation=f"contents of file {i}",
            tool_meta={"success": True, "tool_name": "read_file"},
            files=[f"/tmp/file{i}.py"],
        )

    return step_store.event_store.all_events()


# ---------------------------------------------------------------------------
# Summarizer tests
# ---------------------------------------------------------------------------


class TestDeterministicSummarizer:
    def test_produces_summary_block(self):
        events = _make_many_events(5)
        block = summarize_events_deterministic(events, "act")

        assert block is not None
        assert isinstance(block, SummaryBlock)
        assert block.summary_id.startswith("sb-")
        assert block.kind == "deterministic"
        assert len(block.covered_event_ids) > 0
        assert len(block.covered_iterations) > 0

    def test_structured_fields_populated(self):
        events = [
            _make_event("ev-1", kind="assistant_thought", payload={"thought": "Fix auth"}),
            _make_event("ev-2", kind="tool_call", payload={"tool_name": "read_file", "tool_input": {"path": "auth.py"}}),
            _make_event("ev-3", kind="tool_result", payload={
                "observation": "Found bug",
                "tool_meta": {"success": True, "tool_name": "read_file"},
                "files": ["/tmp/auth.py"],
            }),
        ]
        block = summarize_events_deterministic(events, "act")

        assert block is not None
        assert block.goal == "Fix auth"
        assert len(block.actions_taken) > 0
        assert "read_file" in block.actions_taken[0]
        assert len(block.findings) > 0
        assert "/tmp/auth.py" in block.files_touched

    def test_failures_extracted(self):
        events = [
            _make_event("ev-1", kind="tool_call", payload={"tool_name": "write_file"}),
            _make_event("ev-2", kind="tool_error", payload={
                "error": "permission denied",
                "tool_meta": {
                    "success": False,
                    "tool_name": "write_file",
                    "error_type": "permission_denied",
                },
            }),
        ]
        block = summarize_events_deterministic(events, "act")

        assert block is not None
        assert len(block.failures) > 0
        assert "write_file" in block.failures[0]

    def test_next_steps_from_recommended(self):
        events = [
            _make_event("ev-1", kind="tool_error", payload={
                "error": "not found",
                "tool_meta": {
                    "success": False,
                    "tool_name": "read_file",
                    "summary": "File not found",
                    "recommended_next": "Check path and retry",
                },
            }),
        ]
        block = summarize_events_deterministic(events, "act")

        assert block is not None
        assert "Check path and retry" in block.next_steps

    def test_empty_events_returns_none(self):
        assert summarize_events_deterministic([], "act") is None

    def test_no_meaningful_events_returns_none(self):
        events = [
            _make_event("ev-1", kind="step_started", payload={"mode": "act"}),
        ]
        assert summarize_events_deterministic(events, "act") is None

    def test_summary_property_returns_text(self):
        events = _make_many_events(5)
        block = summarize_events_deterministic(events, "act")

        assert block is not None
        text = block.summary  # property for backward compat
        assert isinstance(text, str)
        assert len(text) > 0


class TestBuildSummaryBlock:
    def test_without_coder(self):
        events = _make_many_events(3)
        block = build_summary_block(events, "act", coder=None)

        assert block is not None
        assert isinstance(block, SummaryBlock)

    def test_with_coder(self):
        events = _make_many_events(3)
        block = build_summary_block(events, "act", coder=object())

        assert block is not None
        assert isinstance(block, SummaryBlock)


# ---------------------------------------------------------------------------
# condense.py integration tests
# ---------------------------------------------------------------------------


class TestSummarizeHistoryEventsUpgrade:
    def test_returns_summary_block(self):
        events = _make_many_events(5)
        block = summarize_history_events(events)

        assert block is not None
        # v1.5: should be SummaryBlock
        assert isinstance(block, SummaryBlock)

    def test_backward_compat_summary_access(self):
        events = _make_many_events(5)
        block = summarize_history_events(events)

        assert block is not None
        # .summary should work (property on SummaryBlock)
        assert hasattr(block, "summary")
        assert len(block.summary) > 0

    def test_backward_compat_covered_event_ids(self):
        events = [
            _make_event("ev-1", kind="tool_call", payload={"tool_name": "read_file"}),
            _make_event("ev-2", kind="tool_result", payload={"observation": "ok"}),
        ]
        block = summarize_history_events(events)

        assert block is not None
        assert block.covered_event_ids == ["ev-1", "ev-2"]

    def test_backward_compat_kind(self):
        events = _make_many_events(3)
        block = summarize_history_events(events)

        assert block is not None
        assert block.kind == "deterministic"

    def test_empty_events_returns_none(self):
        assert summarize_history_events([]) is None


class TestBuildCondensationSnapshot:
    def test_builds_snapshot(self):
        events = _make_many_events(5)
        snap = build_condensation_snapshot(events, "act", session_id="s1")

        assert snap is not None
        assert isinstance(snap, CondensationSnapshot)
        assert snap.session_id == "s1"
        assert snap.source_event_count == len(events)
        assert len(snap.blocks) >= 1
        assert snap.mode == "act"

    def test_snapshot_has_valid_id(self):
        events = _make_many_events(3)
        snap = build_condensation_snapshot(events, "act", session_id="s2")

        assert snap is not None
        assert snap.snapshot_id.startswith("snap-")
        assert snap.latest_event_id != ""

    def test_snapshot_empty_events_returns_none(self):
        assert build_condensation_snapshot([], "act", session_id="s1") is None


class TestApplyCondensationWithSummaryBlock:
    def test_applies_summary_block(self):
        events = _make_many_events(5)
        block = summarize_history_events(events)
        assert block is not None

        view = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        result = apply_condensation_to_history_view(view, block)

        assert len(result) < len(view)
        assert result[0]["content"] == "[Previous conversation condensed]"
        assert result[1].get("condensed") is True
        # v1.5: structured metadata included
        assert "summary_block_id" in result[1]
        assert "goal" in result[1]

    def test_applies_legacy_condensed_block(self):
        """Legacy CondensedBlock should still work."""
        view = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        condensed = CondensedBlock(
            summary="Old style summary",
            covered_event_ids=["ev-1"],
        )
        result = apply_condensation_to_history_view(view, condensed)

        assert len(result) < len(view)
        assert result[1]["content"] == "Old style summary"
        assert result[1].get("condensed") is True
        # No structured metadata for legacy blocks
        assert "summary_block_id" not in result[1]


# ---------------------------------------------------------------------------
# Prune backward compat (unchanged)
# ---------------------------------------------------------------------------


class TestPruneBackwardCompat:
    def test_prune_still_works(self):
        events = [
            _make_event("ev-1", kind="tool_result", payload={
                "observation": "x" * 500,
                "tool_name": "read_file",
            }),
        ]
        pruned = prune_history_events(events, "act")
        assert len(pruned) == 1
        assert pruned[0].payload.get("observation_truncated") is True
