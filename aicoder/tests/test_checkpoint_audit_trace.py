"""Tests for checkpoint audit trace — Phase 2: idempotency audit trail.

Validates that checkpoint guard emits structured checkpoint_skip events
and that replay can count skipped duplicate tool calls.
"""
import pytest

from aicoder.events.types import AgentEventRecord
from aicoder.recovery.checkpoint_guard import CheckpointGuard
from aicoder.tests.conftest import make_graph_coder


def _make_event(event_id, iteration, kind, payload, session_id="test"):
    return AgentEventRecord(
        event_id=event_id,
        session_id=session_id,
        iteration=iteration,
        kind=kind,
        payload=payload,
    )


class TestCheckpointSkipEvent:
    """execute_tool_node must emit checkpoint_skip events when guard skips."""

    def test_skip_produces_checkpoint_skip_event(self, tmp_path):
        """When a tool is skipped by the guard, a checkpoint_skip event must be emitted."""
        from aicoder.graph.nodes import execute_tool_node
        from aicoder.graph.state import register_coder, unregister_coder
        from aicoder.recovery.checkpoint_guard import register_guard, unregister_guard
        from aicoder.runners import register_runner, unregister_runner
        from aicoder.agent_step_store import AgentStepStore
        from aicoder.runners.cot_agent_runner import CotAgentRunner
        from unittest.mock import MagicMock

        session_id = "test-skip-event"
        coder = make_graph_coder(responses=["done"], root=str(tmp_path))
        register_coder(session_id, coder)

        step_store = AgentStepStore(session_id=session_id)
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry={}, step_store=step_store,
        )
        register_runner(session_id, runner)

        guard = CheckpointGuard()
        guard.mark_completed(
            "read_file",
            {"path": "existing.py"},
            tool_call_id="tc_skip",
            observation={
                "tool_name": "read_file",
                "success": True,
                "output": "cached content",
                "error": "",
                "rejected": False,
            },
        )
        register_guard(session_id, guard)

        try:
            state = {
                "session_id": session_id,
                "mode": "act",
                "root": str(tmp_path),
                "loop_count": 1,
                "pending_tool_calls": [
                    {"name": "read_file", "params": {"path": "existing.py"}, "tool_call_id": "tc_skip"},
                ],
                "tool_observations": [],
            }
            result = execute_tool_node(state)

            events = step_store.event_store.all_events()
            skip_events = [e for e in events if e.kind == "checkpoint_skip"]
            assert len(skip_events) >= 1, (
                f"Expected at least 1 checkpoint_skip event, got {len(skip_events)}. "
                f"Event kinds: {[e.kind for e in events]}"
            )

            skip_ev = skip_events[0]
            assert skip_ev.payload["tool_name"] == "read_file"
            assert skip_ev.payload["tool_call_id"] == "tc_skip"
            assert "session_id" in skip_ev.payload
            assert "step_id" in skip_ev.payload

        finally:
            unregister_runner(session_id)
            unregister_guard(session_id)
            unregister_coder(session_id)


class TestCheckpointSkipReplayStats:
    """Replay should be able to count skipped duplicate tool calls."""

    def test_count_skipped_from_events(self):
        """Replay helper counts checkpoint_skip events correctly."""
        from aicoder.debug.dump_helpers import dump_checkpoint_skip_metrics

        events = [
            _make_event("e1", 0, "checkpoint_skip", {
                "tool_name": "read_file", "tool_call_id": "tc_001",
                "session_id": "s1", "step_id": "step1",
            }),
            _make_event("e2", 0, "checkpoint_skip", {
                "tool_name": "edit_file", "tool_call_id": "tc_002",
                "session_id": "s1", "step_id": "step1",
            }),
            _make_event("e3", 1, "tool_result", {"observation": "ok"}),
        ]
        metrics = dump_checkpoint_skip_metrics(events)
        assert metrics["skipped_duplicate_tool_calls"] == 2
        assert metrics["by_tool"]["read_file"] == 1
        assert metrics["by_tool"]["edit_file"] == 1

    def test_count_zero_when_no_skips(self):
        from aicoder.debug.dump_helpers import dump_checkpoint_skip_metrics

        events = [
            _make_event("e1", 0, "tool_result", {"observation": "ok"}),
        ]
        metrics = dump_checkpoint_skip_metrics(events)
        assert metrics["skipped_duplicate_tool_calls"] == 0

    def test_empty_events(self):
        from aicoder.debug.dump_helpers import dump_checkpoint_skip_metrics

        metrics = dump_checkpoint_skip_metrics([])
        assert metrics["skipped_duplicate_tool_calls"] == 0


class TestCheckpointRecoveryChain:
    """End-to-end: first execution succeeds, recovery skips duplicate."""

    def test_guard_rebuilt_from_events_skips_previous(self):
        """Build guard from events, then verify it correctly skips on resume."""
        events = [
            _make_event("e1", 0, "tool_call", {
                "step_id": "s1", "tool_name": "write_file",
                "tool_input": {"path": "a.py", "content": "x"},
                "tool_call_id": "tc_001",
            }),
            _make_event("e2", 0, "tool_result", {
                "step_id": "s1", "observation": "written",
                "tool_meta": {"success": True, "tool_name": "write_file"},
            }),
            # Second tool call that was interrupted (no result)
            _make_event("e3", 1, "tool_call", {
                "step_id": "s2", "tool_name": "read_file",
                "tool_input": {"path": "b.py"},
                "tool_call_id": "tc_002",
            }),
        ]
        guard = CheckpointGuard.from_events(events)

        # write_file completed -> should be skipped
        assert guard.is_completed("write_file", {"path": "a.py", "content": "x"}, "tc_001")
        assert guard.get_observation("write_file", {"path": "a.py", "content": "x"}, "tc_001")["success"] is True

        # read_file never completed -> should NOT be skipped
        assert not guard.is_completed("read_file", {"path": "b.py"}, "tc_002")
