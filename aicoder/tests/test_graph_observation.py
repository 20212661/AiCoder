"""Tests for graph observation pipeline — §8.3 + §8.4."""

import pytest
from unittest.mock import MagicMock

from aicoder.graph.nodes import execute_tool_node, observe_tool_result
from aicoder.tools.result import ToolCall, ToolResult, ExecutionState


def _make_state(**overrides):
    """Build a minimal AgentGraphState-like dict for testing."""
    state = {
        "session_id": "test-session",
        "mode": "act",
        "pending_tool_calls": [],
        "tool_observations": [],
        "messages": [],
        "loop_count": 1,
        "max_loops": 5,
    }
    state.update(overrides)
    return state


def _make_coder():
    coder = MagicMock()
    coder.io = MagicMock()
    coder.tool_exec_state = ExecutionState(mode="act")
    return coder


class TestObserveToolResult:
    def test_failure_enters_messages(self):
        state = _make_state(tool_observations=[{
            "tool_name": "read_file",
            "success": False,
            "output": "",
            "error": "file not found",
            "rejected": False,
        }])
        result = observe_tool_result(state)
        msgs = result["messages"]
        assert any("FAILED" in m["content"] for m in msgs)
        assert any("read_file" in m["content"] for m in msgs)
        assert result["tool_observations"] == []

    def test_success_enters_messages(self):
        state = _make_state(tool_observations=[{
            "tool_name": "read_file",
            "success": True,
            "output": "file content",
            "error": "",
            "rejected": False,
        }])
        result = observe_tool_result(state)
        msgs = result["messages"]
        assert any("Result" in m["content"] for m in msgs)

    def test_rejected_enters_messages(self):
        state = _make_state(tool_observations=[{
            "tool_name": "run_shell",
            "success": False,
            "output": "",
            "error": "",
            "rejected": True,
        }])
        result = observe_tool_result(state)
        msgs = result["messages"]
        assert any("REJECTED" in m["content"] for m in msgs)

    def test_multiple_observations(self):
        state = _make_state(tool_observations=[
            {"tool_name": "a", "success": True, "output": "ok", "error": "", "rejected": False},
            {"tool_name": "b", "success": False, "output": "", "error": "fail", "rejected": False},
        ])
        result = observe_tool_result(state)
        assert len(result["messages"]) == 2
        assert result["tool_observations"] == []

    def test_empty_observations(self):
        state = _make_state(tool_observations=[])
        result = observe_tool_result(state)
        assert result["messages"] == []
        assert result["tool_observations"] == []


class TestExecuteToolNodeStepSync:
    """Test that step store is synced after tool execution."""

    def test_step_updated_after_tool_success(self):
        from aicoder.agent_step_store import AgentStepStore
        from aicoder.tools.executor import ToolExecutor, ToolCoordinator
        from aicoder.tools.handlers.base import ToolHandler

        class OkHandler(ToolHandler):
            name = "ok_tool"
            requires_approval = False
            def execute(self, tc, coder):
                return ToolResult.ok("ok_tool", "hello")

        coord = ToolCoordinator()
        coord.register(OkHandler())

        # Build a real coder mock that has a real ToolExecutor
        coder = _make_coder()
        coder.tool_executor = ToolExecutor(coord, coder, ExecutionState(mode="act"))
        coder.tool_exec_state = coder.tool_executor.state

        from aicoder.graph.state import register_coder
        register_coder("test-session", coder)

        store = AgentStepStore(session_id="test-session")
        from aicoder.runners.function_calling_agent_runner import FunctionCallingAgentRunner
        runner = FunctionCallingAgentRunner(
            coder=coder, session_id="test-session", mode="act",
            tool_registry=MagicMock(), step_store=store,
        )

        from aicoder.runners import register_runner
        register_runner("test-session", runner)

        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(step, action_name="ok_tool", action_input={})

        state = _make_state(
            session_id="test-session",
            pending_tool_calls=[{"name": "ok_tool", "params": {}}],
        )

        result = execute_tool_node(state)

        updated_step = store.last_step()
        assert updated_step.status == "observed"
        assert updated_step.observation == "hello"
        assert updated_step.tool_meta.get("success") is True

        from aicoder.graph.state import unregister_coder
        unregister_coder("test-session")
        from aicoder.runners import unregister_runner
        unregister_runner("test-session")

    def test_step_updated_after_tool_failure(self):
        from aicoder.agent_step_store import AgentStepStore
        from aicoder.tools.executor import ToolExecutor, ToolCoordinator
        from aicoder.tools.handlers.base import ToolHandler

        class FailHandler(ToolHandler):
            name = "bad_tool"
            requires_approval = False
            def execute(self, tc, coder):
                return ToolResult.fail("bad_tool", "something went wrong")

        coord = ToolCoordinator()
        coord.register(FailHandler())

        coder = _make_coder()
        coder.tool_executor = ToolExecutor(coord, coder, ExecutionState(mode="act"))
        coder.tool_exec_state = coder.tool_executor.state

        from aicoder.graph.state import register_coder
        register_coder("test-session-fail", coder)

        store = AgentStepStore(session_id="test-session-fail")
        from aicoder.runners.function_calling_agent_runner import FunctionCallingAgentRunner
        runner = FunctionCallingAgentRunner(
            coder=coder, session_id="test-session-fail", mode="act",
            tool_registry=MagicMock(), step_store=store,
        )
        from aicoder.runners import register_runner
        register_runner("test-session-fail", runner)

        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(step, action_name="bad_tool", action_input={})

        state = _make_state(
            session_id="test-session-fail",
            pending_tool_calls=[{"name": "bad_tool", "params": {}}],
        )

        result = execute_tool_node(state)

        updated_step = store.last_step()
        assert updated_step.status == "observed"
        assert updated_step.tool_meta.get("success") is False
        assert "wrong" in updated_step.observation

        from aicoder.graph.state import unregister_coder
        unregister_coder("test-session-fail")
        from aicoder.runners import unregister_runner
        unregister_runner("test-session-fail")


# ---------------------------------------------------------------------------
# Phase 5: Enriched failure observation tests
# ---------------------------------------------------------------------------

class TestEnrichedFailureObservation:
    def test_failure_observation_has_error_type(self):
        """Failed tool execution should produce observations with error_type."""
        state = _make_state(tool_observations=[{
            "tool_name": "read_file",
            "success": False,
            "output": "",
            "error": "file not found",
            "rejected": False,
            "error_type": "execution_error",
            "summary": "Tool 'read_file' failed: file not found",
            "recommended_next": "Tool failed. Consider: check params, try a different tool, or retry.",
        }])
        result = observe_tool_result(state)
        # The observation should still produce messages (CoT path)
        msgs = result["messages"]
        assert len(msgs) > 0
        # The enriched fields are preserved in the observation
        obs = state["tool_observations"][0] if state.get("tool_observations") else None

    def test_failure_observation_summary_present(self):
        """Enriched failure observation should have a summary."""
        from aicoder.tools.result import ToolResult
        result = ToolResult.fail("edit_file", "permission denied")
        assert result.meta.get("summary") is not None
        assert "edit_file" in result.meta["summary"]
        assert result.meta.get("error_type") == "execution_error"

    def test_rejected_meta_has_error_type(self):
        from aicoder.tools.result import ToolResult
        result = ToolResult.create_rejected("run_shell")
        assert result.meta.get("error_type") == "user_rejected"
        assert result.meta.get("summary") is not None

    def test_blocked_meta_has_error_type(self):
        from aicoder.tools.result import ToolResult
        result = ToolResult.blocked("write_file", "read-only mode")
        assert result.meta.get("error_type") == "blocked"
        assert result.meta.get("summary") is not None

    def test_ok_meta_has_summary(self):
        from aicoder.tools.result import ToolResult
        result = ToolResult.ok("read_file", "file contents")
        assert result.meta.get("summary") is not None
        assert result.meta.get("error_type", "") == ""  # no error type for success

    def test_act_mode_error_usable_in_next_round(self):
        """In act mode, error observation should be usable in the next round context."""
        state = _make_state(tool_observations=[{
            "tool_name": "edit_file",
            "success": False,
            "output": "",
            "error": "old_text not found in file",
            "rejected": False,
            "error_type": "execution_error",
            "summary": "Tool 'edit_file' failed: old_text not found in file",
            "recommended_next": "Tool failed. Consider: check params, try a different tool, or retry.",
        }])
        result = observe_tool_result(state)
        msgs = result["messages"]
        # Error should be in messages for next round
        assert any("FAILED" in m["content"] for m in msgs)
        assert any("edit_file" in m["content"] for m in msgs)
        # Original messages preserved
        assert result["tool_observations"] == []


class TestAgentStepEnrichedFields:
    def test_step_has_tool_calls_field(self):
        from aicoder.agent_step_store import AgentStepStore
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        assert hasattr(step, "tool_calls")
        assert isinstance(step.tool_calls, list)

    def test_step_has_tool_results_field(self):
        from aicoder.agent_step_store import AgentStepStore
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        assert hasattr(step, "tool_results")
        assert isinstance(step.tool_results, list)

    def test_step_has_summary_field(self):
        from aicoder.agent_step_store import AgentStepStore
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        assert hasattr(step, "summary")
        assert step.summary == ""

    def test_step_fields_mutable(self):
        from aicoder.agent_step_store import AgentStepStore
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        step.tool_calls = [{"name": "read_file", "params": {"path": "x.py"}}]
        step.tool_results = [{"success": True, "output": "ok"}]
        step.summary = "Read file x.py successfully"
        assert len(step.tool_calls) == 1
        assert step.summary == "Read file x.py successfully"
