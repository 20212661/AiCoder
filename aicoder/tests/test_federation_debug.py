"""Tests for Phase 6: Federation observability and debug output.

Covers: federation layer in context_trace, dump_federation_context(),
dump_federation_replay_trace(), and explainability requirements.
"""
import json
import os

import pytest

from aicoder.session.federation import create_task_thread, link_session
from aicoder.session.restore_bundle import RestoreBundle
from aicoder.context.summary_types import SummaryBlock, CondensationSnapshot
from aicoder.context.summary_store import save_snapshot
from aicoder.events.types import AgentEventRecord


def _make_event(kind: str, session_id: str, payload: dict) -> AgentEventRecord:
    return AgentEventRecord(
        event_id=f"ev-{kind}",
        session_id=session_id,
        iteration=0,
        kind=kind,
        payload=payload,
    )


@pytest.fixture()
def fed_env(tmp_path):
    tt = create_task_thread(root=str(tmp_path))
    link_session(tt.task_thread_id, "sess-parent", role="parent", root=str(tmp_path))
    link_session(tt.task_thread_id, "sess-child", role="child", root=str(tmp_path))

    for sid in ["sess-parent", "sess-child"]:
        block = SummaryBlock(
            summary_id=f"sum-{sid}",
            goal=f"Goal for {sid}",
            actions_taken=[f"Action in {sid}"],
            next_steps=[f"Continue {sid}"],
            files_touched=[f"src/{sid}/main.py"],
            covered_event_ids=[f"ev-{sid}"],
            covered_iterations=[0],
        )
        snap = CondensationSnapshot(
            snapshot_id=f"snap-{sid}",
            session_id=sid,
            source_event_count=5,
            latest_event_id=f"ev-{sid}",
            blocks=[block],
            mode="act",
        )
        save_snapshot(snap, root=str(tmp_path))

    return tt, tmp_path


# --- Tests ---


class TestDumpFederationContext:
    def test_dump_returns_structured_dict(self, fed_env):
        from aicoder.debug.dump_helpers import dump_federation_context

        tt, tmp_path = fed_env
        result = dump_federation_context(tt.task_thread_id, root=str(tmp_path))

        assert isinstance(result, dict)
        assert "task_thread_id" in result
        assert result["task_thread_id"] == tt.task_thread_id

    def test_dump_shows_sessions_used(self, fed_env):
        from aicoder.debug.dump_helpers import dump_federation_context

        tt, tmp_path = fed_env
        result = dump_federation_context(tt.task_thread_id, root=str(tmp_path))

        assert "sessions_used" in result
        assert len(result["sessions_used"]) > 0

    def test_dump_shows_sessions_skipped(self, fed_env):
        from aicoder.debug.dump_helpers import dump_federation_context

        tt, tmp_path = fed_env
        result = dump_federation_context(tt.task_thread_id, root=str(tmp_path))

        assert "sessions_skipped" in result

    def test_dump_shows_budget_usage(self, fed_env):
        from aicoder.debug.dump_helpers import dump_federation_context

        tt, tmp_path = fed_env
        result = dump_federation_context(tt.task_thread_id, root=str(tmp_path))

        assert "context_tokens" in result
        assert "federation_budget_tokens" in result

    def test_dump_shows_content_summary(self, fed_env):
        from aicoder.debug.dump_helpers import dump_federation_context

        tt, tmp_path = fed_env
        result = dump_federation_context(tt.task_thread_id, root=str(tmp_path))

        assert "goals_count" in result
        assert "decisions_count" in result
        assert "open_loops_count" in result
        assert "files_count" in result

    def test_dump_shows_discard_reason(self, fed_env):
        """When sessions are skipped, dump must explain why."""
        from aicoder.debug.dump_helpers import dump_federation_context
        from aicoder.session.federation import FederationPolicy

        tt, tmp_path = fed_env
        # Add many sessions to force skipping
        for i in range(10):
            link_session(tt.task_thread_id, f"sess-extra-{i}", role="child", root=str(tmp_path))

        result = dump_federation_context(
            tt.task_thread_id, root=str(tmp_path),
            policy=FederationPolicy(max_restore_sessions=1),
        )
        assert "discard_reason" in result
        assert "exceeded" in result["discard_reason"].lower() or "cap" in result["discard_reason"].lower() or len(result["sessions_skipped"]) > 0

    def test_dump_nonexistent_thread(self, tmp_path):
        from aicoder.debug.dump_helpers import dump_federation_context

        result = dump_federation_context("ghost-thread", root=str(tmp_path))
        assert result["task_thread_id"] == "ghost-thread"
        assert result["sessions_used"] == []


class TestDumpFederationReplayTrace:
    def test_dump_from_events(self):
        from aicoder.debug.dump_helpers import dump_federation_replay_trace

        events = [
            _make_event("federation_started", "sess-1", {
                "task_thread_id": "tt-123",
                "linked_session_count": 2,
            }),
            _make_event("federation_session_linked", "sess-1", {
                "task_thread_id": "tt-123",
                "linked_session_id": "s-parent",
                "role": "parent",
            }),
            _make_event("federation_restored", "sess-1", {
                "task_thread_id": "tt-123",
                "sessions_used": ["s-parent"],
                "goals_count": 1,
                "decisions_count": 2,
            }),
        ]

        result = dump_federation_replay_trace(events)
        assert result["started"] is True
        assert result["restored"] is True
        assert len(result["linked_sessions"]) == 1

    def test_dump_skipped_trace(self):
        from aicoder.debug.dump_helpers import dump_federation_replay_trace

        events = [
            _make_event("federation_started", "sess-1", {"task_thread_id": "tt-1", "linked_session_count": 0}),
            _make_event("federation_skipped", "sess-1", {"task_thread_id": "tt-1", "reason": "no linked sessions"}),
        ]

        result = dump_federation_replay_trace(events)
        assert result["skipped"] is True
        assert result["skip_reason"] == "no linked sessions"

    def test_dump_empty_events(self):
        from aicoder.debug.dump_helpers import dump_federation_replay_trace

        result = dump_federation_replay_trace([])
        assert result["started"] is False


class TestContextTraceFederation:
    def test_trace_includes_federation_section(self, fed_env):
        from aicoder.debug.context_trace import trace_federation

        tt, tmp_path = fed_env
        result = trace_federation(tt.task_thread_id, root=str(tmp_path))

        assert isinstance(result, dict)
        assert "federation_available" in result
        assert result["federation_available"] is True

    def test_trace_shows_tokens(self, fed_env):
        from aicoder.debug.context_trace import trace_federation

        tt, tmp_path = fed_env
        result = trace_federation(tt.task_thread_id, root=str(tmp_path))

        assert "context_tokens" in result
        assert isinstance(result["context_tokens"], int)

    def test_trace_no_federation(self, tmp_path):
        from aicoder.debug.context_trace import trace_federation

        result = trace_federation("ghost-thread", root=str(tmp_path))
        assert result["federation_available"] is False
