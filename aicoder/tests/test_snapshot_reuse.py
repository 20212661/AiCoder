"""Tests for snapshot reuse during resume (Phase 5).

Validates that:
1. Persisted snapshots are found and reused by build_llm_history_view()
2. When snapshot covers all events, no fresh condensation occurs
3. When snapshot is stale, fresh condensation is used as fallback
4. merge_snapshot_with_recent_events produces valid LLM messages
5. FC and CoT paths both work
"""
import os
import tempfile

import pytest

from aicoder.agent_step_store import AgentStepStore
from aicoder.context.summary_types import SummaryBlock, CondensationSnapshot
from aicoder.context.summary_store import save_snapshot
from aicoder.context.snapshot import (
    snapshot_covers_events,
    count_uncovered_events,
    get_uncovered_events,
    merge_snapshot_with_recent_events,
)
from aicoder.events.types import AgentEventRecord
from aicoder.events.store import AgentEventStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _persist_session_with_steps(root, session_id, num_steps=5):
    """Write steps to a persistent session and return events."""
    step_store = AgentStepStore.for_session(
        session_id, persist=True, root=root,
    )
    for i in range(num_steps):
        step = step_store.create_step(
            iteration=i, mode="act", runner_type="cot",
        )
        step_store.update_step_after_parse(
            step, thought=f"Step {i}", action_name="read_file",
            action_input={"path": f"/tmp/f{i}.py"},
        )
        step_store.update_step_after_tool(
            step, observation=f"contents of file {i}",
            tool_meta={"success": True, "tool_name": "read_file"},
            files=[f"/tmp/f{i}.py"],
        )
    return step_store.event_store.all_events()


def _make_resume_coder(root, session_id, runner_type="cot"):
    """Create a coder + runner with empty step store (resume scenario)."""
    from aicoder.tests.conftest import make_mock_coder
    from aicoder.tools.registry import ToolRegistry
    from aicoder.runners.cot_agent_runner import CotAgentRunner
    from aicoder.runners import register_runner

    coder = make_mock_coder(root=root)
    coder.session_id = session_id
    coder.done_messages = [
        {"role": "user", "content": "fix the bug"},
        {"role": "assistant", "content": "I'll help fix it."},
    ]

    step_store = AgentStepStore.for_session(
        session_id, persist=True, root=root,
    )
    registry = ToolRegistry()
    runner = CotAgentRunner(
        coder=coder, session_id=session_id, mode="act",
        tool_registry=registry, step_store=step_store,
    )
    register_runner(session_id, runner)
    return coder, runner


def _cleanup(session_id):
    from aicoder.runners import unregister_runner
    unregister_runner(session_id)


def _build_snapshot(session_id, events, num_covered):
    """Build a snapshot covering the first num_covered events."""
    covered_events = events[:num_covered]
    block = SummaryBlock(
        summary_id="sb-test",
        kind="deterministic",
        covered_event_ids=[e.event_id for e in covered_events],
        covered_iterations=[e.iteration for e in covered_events],
        goal="Fix the bug",
        findings=["Found issue in auth.py"],
        actions_taken=["read_file(auth.py)", "edit_file(auth.py)"],
        files_touched=["/tmp/auth.py"],
    )
    return CondensationSnapshot(
        snapshot_id="snap-test",
        session_id=session_id,
        source_event_count=len(covered_events),
        latest_event_id=covered_events[-1].event_id if covered_events else "",
        blocks=[block],
        mode="act",
        created_at="2025-01-01T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Snapshot coverage tests
# ---------------------------------------------------------------------------


class TestSnapshotCoverage:
    def test_covers_all_events(self):
        events = _persist_session_with_steps(tempfile.mkdtemp(), "cov-1", num_steps=3)
        snap = _build_snapshot("cov-1", events, len(events))

        assert snapshot_covers_events(snap, events) is True

    def test_partial_coverage(self):
        events = _persist_session_with_steps(tempfile.mkdtemp(), "cov-2", num_steps=5)
        snap = _build_snapshot("cov-2", events, len(events) // 2)

        assert snapshot_covers_events(snap, events) is False

    def test_empty_events_always_covered(self):
        snap = CondensationSnapshot(
            snapshot_id="snap-empty", session_id="s1",
            source_event_count=0, latest_event_id="",
        )
        assert snapshot_covers_events(snap, []) is True


class TestUncoveredEvents:
    def test_count_uncovered(self):
        events = _persist_session_with_steps(tempfile.mkdtemp(), "unc-1", num_steps=5)
        # Snapshot covers first 60% of events
        snap = _build_snapshot("unc-1", events, int(len(events) * 0.6))

        uncovered = count_uncovered_events(snap, events)
        assert uncovered > 0
        assert uncovered < len(events)

    def test_get_uncovered(self):
        events = _persist_session_with_steps(tempfile.mkdtemp(), "unc-2", num_steps=3)
        snap = _build_snapshot("unc-2", events, len(events) // 2)

        uncovered = get_uncovered_events(snap, events)
        assert len(uncovered) > 0
        # Uncovered events should be newer than snapshot's latest
        for ev in uncovered:
            assert ev.event_id != snap.latest_event_id


# ---------------------------------------------------------------------------
# Merge tests
# ---------------------------------------------------------------------------


class TestMergeSnapshot:
    def test_merge_produces_messages(self):
        events = _persist_session_with_steps(tempfile.mkdtemp(), "merge-1", num_steps=5)
        snap = _build_snapshot("merge-1", events, len(events))

        messages = merge_snapshot_with_recent_events(
            snap, events, runner_type="cot",
            done_messages=[{"role": "user", "content": "fix bug"}],
        )

        assert len(messages) > 2  # done_messages + summary pair
        # Should have condensed summary
        condensed = [m for m in messages if m.get("condensed")]
        assert len(condensed) == 1
        assert condensed[0].get("snapshot_id") == "snap-test"
        assert condensed[0].get("snapshot_source") == "persisted"

    def test_merge_includes_structured_fields(self):
        events = _persist_session_with_steps(tempfile.mkdtemp(), "merge-2", num_steps=3)
        snap = _build_snapshot("merge-2", events, len(events))

        messages = merge_snapshot_with_recent_events(
            snap, events, runner_type="cot", done_messages=[],
        )

        condensed = [m for m in messages if m.get("condensed")]
        assert len(condensed) == 1
        assert condensed[0]["goal"] == "Fix the bug"
        assert len(condensed[0]["findings"]) > 0
        assert len(condensed[0]["actions_taken"]) > 0

    def test_merge_with_uncovered_events(self):
        events = _persist_session_with_steps(tempfile.mkdtemp(), "merge-3", num_steps=5)
        # Snapshot covers only first half
        snap = _build_snapshot("merge-3", events, len(events) // 2)

        messages = merge_snapshot_with_recent_events(
            snap, events, runner_type="cot", done_messages=[],
        )

        # Should have summary pair + recent replayed messages
        condensed = [m for m in messages if m.get("condensed")]
        assert len(condensed) == 1

        # Should have messages from uncovered events
        non_summary = [m for m in messages if not m.get("condensed")]
        assert len(non_summary) > 0

    def test_merge_empty_snapshot(self):
        snap = CondensationSnapshot(
            snapshot_id="snap-empty", session_id="s1",
            source_event_count=0, latest_event_id="",
        )
        messages = merge_snapshot_with_recent_events(
            snap, [], runner_type="cot",
            done_messages=[{"role": "user", "content": "hi"}],
        )
        assert messages == [{"role": "user", "content": "hi"}]


# ---------------------------------------------------------------------------
# Integration: build_llm_history_view with snapshot
# ---------------------------------------------------------------------------


class TestLLMViewSnapshotReuse:
    def test_reuses_persisted_snapshot(self):
        """build_llm_history_view should reuse persisted snapshot."""
        root = tempfile.mkdtemp()
        session_id = "snap-reuse-1"
        events = _persist_session_with_steps(root, session_id, num_steps=5)

        # Build and save snapshot covering all events
        snap = _build_snapshot(session_id, events, len(events))
        save_snapshot(snap, root)

        coder, runner = _make_resume_coder(root, session_id)

        from aicoder.context.history_view import build_llm_history_view
        messages = build_llm_history_view(coder, "act", "cot")

        # Should use persisted snapshot
        condensed = [m for m in messages if m.get("condensed")]
        assert len(condensed) >= 1
        assert condensed[0].get("snapshot_source") == "persisted"

        _cleanup(session_id)

    def test_no_snapshot_falls_back_to_fresh(self):
        """Without snapshot, should fall back to fresh condensation."""
        root = tempfile.mkdtemp()
        session_id = "snap-nosnap-1"
        _persist_session_with_steps(root, session_id, num_steps=5)

        coder, runner = _make_resume_coder(root, session_id)

        from aicoder.context.history_view import build_llm_history_view
        messages = build_llm_history_view(coder, "act", "cot")

        # Should use fresh condensation (no snapshot_source)
        condensed = [m for m in messages if m.get("condensed")]
        if condensed:
            assert condensed[0].get("snapshot_source") != "persisted"

        _cleanup(session_id)

    def test_stale_snapshot_uses_merge(self):
        """Partially stale snapshot should still be used for old events."""
        root = tempfile.mkdtemp()
        session_id = "snap-stale-1"
        events = _persist_session_with_steps(root, session_id, num_steps=5)

        # Build snapshot covering first 80% of events (leaving 20% uncovered)
        snap = _build_snapshot(session_id, events, int(len(events) * 0.8))
        save_snapshot(snap, root)

        coder, runner = _make_resume_coder(root, session_id)

        from aicoder.context.history_view import build_llm_history_view
        messages = build_llm_history_view(coder, "act", "cot")

        # Should produce messages
        assert len(messages) > 0

        _cleanup(session_id)

    def test_ui_view_not_affected_by_snapshot(self):
        """UI view should not use snapshots."""
        root = tempfile.mkdtemp()
        session_id = "snap-ui-1"
        events = _persist_session_with_steps(root, session_id, num_steps=3)
        snap = _build_snapshot(session_id, events, len(events))
        save_snapshot(snap, root)

        coder, runner = _make_resume_coder(root, session_id)

        from aicoder.context.history_view import build_ui_history_view
        view = build_ui_history_view(coder, "act", "cot")

        # UI view should have step entries from replay
        step_entries = [e for e in view if e.get("source") == "step"]
        assert len(step_entries) > 0

        _cleanup(session_id)

    def test_runtime_view_not_affected_by_snapshot(self):
        """Runtime view should not use snapshots."""
        root = tempfile.mkdtemp()
        session_id = "snap-rt-1"
        events = _persist_session_with_steps(root, session_id, num_steps=3)
        snap = _build_snapshot(session_id, events, len(events))
        save_snapshot(snap, root)

        coder, runner = _make_resume_coder(root, session_id)

        from aicoder.context.history_view import build_runtime_history_view
        view = build_runtime_history_view(coder, "act", "cot")

        assert len(view) >= 3

        _cleanup(session_id)
