"""Tests for permission and approval flows in the LangGraph workflow."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from aicoder.graph.state import AgentGraphState, register_coder
from aicoder.graph.nodes import permission_node
from aicoder.permission_modes import (
    can_use_tool_in_mode,
    ToolPermissionContext,
)
from aicoder.tests.conftest import (
    FakeIO,
    FakeModel,
    make_graph_coder,
    make_tool_call_xml,
    invoke_graph,
)


class TestPermissionNodeDeny:
    def test_edit_denied_in_plan_mode(self):
        """edit_file should be denied in plan mode."""
        coder = make_graph_coder(responses=[], mode="plan")
        register_coder("test-session", coder)
        state: AgentGraphState = {
            "session_id": "test-session",
            "pending_tool_calls": [
                {"name": "edit_file", "params": {"path": "a.py", "old_text": "x", "new_text": "y"}},
            ],
            "mode": "plan",
            "tool_observations": [],
        }

        result = permission_node(state)
        # All tools denied, pending_tool_calls should be empty
        assert result["pending_tool_calls"] == []
        # Should have a denied observation
        obs = result.get("tool_observations", [])
        assert any(o["tool_name"] == "edit_file" and not o["success"] for o in obs)

    def test_write_denied_in_plan_mode(self):
        """write_file should be denied in plan mode."""
        coder = make_graph_coder(responses=[], mode="plan")
        register_coder("test-session", coder)
        state: AgentGraphState = {
            "session_id": "test-session",
            "pending_tool_calls": [
                {"name": "write_file", "params": {"path": "b.py", "content": "new"}},
            ],
            "mode": "plan",
            "tool_observations": [],
        }

        result = permission_node(state)
        assert result["pending_tool_calls"] == []
        obs = result.get("tool_observations", [])
        assert any(not o["success"] for o in obs)


class TestPermissionNodeAllow:
    def test_read_allowed_in_plan_mode(self):
        """read_file should be allowed in plan mode."""
        coder = make_graph_coder(responses=[], mode="plan")
        register_coder("test-session", coder)
        state: AgentGraphState = {
            "session_id": "test-session",
            "pending_tool_calls": [
                {"name": "read_file", "params": {"path": "README.md"}},
            ],
            "mode": "plan",
            "tool_observations": [],
        }

        result = permission_node(state)
        assert len(result["pending_tool_calls"]) == 1

    def test_list_files_allowed_in_plan_mode(self):
        """list_files should be allowed in plan mode."""
        coder = make_graph_coder(responses=[], mode="plan")
        register_coder("test-session", coder)
        state: AgentGraphState = {
            "session_id": "test-session",
            "pending_tool_calls": [
                {"name": "list_files", "params": {"path": "."}},
            ],
            "mode": "plan",
            "tool_observations": [],
        }

        result = permission_node(state)
        assert len(result["pending_tool_calls"]) == 1

    def test_edit_auto_approved_in_act_mode(self):
        """edit_file should require approval in act mode (ask behavior)."""
        coder = make_graph_coder(responses=[], confirm_answers=[True], mode="act")
        register_coder("test-session", coder)
        state: AgentGraphState = {
            "session_id": "test-session",
            "pending_tool_calls": [
                {"name": "edit_file", "params": {"path": "a.py", "old_text": "x", "new_text": "y"}},
            ],
            "mode": "act",
            "tool_observations": [],
        }

        result = permission_node(state)
        assert len(result["pending_tool_calls"]) == 1

    def test_write_auto_approved_in_act_mode(self):
        """write_file should require approval in act mode (ask behavior)."""
        coder = make_graph_coder(responses=[], confirm_answers=[True], mode="act")
        register_coder("test-session", coder)
        state: AgentGraphState = {
            "session_id": "test-session",
            "pending_tool_calls": [
                {"name": "write_file", "params": {"path": "b.py", "content": "new"}},
            ],
            "mode": "act",
            "tool_observations": [],
        }

        result = permission_node(state)
        assert len(result["pending_tool_calls"]) == 1


class TestPermissionNodeUserApproval:
    def test_user_approves_tool(self):
        """When behavior is 'ask' and user approves, tool should be in approved list.

        Use 'default' mode so run_shell triggers 'ask' behavior.
        """
        coder = make_graph_coder(responses=[], confirm_answers=[True], mode="default")
        register_coder("test-session", coder)
        state: AgentGraphState = {
            "session_id": "test-session",
            "pending_tool_calls": [
                {"name": "run_shell", "params": {"command": "python --version"}},
            ],
            "mode": "default",
            "tool_observations": [],
        }

        result = permission_node(state)
        assert len(result["pending_tool_calls"]) == 1

    def test_user_rejects_tool(self):
        """When behavior is 'ask' and user rejects, tool should not execute.

        Use 'default' mode so run_shell goes to 'ask' behavior.
        """
        coder = make_graph_coder(responses=[], confirm_answers=[False], mode="default")
        register_coder("test-session", coder)
        state: AgentGraphState = {
            "session_id": "test-session",
            "pending_tool_calls": [
                {"name": "run_shell", "params": {"command": "python --version"}},
            ],
            "mode": "default",
            "tool_observations": [],
        }

        result = permission_node(state)
        assert result["pending_tool_calls"] == []
        obs = result.get("tool_observations", [])
        rejected = [o for o in obs if o.get("rejected")]
        assert len(rejected) == 1
        assert rejected[0]["tool_name"] == "run_shell"


class TestCanUseToolInMode:
    def test_plan_mode_deny_edit(self):
        ctx = ToolPermissionContext(mode="plan")
        decision = can_use_tool_in_mode("edit_file", {"path": "a.py"}, ctx, None)
        assert decision.behavior == "deny"

    def test_plan_mode_deny_write(self):
        ctx = ToolPermissionContext(mode="plan")
        decision = can_use_tool_in_mode("write_file", {"path": "a.py"}, ctx, None)
        assert decision.behavior == "deny"

    def test_plan_mode_allow_read(self):
        ctx = ToolPermissionContext(mode="plan")
        decision = can_use_tool_in_mode("read_file", {"path": "a.py"}, ctx, None)
        assert decision.behavior == "allow"

    def test_act_mode_allow_edit(self):
        ctx = ToolPermissionContext(mode="act")
        decision = can_use_tool_in_mode("edit_file", {"path": "a.py"}, ctx, None)
        assert decision.behavior == "ask"

    def test_act_mode_allow_write(self):
        ctx = ToolPermissionContext(mode="act")
        decision = can_use_tool_in_mode("write_file", {"path": "a.py"}, ctx, None)
        assert decision.behavior == "ask"


class TestInterruptModule:
    def test_blocking_tool_approval_approved(self):
        """Blocking approval should return True when IO approves."""
        from aicoder.graph.interrupts import _blocking_tool_approval

        coder = make_graph_coder(responses=[], confirm_answers=[True])
        register_coder("test-session", coder)
        state: AgentGraphState = {"session_id": "test-session"}

        result = _blocking_tool_approval(
            state, tool_name="edit_file", desc="edit a.py", params_preview="path=a.py"
        )
        assert result is True

    def test_blocking_tool_approval_rejected(self):
        """Blocking approval should return False when IO rejects."""
        from aicoder.graph.interrupts import _blocking_tool_approval

        coder = make_graph_coder(responses=[], confirm_answers=[False])
        register_coder("test-session", coder)
        state: AgentGraphState = {"session_id": "test-session"}

        result = _blocking_tool_approval(
            state, tool_name="edit_file", desc="edit a.py", params_preview="path=a.py"
        )
        assert result is False

    def test_blocking_plan_approval(self):
        """Blocking plan approval should delegate to IO."""
        from aicoder.graph.interrupts import _blocking_plan_approval

        coder = make_graph_coder(responses=[], confirm_answers=[True])
        register_coder("test-session", coder)
        state: AgentGraphState = {"session_id": "test-session"}

        result = _blocking_plan_approval(state, plan_text="Step 1: Read files")
        assert result is True

    def test_no_coder_returns_false(self):
        """When no coder is available, blocking approval should return False."""
        from aicoder.graph.interrupts import _blocking_tool_approval

        state: AgentGraphState = {}
        result = _blocking_tool_approval(
            state, tool_name="edit_file", desc="test", params_preview=""
        )
        assert result is False


class TestCheckpointerModule:
    def test_get_checkpointer_creates_db(self, tmp_path):
        from aicoder.graph.checkpointer import get_checkpointer

        db = tmp_path / "sub" / "test.sqlite"
        cp = get_checkpointer(db_path=db)
        assert cp is not None
        # DB file should be created by the connection
        assert db.parent.exists()

    def test_get_thread_config(self):
        from aicoder.graph.checkpointer import get_thread_config

        config = get_thread_config("sess-123")
        assert config == {"configurable": {"thread_id": "sess-123"}}

    def test_default_db_path(self):
        from aicoder.graph.checkpointer import DEFAULT_DB_DIR, DEFAULT_DB_NAME
        from pathlib import Path

        assert "aicoder" in str(DEFAULT_DB_DIR)
        assert DEFAULT_DB_NAME == "checkpoints.sqlite"
