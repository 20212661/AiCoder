"""Tests for Phase 2: Cross-session restore bundle builder.

Covers: RestoreBundle construction, aggregation from linked sessions,
structured output format, and edge cases.
"""
import json
import os
import time

import pytest

from aicoder.session.federation import (
    create_task_thread,
    link_session,
    list_linked_sessions,
)
from aicoder.context.summary_types import SummaryBlock, CondensationSnapshot
from aicoder.context.summary_store import save_snapshot


# --- Fixtures ---


@pytest.fixture()
def fed_env(tmp_path):
    """Set up a task thread with linked sessions and snapshots."""
    tt = create_task_thread(root=str(tmp_path))
    link_session(tt.task_thread_id, "sess-parent", role="parent", root=str(tmp_path))
    link_session(tt.task_thread_id, "sess-child-1", role="child", root=str(tmp_path))

    # Save snapshots for each session
    for sid in ["sess-parent", "sess-child-1"]:
        block = SummaryBlock(
            summary_id=f"sum-{sid}",
            goal=f"Goal for {sid}",
            findings=[f"Found X in {sid}"],
            actions_taken=[f"Did A in {sid}"],
            failures=[],
            files_touched=[f"src/{sid}/main.py"],
            next_steps=[f"Continue with {sid}"],
            covered_event_ids=[f"ev-{sid}-1"],
            covered_iterations=[0, 1],
        )
        snap = CondensationSnapshot(
            snapshot_id=f"snap-{sid}",
            session_id=sid,
            source_event_count=10,
            latest_event_id=f"ev-{sid}-1",
            blocks=[block],
            mode="act",
        )
        save_snapshot(snap, root=str(tmp_path))

    return tt, tmp_path


# --- Tests ---


class TestRestoreBundle:
    def test_build_restore_bundle(self, fed_env):
        from aicoder.session.restore_bundle import build_restore_bundle

        tt, tmp_path = fed_env
        bundle = build_restore_bundle(tt.task_thread_id, root=str(tmp_path))

        assert bundle is not None
        assert bundle.task_thread_id == tt.task_thread_id
        assert len(bundle.sessions_used) > 0

    def test_bundle_has_goals(self, fed_env):
        from aicoder.session.restore_bundle import build_restore_bundle

        tt, tmp_path = fed_env
        bundle = build_restore_bundle(tt.task_thread_id, root=str(tmp_path))

        assert len(bundle.goals) > 0
        # Should have goals from both sessions
        goals_text = " ".join(bundle.goals)
        assert "sess-parent" in goals_text or "Goal for" in goals_text

    def test_bundle_has_decisions(self, fed_env):
        from aicoder.session.restore_bundle import build_restore_bundle

        tt, tmp_path = fed_env
        bundle = build_restore_bundle(tt.task_thread_id, root=str(tmp_path))

        # decisions come from actions_taken
        assert isinstance(bundle.decisions, list)

    def test_bundle_has_open_loops(self, fed_env):
        from aicoder.session.restore_bundle import build_restore_bundle

        tt, tmp_path = fed_env
        bundle = build_restore_bundle(tt.task_thread_id, root=str(tmp_path))

        # open_loops come from next_steps
        assert isinstance(bundle.open_loops, list)
        assert len(bundle.open_loops) > 0

    def test_bundle_has_critical_files(self, fed_env):
        from aicoder.session.restore_bundle import build_restore_bundle

        tt, tmp_path = fed_env
        bundle = build_restore_bundle(tt.task_thread_id, root=str(tmp_path))

        assert isinstance(bundle.critical_files, list)
        assert len(bundle.critical_files) > 0

    def test_bundle_has_constraints(self, fed_env):
        from aicoder.session.restore_bundle import build_restore_bundle

        tt, tmp_path = fed_env
        bundle = build_restore_bundle(tt.task_thread_id, root=str(tmp_path))

        assert isinstance(bundle.constraints, list)

    def test_bundle_respects_session_cap(self, fed_env):
        """When max_restore_sessions < linked sessions, only top N are used."""
        from aicoder.session.restore_bundle import build_restore_bundle
        from aicoder.session.federation import FederationPolicy

        tt, tmp_path = fed_env
        # Add a third session
        link_session(tt.task_thread_id, "sess-child-2", role="child", root=str(tmp_path))

        policy = FederationPolicy(max_restore_sessions=1)
        bundle = build_restore_bundle(
            tt.task_thread_id, root=str(tmp_path), policy=policy,
        )
        # Should use at most 1 session
        assert len(bundle.sessions_used) <= 1

    def test_bundle_empty_thread(self, tmp_path):
        from aicoder.session.restore_bundle import build_restore_bundle

        tt = create_task_thread(root=str(tmp_path))
        bundle = build_restore_bundle(tt.task_thread_id, root=str(tmp_path))

        assert bundle is not None
        assert bundle.goals == []
        assert bundle.sessions_used == []

    def test_bundle_nonexistent_thread(self, tmp_path):
        from aicoder.session.restore_bundle import build_restore_bundle

        bundle = build_restore_bundle("ghost-thread", root=str(tmp_path))
        assert bundle is not None
        assert bundle.sessions_used == []

    def test_bundle_to_dict(self, fed_env):
        from aicoder.session.restore_bundle import build_restore_bundle

        tt, tmp_path = fed_env
        bundle = build_restore_bundle(tt.task_thread_id, root=str(tmp_path))
        d = bundle.to_dict()

        assert "task_thread_id" in d
        assert "goals" in d
        assert "decisions" in d
        assert "open_loops" in d
        assert "critical_files" in d
        assert "constraints" in d
        assert "sessions_used" in d

    def test_bundle_from_sessions_without_snapshots(self, tmp_path):
        """Sessions without snapshots should be skipped gracefully."""
        from aicoder.session.restore_bundle import build_restore_bundle

        tt = create_task_thread(root=str(tmp_path))
        link_session(tt.task_thread_id, "sess-no-snap", role="child", root=str(tmp_path))

        bundle = build_restore_bundle(tt.task_thread_id, root=str(tmp_path))
        assert bundle is not None
        # Session without snapshot should not appear in sessions_used
        assert "sess-no-snap" not in bundle.sessions_used
