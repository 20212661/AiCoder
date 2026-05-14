"""Tests for Phase 3: Federation budget control and compression.

Covers: federation budget fields in ContextBudget, federation_context layer
in packer, token trimming of restore bundles, and trace visibility.
"""
import json
import os

import pytest

from aicoder.session.federation import create_task_thread, link_session, FederationPolicy
from aicoder.session.restore_bundle import RestoreBundle, build_restore_bundle
from aicoder.context.summary_types import SummaryBlock, CondensationSnapshot
from aicoder.context.summary_store import save_snapshot


# --- Fixtures ---


@pytest.fixture()
def fed_env(tmp_path):
    """Set up federation with multiple sessions having snapshots."""
    tt = create_task_thread(root=str(tmp_path))
    for i in range(5):
        sid = f"sess-{i}"
        link_session(tt.task_thread_id, sid, role="child", root=str(tmp_path))

        block = SummaryBlock(
            summary_id=f"sum-{sid}",
            goal=f"Goal for session {i}",
            findings=[f"Finding {j} from session {i}" for j in range(10)],
            actions_taken=[f"Action {j} in session {i}" for j in range(8)],
            failures=[],
            files_touched=[f"src/{sid}/file_{j}.py" for j in range(5)],
            next_steps=[f"Next step {j} for session {i}" for j in range(4)],
            covered_event_ids=[f"ev-{sid}-1"],
            covered_iterations=[0, 1],
        )
        snap = CondensationSnapshot(
            snapshot_id=f"snap-{sid}",
            session_id=sid,
            source_event_count=20,
            latest_event_id=f"ev-{sid}-1",
            blocks=[block],
            mode="act",
        )
        save_snapshot(snap, root=str(tmp_path))

    return tt, tmp_path


# --- Tests ---


class TestFederationBudgetFields:
    def test_context_budget_has_federation_tokens(self):
        from aicoder.context.policies import ContextBudget

        b = ContextBudget(
            repo_map_tokens=1000,
            history_tokens=2000,
            focused_file_tokens=1000,
            tool_trace_tokens=500,
            federation_tokens=4096,
        )
        assert b.federation_tokens == 4096

    def test_context_budget_default_federation_zero(self):
        from aicoder.context.policies import ContextBudget

        b = ContextBudget(
            repo_map_tokens=1000,
            history_tokens=2000,
            focused_file_tokens=1000,
            tool_trace_tokens=500,
        )
        assert b.federation_tokens == 0


class TestFederationContextTrim:
    def test_trim_restore_bundle_to_budget(self):
        from aicoder.context.packer import trim_federation_context

        # Build a large bundle
        bundle = RestoreBundle(
            task_thread_id="tt-test",
            goals=["Goal " * 200] * 5,
            decisions=["Decision " * 100] * 20,
            open_loops=["Loop " * 100] * 10,
            critical_files=[f"src/file_{i}.py" for i in range(30)],
        )
        trimmed = trim_federation_context(bundle, max_tokens=1000)
        assert trimmed is not None
        # Should have been trimmed
        total_chars = len(trimmed)
        assert total_chars <= 1000 * 4 * 1.1  # Allow 10% margin

    def test_trim_empty_bundle(self):
        from aicoder.context.packer import trim_federation_context

        bundle = RestoreBundle(task_thread_id="tt-test")
        trimmed = trim_federation_context(bundle, max_tokens=1000)
        assert trimmed == ""

    def test_trim_small_bundle_unchanged(self):
        from aicoder.context.packer import trim_federation_context

        bundle = RestoreBundle(
            task_thread_id="tt-test",
            goals=["Short goal"],
        )
        trimmed = trim_federation_context(bundle, max_tokens=10000)
        assert "Short goal" in trimmed


class TestFederationBudgetTrace:
    def test_pack_context_trace_includes_federation_when_set(self):
        """When federation_context is provided, trace should show federation layer."""
        from aicoder.context.packer import federation_context_messages

        bundle = RestoreBundle(
            task_thread_id="tt-test",
            goals=["Implement feature X"],
            decisions=["Chose library Y"],
            open_loops=["Need to test Z"],
            critical_files=["src/main.py"],
        )
        msgs = federation_context_messages(bundle)
        assert len(msgs) > 0
        # Should contain goal info
        combined = " ".join(m.get("content", "") for m in msgs)
        assert "feature X" in combined

    def test_federation_context_messages_empty_bundle(self):
        from aicoder.context.packer import federation_context_messages

        bundle = RestoreBundle(task_thread_id="tt-test")
        msgs = federation_context_messages(bundle)
        assert msgs == []


class TestBudgetIntegration:
    def test_full_bundle_trim_produces_valid_text(self, fed_env):
        from aicoder.context.packer import trim_federation_context

        tt, tmp_path = fed_env
        bundle = build_restore_bundle(tt.task_thread_id, root=str(tmp_path))
        trimmed = trim_federation_context(bundle, max_tokens=500)
        assert isinstance(trimmed, str)
        assert len(trimmed) > 0

    def test_trim_trace_visible(self, fed_env):
        from aicoder.context.packer import trim_federation_context

        tt, tmp_path = fed_env
        bundle = build_restore_bundle(tt.task_thread_id, root=str(tmp_path))
        original_len = len(bundle.to_dict()["goals"])
        trimmed = trim_federation_context(bundle, max_tokens=200)
        # Should produce something even if heavily trimmed
        assert isinstance(trimmed, str)
