"""Tests for checkpoint recovery idempotency — Phase 5."""
import pytest

from aicoder.events.types import AgentEventRecord
from aicoder.recovery.checkpoint_guard import (
    CheckpointGuard,
    _tool_key,
    get_guard,
    register_guard,
    unregister_guard,
)


# ---------------------------------------------------------------------------
# Tool key generation
# ---------------------------------------------------------------------------


class TestToolKey:
    def test_uses_tool_call_id_when_available(self):
        key = _tool_key("read_file", {"path": "a.py"}, "tc_001")
        assert key == "tc:tc_001"

    def test_uses_hash_without_tool_call_id(self):
        key1 = _tool_key("read_file", {"path": "a.py"})
        key2 = _tool_key("read_file", {"path": "b.py"})
        assert key1 != key2

    def test_same_params_same_key(self):
        key1 = _tool_key("edit_file", {"path": "a.py", "old": "x", "new": "y"})
        key2 = _tool_key("edit_file", {"path": "a.py", "old": "x", "new": "y"})
        assert key1 == key2

    def test_different_order_same_key(self):
        key1 = _tool_key("edit_file", {"path": "a.py", "old": "x"})
        key2 = _tool_key("edit_file", {"old": "x", "path": "a.py"})
        assert key1 == key2


# ---------------------------------------------------------------------------
# CheckpointGuard basics
# ---------------------------------------------------------------------------


class TestCheckpointGuard:
    def test_empty_guard(self):
        g = CheckpointGuard()
        assert not g.is_completed("read_file", {})
        assert g.completed_count == 0

    def test_mark_and_check(self):
        g = CheckpointGuard()
        g.mark_completed("read_file", {"path": "a.py"})
        assert g.is_completed("read_file", {"path": "a.py"})
        assert g.completed_count == 1

    def test_get_observation(self):
        g = CheckpointGuard()
        obs = {"tool_name": "read_file", "success": True, "output": "hello"}
        g.mark_completed("read_file", {"path": "a.py"}, observation=obs)
        result = g.get_observation("read_file", {"path": "a.py"})
        assert result["success"] is True
        assert result["output"] == "hello"

    def test_no_observation_for_incomplete(self):
        g = CheckpointGuard()
        assert g.get_observation("read_file", {}) is None

    def test_with_tool_call_id(self):
        g = CheckpointGuard()
        g.mark_completed("edit_file", {"path": "a.py"}, tool_call_id="tc_123")
        assert g.is_completed("edit_file", {"path": "a.py"}, "tc_123")
        assert not g.is_completed("edit_file", {"path": "a.py"}, "tc_456")

    def test_different_tools_not_confused(self):
        g = CheckpointGuard()
        g.mark_completed("read_file", {"path": "a.py"})
        assert not g.is_completed("write_file", {"path": "a.py"})


# ---------------------------------------------------------------------------
# CheckpointGuard.from_events
# ---------------------------------------------------------------------------


def _make_event(event_id, iteration, kind, payload, session_id="test"):
    return AgentEventRecord(
        event_id=event_id,
        session_id=session_id,
        iteration=iteration,
        kind=kind,
        payload=payload,
    )


class TestFromEvents:
    def test_empty_events(self):
        g = CheckpointGuard.from_events([])
        assert g.completed_count == 0

    def test_completed_tool_call_result_pair(self):
        events = [
            _make_event("e1", 0, "tool_call", {
                "step_id": "s1", "tool_name": "read_file",
                "tool_input": {"path": "a.py"}, "tool_call_id": "tc_001",
            }),
            _make_event("e2", 0, "tool_result", {
                "step_id": "s1", "observation": "file content",
                "tool_meta": {"success": True, "tool_name": "read_file"},
            }),
        ]
        g = CheckpointGuard.from_events(events)
        assert g.completed_count == 1
        assert g.is_completed("read_file", {"path": "a.py"}, "tc_001")
        obs = g.get_observation("read_file", {"path": "a.py"}, "tc_001")
        assert obs["success"] is True
        assert obs["output"] == "file content"

    def test_tool_error_also_completed(self):
        events = [
            _make_event("e1", 0, "tool_call", {
                "step_id": "s1", "tool_name": "write_file",
                "tool_input": {"path": "a.py", "content": "x"},
            }),
            _make_event("e2", 0, "tool_error", {
                "step_id": "s1", "error": "permission denied",
                "tool_meta": {"success": False, "tool_name": "write_file"},
            }),
        ]
        g = CheckpointGuard.from_events(events)
        assert g.completed_count == 1
        obs = g.get_observation("write_file", {"path": "a.py", "content": "x"})
        assert obs["success"] is False

    def test_tool_call_without_result_not_completed(self):
        events = [
            _make_event("e1", 0, "tool_call", {
                "step_id": "s1", "tool_name": "read_file",
                "tool_input": {"path": "a.py"},
            }),
        ]
        g = CheckpointGuard.from_events(events)
        assert g.completed_count == 0

    def test_multiple_completed_tools(self):
        events = [
            _make_event("e1", 0, "tool_call", {
                "step_id": "s1", "tool_name": "read_file",
                "tool_input": {"path": "a.py"}, "tool_call_id": "tc_001",
            }),
            _make_event("e2", 0, "tool_result", {
                "step_id": "s1", "observation": "ok",
                "tool_meta": {"success": True},
            }),
            _make_event("e3", 1, "tool_call", {
                "step_id": "s2", "tool_name": "edit_file",
                "tool_input": {"path": "a.py", "old": "x", "new": "y"},
                "tool_call_id": "tc_002",
            }),
            _make_event("e4", 1, "tool_result", {
                "step_id": "s2", "observation": "edited",
                "tool_meta": {"success": True},
            }),
        ]
        g = CheckpointGuard.from_events(events)
        assert g.completed_count == 2
        assert g.is_completed("read_file", {"path": "a.py"}, "tc_001")
        assert g.is_completed("edit_file", {"path": "a.py", "old": "x", "new": "y"}, "tc_002")

    def test_raw_string_tool_input(self):
        """Handles tool_input as a string (CoT runner path)."""
        events = [
            _make_event("e1", 0, "tool_call", {
                "step_id": "s1", "tool_name": "run_shell",
                "tool_input": "echo hello",
            }),
            _make_event("e2", 0, "tool_result", {
                "step_id": "s1", "observation": "hello",
                "tool_meta": {"success": True},
            }),
        ]
        g = CheckpointGuard.from_events(events)
        assert g.completed_count == 1
        obs = g.get_observation("run_shell", {"raw": "echo hello"})
        assert obs["success"] is True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestGuardRegistry:
    def test_register_and_get(self):
        g = CheckpointGuard()
        g.mark_completed("read_file", {"path": "a.py"})
        register_guard("test-reg-1", g)
        assert get_guard("test-reg-1") is g
        unregister_guard("test-reg-1")

    def test_get_nonexistent(self):
        assert get_guard("nonexistent") is None

    def test_unregister(self):
        g = CheckpointGuard()
        register_guard("test-reg-2", g)
        unregister_guard("test-reg-2")
        assert get_guard("test-reg-2") is None


# ---------------------------------------------------------------------------
# Integration: execute_tool_node with guard
# ---------------------------------------------------------------------------


class TestExecuteToolNodeWithGuard:
    def test_skips_completed_tool(self, tmp_path):
        """When a guard marks a tool as completed, execute_tool_node skips it."""
        from aicoder.graph.nodes import execute_tool_node
        from aicoder.graph.state import register_coder, unregister_coder
        from aicoder.recovery.checkpoint_guard import CheckpointGuard, register_guard, unregister_guard

        session_id = "test-guard-integ"
        coder = _make_minimal_coder(str(tmp_path))
        register_coder(session_id, coder)

        guard = CheckpointGuard()
        guard.mark_completed(
            "read_file",
            {"path": "existing.py"},
            tool_call_id="tc_done",
            observation={
                "tool_name": "read_file",
                "success": True,
                "output": "previously read content",
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
                    {"name": "read_file", "params": {"path": "existing.py"}, "tool_call_id": "tc_done"},
                ],
                "tool_observations": [],
            }
            result = execute_tool_node(state)
            obs_list = result.get("tool_observations", [])
            assert len(obs_list) == 1
            assert obs_list[0]["output"] == "previously read content"
            assert obs_list[0]["tool_call_id"] == "tc_done"
        finally:
            unregister_guard(session_id)
            unregister_coder(session_id)

    def test_executes_new_tool(self, tmp_path):
        """When no guard, tools execute normally."""
        from aicoder.graph.nodes import execute_tool_node

        # Create a file to read
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\n")

        coder = _make_minimal_coder(str(tmp_path))
        from aicoder.graph.state import register_coder, unregister_coder
        session_id = "test-no-guard"
        register_coder(session_id, coder)

        try:
            state = {
                "session_id": session_id,
                "mode": "act",
                "root": str(tmp_path),
                "loop_count": 0,
                "pending_tool_calls": [
                    {"name": "read_file", "params": {"path": "test.py"}},
                ],
                "tool_observations": [],
            }
            result = execute_tool_node(state)
            obs_list = result.get("tool_observations", [])
            assert len(obs_list) == 1
            assert obs_list[0]["success"] is True
        finally:
            unregister_coder(session_id)


def _make_minimal_coder(root):
    """Create a minimal coder for execute_tool_node tests."""
    from aicoder.tests.conftest import make_graph_coder
    return make_graph_coder(responses=["done"], root=root)
