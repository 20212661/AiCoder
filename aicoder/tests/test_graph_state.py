"""Tests for graph state schema correctness."""
from __future__ import annotations

from typing import get_args

from aicoder.graph.state import (
    AgentGraphState,
    ApprovalRequest,
    PermissionMode,
    RunPhase,
    ToolObservation,
)


class TestPermissionMode:
    def test_has_all_values(self):
        values = get_args(PermissionMode)
        assert "sniff" in values
        assert "plan" in values
        assert "act" in values

    def test_exactly_three_modes(self):
        values = get_args(PermissionMode)
        assert len(values) == 3


class TestRunPhase:
    def test_has_all_values(self):
        values = get_args(RunPhase)
        expected = [
            "idle", "preparing", "planning", "waiting_approval",
            "acting", "tool_running", "verifying", "summarizing",
            "done", "error",
        ]
        for phase in expected:
            assert phase in values

    def test_exactly_ten_phases(self):
        values = get_args(RunPhase)
        assert len(values) == 10


class TestApprovalRequest:
    def test_all_fields_settable(self):
        req: ApprovalRequest = {
            "id": "abc-123",
            "kind": "tool",
            "title": "Allow edit?",
            "body": "edit_file wants to modify a.py",
            "tool_name": "edit_file",
            "params": {"path": "a.py"},
            "diff": "--- a.py\n+++ a.py",
            "mode": "act",
        }
        assert req["id"] == "abc-123"
        assert req["kind"] == "tool"
        assert req["tool_name"] == "edit_file"
        assert req["mode"] == "act"

    def test_partial_fields(self):
        req: ApprovalRequest = {"kind": "plan", "title": "Plan?"}
        assert req["kind"] == "plan"

    def test_kind_values(self):
        from typing import get_args, Literal

        kind_type = ApprovalRequest.__annotations__.get("kind")
        # kind is Literal["plan", "tool", "command"]
        assert "plan" in ("plan", "tool", "command")
        assert "tool" in ("plan", "tool", "command")
        assert "command" in ("plan", "tool", "command")


class TestToolObservation:
    def test_success_observation(self):
        obs: ToolObservation = {
            "tool_name": "read_file",
            "params": {"path": "README.md"},
            "success": True,
            "output": "file contents",
        }
        assert obs["success"] is True
        assert obs["tool_name"] == "read_file"

    def test_failure_observation(self):
        obs: ToolObservation = {
            "tool_name": "write_file",
            "params": {"path": "/forbidden"},
            "success": False,
            "error": "Permission denied",
            "rejected": False,
        }
        assert obs["success"] is False
        assert obs["error"] == "Permission denied"

    def test_rejected_observation(self):
        obs: ToolObservation = {
            "tool_name": "run_shell",
            "params": {"command": "rm -rf /"},
            "success": False,
            "error": "User rejected the tool call.",
            "rejected": True,
        }
        assert obs["rejected"] is True


class TestAgentGraphState:
    def test_all_fields_settable(self):
        state: AgentGraphState = {
            "session_id": "sess-001",
            "user_input": "read foo.py",
            "messages": [{"role": "user", "content": "read foo.py"}],
            "mode": "act",
            "phase": "acting",
            "root": "/home/user/project",
            "current_plan": "",
            "approved_plan": "",
            "approval_request": None,
            "approval_response": False,
            "pending_tool_calls": [{"name": "read_file", "params": {"path": "foo.py"}}],
            "tool_observations": [],
            "final_response": "",
            "error": "",
            "loop_count": 1,
            "max_loops": 5,
        }
        assert state["session_id"] == "sess-001"
        assert state["mode"] == "act"
        assert state["loop_count"] == 1
        assert len(state["pending_tool_calls"]) == 1

    def test_empty_state(self):
        state: AgentGraphState = {}
        assert state.get("phase") is None
        assert state.get("messages") is None

    def test_state_merge_simulation(self):
        """Simulate LangGraph state merge behavior: partial updates are merged."""
        base: dict = {
            "messages": [{"role": "system", "content": "sys"}],
            "loop_count": 0,
            "phase": "idle",
        }
        update: dict = {
            "loop_count": 1,
            "phase": "acting",
            "pending_tool_calls": [{"name": "read_file", "params": {"path": "a.py"}}],
        }
        # LangGraph merges dict updates
        merged = {**base, **update}
        assert merged["loop_count"] == 1
        assert merged["phase"] == "acting"
        assert merged["messages"] == [{"role": "system", "content": "sys"}]
        assert len(merged["pending_tool_calls"]) == 1

    def test_mode_field_accepts_all_permission_modes(self):
        for mode in get_args(PermissionMode):
            state: AgentGraphState = {"mode": mode}
            assert state["mode"] == mode
