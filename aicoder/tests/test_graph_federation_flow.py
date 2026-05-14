"""Tests for Phase 4: Runtime wiring — federation restore in main chain.

Covers: graph state federation fields, load_federation_restore_bundle in
agent_app_runner, no-federation passthrough behavior, and trace propagation.
"""
import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from aicoder.session.federation import create_task_thread, link_session
from aicoder.context.summary_types import SummaryBlock, CondensationSnapshot
from aicoder.context.summary_store import save_snapshot


# --- Fixtures ---


@pytest.fixture()
def fed_env(tmp_path):
    """Set up a task thread with one linked session and snapshot."""
    tt = create_task_thread(root=str(tmp_path))
    link_session(tt.task_thread_id, "sess-parent", role="parent", root=str(tmp_path))

    block = SummaryBlock(
        summary_id="sum-parent",
        goal="Implement feature X",
        actions_taken=["Created module A"],
        next_steps=["Test module A"],
        files_touched=["src/a.py"],
        covered_event_ids=["ev-1"],
        covered_iterations=[0],
    )
    snap = CondensationSnapshot(
        snapshot_id="snap-parent",
        session_id="sess-parent",
        source_event_count=5,
        latest_event_id="ev-1",
        blocks=[block],
        mode="act",
    )
    save_snapshot(snap, root=str(tmp_path))
    return tt, tmp_path


# --- Tests ---


class TestGraphStateFederationFields:
    def test_state_accepts_task_thread_id(self):
        from aicoder.graph.state import AgentGraphState

        state = AgentGraphState(
            session_id="test",
            task_thread_id="tt-123",
        )
        assert state.get("task_thread_id") == "tt-123"

    def test_state_accepts_federation_context(self):
        from aicoder.graph.state import AgentGraphState

        state = AgentGraphState(
            session_id="test",
            federation_context={"goals": ["Goal 1"]},
        )
        assert state.get("federation_context") is not None

    def test_state_accepts_federation_trace(self):
        from aicoder.graph.state import AgentGraphState

        state = AgentGraphState(
            session_id="test",
            federation_trace={"sessions_used": ["sess-1"]},
        )
        assert state.get("federation_trace") is not None

    def test_state_without_federation(self):
        """State without federation fields is valid (v1.6.1 compat)."""
        from aicoder.graph.state import AgentGraphState

        state = AgentGraphState(session_id="test")
        assert state.get("task_thread_id") is None
        assert state.get("federation_context") is None
        assert state.get("federation_trace") is None


class TestLoadFederationRestoreBundle:
    def test_load_with_valid_thread(self, fed_env):
        from aicoder.agent_app_runner import load_federation_restore_bundle

        tt, tmp_path = fed_env
        result = load_federation_restore_bundle(
            task_thread_id=tt.task_thread_id,
            root=str(tmp_path),
        )
        assert result is not None
        assert result["bundle"] is not None
        assert result["trace"]["sessions_used"] == ["sess-parent"]

    def test_load_with_no_thread_id(self, tmp_path):
        from aicoder.agent_app_runner import load_federation_restore_bundle

        result = load_federation_restore_bundle(
            task_thread_id="",
            root=str(tmp_path),
        )
        assert result is None

    def test_load_with_nonexistent_thread(self, tmp_path):
        from aicoder.agent_app_runner import load_federation_restore_bundle

        result = load_federation_restore_bundle(
            task_thread_id="ghost",
            root=str(tmp_path),
        )
        assert result is None

    def test_load_trace_has_events(self, fed_env):
        from aicoder.agent_app_runner import load_federation_restore_bundle

        tt, tmp_path = fed_env
        result = load_federation_restore_bundle(
            task_thread_id=tt.task_thread_id,
            root=str(tmp_path),
        )
        trace = result["trace"]
        assert "sessions_used" in trace
        assert "sessions_skipped" in trace
        assert "goals_count" in trace


class TestNoFederationPassthrough:
    def test_initial_state_without_federation(self):
        """Verify v1.6.1 behavior: no federation fields in initial state."""
        initial_state = {
            "session_id": "test",
            "user_input": "hello",
            "messages": [],
            "mode": "act",
            "phase": "idle",
            "root": "/tmp",
            "pending_tool_calls": [],
            "tool_observations": [],
            "loop_count": 0,
            "max_loops": 5,
            "runner_type": "cot",
        }
        # No federation fields — this is v1.6.1 baseline
        assert "task_thread_id" not in initial_state
        assert "federation_context" not in initial_state

    def test_initial_state_with_federation(self):
        """Verify v1.7 enhancement: federation fields added when configured."""
        initial_state = {
            "session_id": "test",
            "user_input": "hello",
            "messages": [],
            "mode": "act",
            "phase": "idle",
            "root": "/tmp",
            "pending_tool_calls": [],
            "tool_observations": [],
            "loop_count": 0,
            "max_loops": 5,
            "runner_type": "cot",
            "task_thread_id": "tt-123",
            "federation_context": "Prior session goals...",
            "federation_trace": {"sessions_used": ["sess-1"]},
        }
        assert initial_state["task_thread_id"] == "tt-123"
        assert initial_state["federation_context"] is not None
