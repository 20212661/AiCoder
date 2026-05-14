"""Tests for Phase 1: Session Federation metadata layer.

Covers: TaskThread, SessionLink, FederationPolicy, local persistence, and API.
"""
import json
import os
import tempfile
import time

import pytest


# --- Helpers ---

def _make_session_link(session_id: str, role: str = "child", **kw):
    return {
        "session_id": session_id,
        "role": role,
        "linked_at": kw.get("linked_at", time.time()),
        "meta": kw.get("meta", {}),
    }


# --- Test: TaskThread creation and persistence ---

class TestTaskThread:
    def test_create_task_thread_returns_valid_id(self, tmp_path):
        from aicoder.session.federation import create_task_thread

        tt = create_task_thread(root=str(tmp_path))
        assert tt.task_thread_id
        assert len(tt.task_thread_id) > 8

    def test_task_thread_persists_to_disk(self, tmp_path):
        from aicoder.session.federation import create_task_thread

        tt = create_task_thread(root=str(tmp_path))
        fed_dir = tmp_path / ".aicoder" / "session_federation" / tt.task_thread_id
        assert fed_dir.exists()
        meta_file = fed_dir / "thread_meta.json"
        assert meta_file.exists()

    def test_task_thread_meta_has_created_at(self, tmp_path):
        from aicoder.session.federation import create_task_thread

        before = time.time()
        tt = create_task_thread(root=str(tmp_path))
        assert tt.created_at >= before
        assert tt.created_at <= time.time()

    def test_load_task_thread(self, tmp_path):
        from aicoder.session.federation import create_task_thread, load_task_thread

        tt = create_task_thread(root=str(tmp_path))
        loaded = load_task_thread(tt.task_thread_id, root=str(tmp_path))
        assert loaded is not None
        assert loaded.task_thread_id == tt.task_thread_id
        assert loaded.created_at == tt.created_at

    def test_load_nonexistent_returns_none(self, tmp_path):
        from aicoder.session.federation import load_task_thread

        result = load_task_thread("nonexistent-id", root=str(tmp_path))
        assert result is None


# --- Test: SessionLink ---

class TestSessionLink:
    def test_link_session(self, tmp_path):
        from aicoder.session.federation import create_task_thread, link_session

        tt = create_task_thread(root=str(tmp_path))
        link = link_session(tt.task_thread_id, "sess-001", role="parent", root=str(tmp_path))
        assert link.session_id == "sess-001"
        assert link.role == "parent"

    def test_link_session_persists(self, tmp_path):
        from aicoder.session.federation import (
            create_task_thread, link_session, list_linked_sessions,
        )

        tt = create_task_thread(root=str(tmp_path))
        link_session(tt.task_thread_id, "sess-001", role="parent", root=str(tmp_path))
        link_session(tt.task_thread_id, "sess-002", role="child", root=str(tmp_path))

        links = list_linked_sessions(tt.task_thread_id, root=str(tmp_path))
        assert len(links) == 2
        ids = {l.session_id for l in links}
        assert ids == {"sess-001", "sess-002"}

    def test_link_session_with_meta(self, tmp_path):
        from aicoder.session.federation import (
            create_task_thread, link_session, list_linked_sessions,
        )

        tt = create_task_thread(root=str(tmp_path))
        link_session(
            tt.task_thread_id, "sess-001", role="parent",
            meta={"label": "initial session"}, root=str(tmp_path),
        )

        links = list_linked_sessions(tt.task_thread_id, root=str(tmp_path))
        assert links[0].meta.get("label") == "initial session"

    def test_list_linked_sessions_empty(self, tmp_path):
        from aicoder.session.federation import (
            create_task_thread, list_linked_sessions,
        )

        tt = create_task_thread(root=str(tmp_path))
        links = list_linked_sessions(tt.task_thread_id, root=str(tmp_path))
        assert links == []

    def test_list_linked_sessions_ordered_by_time(self, tmp_path):
        from aicoder.session.federation import (
            create_task_thread, link_session, list_linked_sessions,
        )

        tt = create_task_thread(root=str(tmp_path))
        link_session(tt.task_thread_id, "sess-early", role="parent", root=str(tmp_path))
        link_session(tt.task_thread_id, "sess-late", role="child", root=str(tmp_path))

        links = list_linked_sessions(tt.task_thread_id, root=str(tmp_path))
        assert links[0].session_id == "sess-early"
        assert links[1].session_id == "sess-late"

    def test_duplicate_link_idempotent(self, tmp_path):
        from aicoder.session.federation import (
            create_task_thread, link_session, list_linked_sessions,
        )

        tt = create_task_thread(root=str(tmp_path))
        link_session(tt.task_thread_id, "sess-001", role="parent", root=str(tmp_path))
        link_session(tt.task_thread_id, "sess-001", role="parent", root=str(tmp_path))

        links = list_linked_sessions(tt.task_thread_id, root=str(tmp_path))
        assert len(links) == 1


# --- Test: FederationPolicy ---

class TestFederationPolicy:
    def test_default_policy(self):
        from aicoder.session.federation import FederationPolicy

        policy = FederationPolicy()
        assert policy.max_linked_sessions > 0
        assert policy.max_restore_sessions > 0
        assert policy.federation_tokens > 0

    def test_custom_policy(self):
        from aicoder.session.federation import FederationPolicy

        policy = FederationPolicy(
            max_linked_sessions=3,
            max_restore_sessions=2,
            federation_tokens=2048,
        )
        assert policy.max_linked_sessions == 3
        assert policy.federation_tokens == 2048

    def test_policy_frozen(self):
        from aicoder.session.federation import FederationPolicy

        policy = FederationPolicy()
        with pytest.raises(AttributeError):
            policy.max_linked_sessions = 99


# --- Test: Non-existent thread operations ---

class TestEdgeCases:
    def test_link_nonexistent_thread(self, tmp_path):
        from aicoder.session.federation import link_session

        with pytest.raises(ValueError, match="not found"):
            link_session("ghost-thread", "sess-001", role="child", root=str(tmp_path))

    def test_list_sessions_nonexistent_thread(self, tmp_path):
        from aicoder.session.federation import list_linked_sessions

        links = list_linked_sessions("ghost-thread", root=str(tmp_path))
        assert links == []
