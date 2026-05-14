"""Tests for Phase 5: Federation event types and replay.

Covers: federation event kinds, replay_federation_trace(), and audit trail.
"""
import time

import pytest

from aicoder.events.types import AgentEventRecord


def _make_event(kind: str, session_id: str, payload: dict, iteration: int = 0) -> AgentEventRecord:
    return AgentEventRecord(
        event_id=f"ev-{kind}-{session_id}",
        session_id=session_id,
        iteration=iteration,
        kind=kind,
        payload=payload,
    )


# --- Tests ---


class TestFederationEventKinds:
    def test_federation_started_event(self):
        ev = _make_event("federation_started", "sess-1", {
            "task_thread_id": "tt-123",
            "linked_session_count": 3,
        })
        assert ev.kind == "federation_started"
        assert ev.payload["task_thread_id"] == "tt-123"

    def test_federation_session_linked_event(self):
        ev = _make_event("federation_session_linked", "sess-1", {
            "task_thread_id": "tt-123",
            "linked_session_id": "sess-parent",
            "role": "parent",
        })
        assert ev.kind == "federation_session_linked"

    def test_federation_restored_event(self):
        ev = _make_event("federation_restored", "sess-1", {
            "task_thread_id": "tt-123",
            "sessions_used": ["sess-parent"],
            "goals_count": 2,
            "decisions_count": 5,
        })
        assert ev.kind == "federation_restored"

    def test_federation_skipped_event(self):
        ev = _make_event("federation_skipped", "sess-1", {
            "task_thread_id": "tt-123",
            "reason": "no snapshots found",
        })
        assert ev.kind == "federation_skipped"


class TestFederationReplayTrace:
    def test_replay_federation_trace_basic(self):
        from aicoder.events.replay import replay_federation_trace

        events = [
            _make_event("federation_started", "sess-1", {
                "task_thread_id": "tt-123",
                "linked_session_count": 2,
            }),
            _make_event("federation_session_linked", "sess-1", {
                "task_thread_id": "tt-123",
                "linked_session_id": "sess-parent",
                "role": "parent",
            }),
            _make_event("federation_session_linked", "sess-1", {
                "task_thread_id": "tt-123",
                "linked_session_id": "sess-child",
                "role": "child",
            }),
            _make_event("federation_restored", "sess-1", {
                "task_thread_id": "tt-123",
                "sessions_used": ["sess-parent"],
                "goals_count": 1,
            }),
        ]

        trace = replay_federation_trace(events)
        assert trace is not None
        assert trace["task_thread_id"] == "tt-123"
        assert trace["started"] is True
        assert len(trace["linked_sessions"]) == 2
        assert trace["restored"] is True
        assert trace["sessions_used"] == ["sess-parent"]

    def test_replay_federation_trace_skipped(self):
        from aicoder.events.replay import replay_federation_trace

        events = [
            _make_event("federation_started", "sess-1", {
                "task_thread_id": "tt-123",
                "linked_session_count": 0,
            }),
            _make_event("federation_skipped", "sess-1", {
                "task_thread_id": "tt-123",
                "reason": "no linked sessions",
            }),
        ]

        trace = replay_federation_trace(events)
        assert trace["restored"] is False
        assert trace["skipped"] is True
        assert trace["skip_reason"] == "no linked sessions"

    def test_replay_federation_trace_no_events(self):
        from aicoder.events.replay import replay_federation_trace

        trace = replay_federation_trace([])
        assert trace["started"] is False
        assert trace["restored"] is False

    def test_replay_federation_trace_mixed_with_other_events(self):
        """Federation events mixed with regular events should be filtered correctly."""
        from aicoder.events.replay import replay_federation_trace

        events = [
            _make_event("user_message", "sess-1", {"content": "hello"}),
            _make_event("federation_started", "sess-1", {"task_thread_id": "tt-1", "linked_session_count": 1}),
            _make_event("tool_call", "sess-1", {"tool_name": "read_file"}),
            _make_event("federation_restored", "sess-1", {"task_thread_id": "tt-1", "sessions_used": ["s-1"]}),
        ]

        trace = replay_federation_trace(events)
        assert trace["started"] is True
        assert trace["restored"] is True

    def test_replay_trace_has_skip_details(self):
        from aicoder.events.replay import replay_federation_trace

        events = [
            _make_event("federation_started", "sess-1", {"task_thread_id": "tt-1", "linked_session_count": 3}),
            _make_event("federation_session_linked", "sess-1", {"task_thread_id": "tt-1", "linked_session_id": "s-1", "role": "parent"}),
            _make_event("federation_session_linked", "sess-1", {"task_thread_id": "tt-1", "linked_session_id": "s-2", "role": "child"}),
            _make_event("federation_session_linked", "sess-1", {"task_thread_id": "tt-1", "linked_session_id": "s-3", "role": "child"}),
            _make_event("federation_restored", "sess-1", {
                "task_thread_id": "tt-1",
                "sessions_used": ["s-1", "s-2"],
                "sessions_skipped": ["s-3"],
                "goals_count": 2,
                "decisions_count": 3,
                "open_loops_count": 1,
                "files_count": 5,
            }),
        ]

        trace = replay_federation_trace(events)
        assert trace["linked_count"] == 3
        assert len(trace["sessions_skipped"]) == 1
        assert trace["sessions_skipped"] == ["s-3"]
        assert trace["goals_count"] == 2
