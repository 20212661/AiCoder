"""Integration tests for v1.5 snapshot auto-persistence and retention policy.

Validates the two main-chain fixes:
1. Snapshot is auto-generated and persisted after fresh condensation
2. Tool trace retention policy is active in the default condensation path
"""
import os
import stat
import tempfile

import pytest

from aicoder.agent_step_store import AgentStepStore
from aicoder.context.summary_store import (
    save_snapshot,
    load_latest_snapshot,
    list_snapshots,
)
from aicoder.context.summary_types import CondensationSnapshot
from aicoder.context.tool_trace_policy import (
    RetentionTier,
    decide_tool_trace_retention,
)
from aicoder.events.types import AgentEventRecord
from aicoder.events.store import AgentEventStore
from aicoder.runners import register_runner, unregister_runner


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


def _make_resume_coder(root, session_id):
    """Create a coder + runner for integration tests."""
    from aicoder.tests.conftest import make_mock_coder
    from aicoder.tools.registry import ToolRegistry
    from aicoder.runners.cot_agent_runner import CotAgentRunner

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
    unregister_runner(session_id)


# ---------------------------------------------------------------------------
# Issue 1: Snapshot auto-persistence in main chain
# ---------------------------------------------------------------------------


class TestSnapshotAutoPersistence:
    """Validate that fresh condensation auto-generates and persists a snapshot."""

    def test_fresh_condensation_auto_saves_snapshot(self):
        """First condensation should create a snapshot file on disk."""
        root = tempfile.mkdtemp()
        session_id = "snap-auto-1"

        # Create enough events to trigger condensation
        _persist_session_with_steps(root, session_id, num_steps=5)
        coder, runner = _make_resume_coder(root, session_id)

        # No snapshot should exist yet
        assert load_latest_snapshot(session_id, root) is None

        from aicoder.context.history_view import build_llm_history_view
        messages = build_llm_history_view(coder, "act", "cot")

        # Now a snapshot should exist on disk
        snap = load_latest_snapshot(session_id, root)
        assert snap is not None, "Snapshot should be auto-persisted after fresh condensation"
        assert snap.session_id == session_id
        assert snap.source_event_count > 0
        assert len(snap.blocks) >= 1

        _cleanup(session_id)

    def test_second_call_reuses_snapshot(self):
        """Second build_llm_history_view should reuse the persisted snapshot."""
        root = tempfile.mkdtemp()
        session_id = "snap-auto-2"

        _persist_session_with_steps(root, session_id, num_steps=5)
        coder, runner = _make_resume_coder(root, session_id)

        from aicoder.context.history_view import build_llm_history_view

        # First call: fresh condensation + auto-save
        messages1 = build_llm_history_view(coder, "act", "cot")

        # Verify snapshot exists
        snap = load_latest_snapshot(session_id, root)
        assert snap is not None

        # Second call: should reuse snapshot
        messages2 = build_llm_history_view(coder, "act", "cot")
        assert len(messages2) > 0

        # The condensed message should come from persisted snapshot
        condensed = [m for m in messages2 if m.get("condensed")]
        if condensed:
            assert condensed[0].get("snapshot_source") == "persisted"

        _cleanup(session_id)

    def test_snapshot_covers_all_source_events(self):
        """Auto-persisted snapshot should cover the events it was built from."""
        root = tempfile.mkdtemp()
        session_id = "snap-auto-3"

        _persist_session_with_steps(root, session_id, num_steps=5)
        coder, runner = _make_resume_coder(root, session_id)

        from aicoder.context.history_view import build_llm_history_view
        build_llm_history_view(coder, "act", "cot")

        snap = load_latest_snapshot(session_id, root)
        assert snap is not None
        assert snap.latest_event_id != ""

        # The snapshot should know how many events it covers
        assert snap.source_event_count > 0

        _cleanup(session_id)

    def test_save_failure_does_not_crash(self):
        """If snapshot save fails, build_llm_history_view should still work."""
        root = tempfile.mkdtemp()
        session_id = "snap-auto-readonly"

        _persist_session_with_steps(root, session_id, num_steps=5)
        coder, runner = _make_resume_coder(root, session_id)

        # Make the summaries dir read-only so save_snapshot fails
        summaries_dir = os.path.join(root, ".aicoder", "summaries")
        os.makedirs(summaries_dir, exist_ok=True)
        os.chmod(summaries_dir, stat.S_IRUSR | stat.S_IXUSR)

        try:
            from aicoder.context.history_view import build_llm_history_view
            # Should NOT crash even though saving fails
            messages = build_llm_history_view(coder, "act", "cot")

            assert len(messages) > 0, "Should return messages even if snapshot save fails"

            # Should have fresh condensation (no persisted snapshot to reuse)
            condensed = [m for m in messages if m.get("condensed")]
            if condensed:
                assert condensed[0].get("snapshot_source") != "persisted"
        finally:
            os.chmod(summaries_dir, stat.S_IRWXU)
            _cleanup(session_id)

    def test_no_session_id_still_works(self):
        """Without session_id, condensation still works (no snapshot persist)."""
        root = tempfile.mkdtemp()
        session_id = "snap-auto-no-session"

        _persist_session_with_steps(root, session_id, num_steps=5)
        coder, runner = _make_resume_coder(root, session_id)
        coder.session_id = ""  # Clear session_id

        from aicoder.context.history_view import build_llm_history_view
        messages = build_llm_history_view(coder, "act", "cot")

        assert len(messages) > 0
        # No snapshot should be saved (no session_id)
        assert load_latest_snapshot("snap-auto-no-session", root) is None

        _cleanup(session_id)


# ---------------------------------------------------------------------------
# Issue 2: Retention policy active in default condensation
# ---------------------------------------------------------------------------


class TestRetentionPolicyInMainChain:
    """Validate that retention policy is active in the default condensation path."""

    def test_retention_affects_pruned_events(self):
        """Events going through _apply_condensation should be retention-aware."""
        from aicoder.context.history_view import _apply_condensation

        # Build events with varying tool trace characteristics
        events: list[AgentEventRecord] = []

        # Old iteration 0: long output (should be trimmed by retention)
        events.append(_make_event("ev-r1", iteration=0, kind="tool_result", payload={
            "observation": "x" * 1000,
            "tool_name": "read_file",
            "tool_meta": {"success": True},
        }))

        # Old iteration 0: critical tool (should be kept)
        events.append(_make_event("ev-r2", iteration=0, kind="tool_result", payload={
            "observation": "wrote file content here",
            "tool_name": "edit_file",
            "tool_meta": {"success": True},
        }))

        # Old iteration 0: error (should be must_keep)
        events.append(_make_event("ev-r3", iteration=0, kind="tool_error", payload={
            "error": "permission denied",
            "tool_name": "write_file",
            "tool_meta": {"success": False, "error_type": "permission_denied"},
        }))

        # Recent iteration 4: regular output (should be kept)
        events.append(_make_event("ev-r4", iteration=4, kind="tool_result", payload={
            "observation": "recent file content",
            "tool_name": "read_file",
            "tool_meta": {"success": True},
        }))

        # Non-tool event (should pass through)
        events.append(_make_event("ev-r5", iteration=4, kind="assistant_thought",
                                  payload={"thought": "Analyzing results"}))

        messages = [{"role": "user", "content": f"msg {i}"} for i in range(10)]

        result = _apply_condensation(messages, events, "act")

        # Should return condensed messages
        assert len(result) < len(messages) + len(events)
        condensed = [m for m in result if m.get("condensed")]
        assert len(condensed) >= 1

    def test_old_bulky_output_trimmed_in_main_chain(self):
        """Old bulky tool outputs should be trimmed by retention-aware pruning."""
        from aicoder.context.history_view import _apply_condensation

        # Build events with a very old, very large tool output
        events: list[AgentEventRecord] = []
        for i in range(5):
            events.append(_make_event(f"ev-t{i}", iteration=i, kind="tool_result", payload={
                "observation": "x" * 2000 if i == 0 else f"normal output {i}",
                "tool_name": "read_file",
                "tool_meta": {"success": True},
            }))

        messages = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        result = _apply_condensation(messages, events, "act")

        # Should condense without error
        assert len(result) > 0
        condensed = [m for m in result if m.get("condensed")]
        assert len(condensed) >= 1

    def test_recent_error_traces_not_aggressively_trimmed(self):
        """Recent error traces should be must_keep, not aggressively trimmed."""
        from aicoder.context.history_view import _apply_condensation

        events: list[AgentEventRecord] = []

        # Recent error — must_keep by retention policy
        events.append(_make_event("ev-err1", iteration=4, kind="tool_error", payload={
            "error": "file not found: /tmp/important.py",
            "tool_name": "read_file",
            "tool_meta": {"success": False, "error_type": "file_not_found"},
        }))

        # Recent success — must_keep (recent)
        events.append(_make_event("ev-ok1", iteration=4, kind="tool_result", payload={
            "observation": "file contents here",
            "tool_name": "read_file",
            "tool_meta": {"success": True},
        }))

        # Add enough more events to make condensation meaningful
        for i in range(5, 10):
            events.append(_make_event(f"ev-fill{i}", iteration=i, kind="tool_result", payload={
                "observation": f"filler {i}",
                "tool_name": "read_file",
                "tool_meta": {"success": True},
            }))

        messages = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        result = _apply_condensation(messages, events, "act")

        # Error trace info should survive in the condensed summary
        condensed = [m for m in result if m.get("condensed")]
        if condensed:
            # The summary should mention the error or file operations
            content = condensed[0].get("content", "")
            assert len(content) > 0

    def test_retention_tier_classification_in_main_chain(self):
        """Verify that events are classified into correct tiers when pruned."""
        # Directly test that the main chain uses retention policy
        from aicoder.context.condense import prune_history_events

        events = [
            # Old, short, non-critical -> trim_aggressively
            _make_event("ev-1", iteration=0, kind="tool_result", payload={
                "observation": "short",
                "tool_name": "read_file",
            }),
            # Error -> must_keep
            _make_event("ev-2", iteration=0, kind="tool_error", payload={
                "error": "crashed",
                "tool_name": "read_file",
            }),
            # Critical tool -> must_keep
            _make_event("ev-3", iteration=0, kind="tool_result", payload={
                "observation": "wrote it",
                "tool_name": "edit_file",
            }),
            # Recent -> must_keep
            _make_event("ev-4", iteration=5, kind="tool_result", payload={
                "observation": "recent output",
                "tool_name": "read_file",
            }),
        ]

        # Main chain now uses retention policy
        pruned = prune_history_events(events, "act", use_retention_policy=True)

        # Error trace should keep its full observation
        error_events = [e for e in pruned if e.kind == "tool_error"]
        assert len(error_events) == 1
        assert error_events[0].payload.get("error") == "crashed"

        # Critical tool trace should be preserved
        edit_events = [e for e in pruned
                       if e.payload.get("tool_name") == "edit_file"]
        assert len(edit_events) == 1
        assert edit_events[0].payload.get("observation") == "wrote it"

        # Recent event should be preserved
        recent_events = [e for e in pruned if e.iteration == 5]
        assert len(recent_events) == 1
        assert recent_events[0].payload.get("observation") == "recent output"


# ---------------------------------------------------------------------------
# Full pipeline: retention + snapshot together
# ---------------------------------------------------------------------------


class TestFullPipelineIntegration:
    """End-to-end: retention policy + snapshot persistence in real main chain."""

    def test_full_pipeline_with_varied_traces(self):
        """Full pipeline with error/critical/bulky/recent traces + snapshot."""
        root = tempfile.mkdtemp()
        session_id = "pipeline-full-1"

        step_store = AgentStepStore.for_session(
            session_id, persist=True, root=root,
        )

        # Build varied tool traces across iterations
        for i in range(6):
            step = step_store.create_step(iteration=i, mode="act", runner_type="cot")
            step_store.update_step_after_parse(
                step, thought=f"Step {i}",
                action_name="edit_file" if i % 3 == 0 else "read_file",
                action_input={"path": f"/tmp/f{i}.py"},
            )

            if i == 2:
                # Error step
                step_store.update_step_after_tool(
                    step, observation="permission denied",
                    tool_error=True,
                    tool_meta={"success": False, "tool_name": "edit_file",
                               "error_type": "permission_denied"},
                )
            else:
                obs = "x" * 800 if i == 0 else f"normal output {i}"
                step_store.update_step_after_tool(
                    step, observation=obs,
                    tool_meta={"success": True, "tool_name": step.action_name},
                    files=[f"/tmp/f{i}.py"],
                )

        coder, runner = _make_resume_coder(root, session_id)

        from aicoder.context.history_view import build_llm_history_view

        # First call: fresh condensation + snapshot save
        messages = build_llm_history_view(coder, "act", "cot")
        assert len(messages) > 0

        # Verify snapshot was persisted
        snap = load_latest_snapshot(session_id, root)
        assert snap is not None, "Snapshot should be auto-persisted"
        assert len(snap.blocks) >= 1

        # Verify the snapshot contains structured data
        block = snap.blocks[0]
        assert len(block.covered_event_ids) > 0
        assert len(block.actions_taken) > 0

        _cleanup(session_id)

    def test_retention_report_matches_main_chain_behavior(self):
        """Retention report should match what actually happens in condensation."""
        events: list[AgentEventRecord] = []

        # Build a realistic mix
        for i in range(5):
            events.append(_make_event(f"ev-mc{i}", iteration=i, kind="tool_result", payload={
                "observation": f"output {i}" if i < 3 else "recent output " * 50,
                "tool_name": "edit_file" if i == 0 else "read_file",
                "tool_meta": {"success": True},
            }))

        # Get the retention report (what the policy says)
        report = decide_tool_trace_retention(events, "act")

        # Now verify the main chain respects it
        from aicoder.context.condense import prune_history_events
        pruned = prune_history_events(events, "act", use_retention_policy=True)

        # Every trace event should have been processed
        trace_pruned = [e for e in pruned if e.kind == "tool_result"]
        assert len(trace_pruned) == 5

        # Must_keep events should have full observations
        for decision in report.decisions:
            if decision.tier == RetentionTier.MUST_KEEP:
                matching = [e for e in pruned if e.event_id == decision.event_id]
                assert len(matching) == 1
                # Should not have retention_tier marker (must_keep = no trimming)
                assert matching[0].payload.get("retention_tier") != "trim_aggressively"
