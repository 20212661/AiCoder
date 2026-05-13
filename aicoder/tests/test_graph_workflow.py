"""Tests for graph workflow topology, compilation, and routing logic."""
from __future__ import annotations

from unittest.mock import MagicMock

from aicoder.graph.state import AgentGraphState, register_coder
from aicoder.graph.workflow import build_agent_graph
from aicoder.graph.nodes import (
    route_after_model,
    route_after_observe,
    route_after_permission,
    route_after_verify,
    route_mode,
)


class TestGraphCompilation:
    def test_graph_compiles(self):
        graph = build_agent_graph()
        assert graph is not None

    def test_graph_compiles_with_checkpointer(self, tmp_path):
        from aicoder.graph.checkpointer import get_checkpointer
        cp = get_checkpointer(db_path=tmp_path / "test.db")
        graph = build_agent_graph(checkpointer=cp)
        assert graph is not None

    def test_all_nodes_registered(self):
        graph = build_agent_graph()
        nodes = list(graph.nodes.keys())
        expected = [
            "prepare_context",
            "plan",
            "request_plan_approval",
            "model",
            "parse_tool_calls",
            "permission",
            "execute_tool",
            "verify",
            "observe_tool_result",
            "summarize",
        ]
        for name in expected:
            assert name in nodes, f"Missing node: {name}"

    def test_entry_point_is_prepare_context(self):
        graph = build_agent_graph()
        # The first node in the execution should be prepare_context
        assert "prepare_context" in graph.nodes


class TestRouteMode:
    def test_plan_mode_routes_to_model(self):
        state = {"mode": "plan"}
        assert route_mode(state) == "model"

    def test_act_mode_routes_to_model(self):
        state = {"mode": "act"}
        assert route_mode(state) == "model"

    def test_sniff_mode_routes_to_model(self):
        state = {"mode": "sniff"}
        assert route_mode(state) == "model"

    def test_default_routes_to_model(self):
        state = {"mode": "default"}
        assert route_mode(state) == "model"

    def test_empty_mode_routes_to_model(self):
        state = {}
        assert route_mode(state) == "model"


class TestRouteAfterModel:
    def test_tools_present_routes_to_tools(self):
        state = {
            "pending_tool_calls": [{"name": "read_file", "params": {}}],
            "loop_count": 1,
            "max_loops": 5,
        }
        assert route_after_model(state) == "tools"

    def test_no_tools_routes_to_finish(self):
        state = {
            "pending_tool_calls": [],
            "loop_count": 1,
            "max_loops": 5,
        }
        assert route_after_model(state) == "finish"

    def test_exceeded_max_loops_routes_to_finish(self):
        state = {
            "pending_tool_calls": [{"name": "read_file", "params": {}}],
            "loop_count": 6,
            "max_loops": 5,
        }
        assert route_after_model(state) == "finish"

    def test_too_many_errors_routes_to_finish(self):
        coder = MagicMock()
        coder.tool_exec_state.too_many_errors = True
        register_coder("test-session", coder)
        state = {
            "session_id": "test-session",
            "pending_tool_calls": [{"name": "read_file", "params": {}}],
            "loop_count": 1,
            "max_loops": 5,
        }
        assert route_after_model(state) == "finish"


class TestRouteAfterPermission:
    def test_approved_tools_route_to_execute(self):
        state = {
            "pending_tool_calls": [{"name": "read_file", "params": {}}],
        }
        assert route_after_permission(state) == "execute"

    def test_all_denied_route_to_deny(self):
        state = {
            "pending_tool_calls": [],
        }
        assert route_after_permission(state) == "deny"

    def test_empty_pending_route_to_deny(self):
        state = {}
        assert route_after_permission(state) == "deny"


class TestRouteAfterObserve:
    def test_under_limit_routes_to_continue(self):
        state = {
            "loop_count": 2,
            "max_loops": 5,
        }
        assert route_after_observe(state) == "continue"

    def test_at_limit_routes_to_finish(self):
        state = {
            "loop_count": 5,
            "max_loops": 5,
        }
        assert route_after_observe(state) == "finish"

    def test_over_limit_routes_to_finish(self):
        state = {
            "loop_count": 6,
            "max_loops": 5,
        }
        assert route_after_observe(state) == "finish"

    def test_too_many_errors_routes_to_finish(self):
        coder = MagicMock()
        coder.tool_exec_state.too_many_errors = True
        register_coder("test-session", coder)
        state = {
            "session_id": "test-session",
            "loop_count": 1,
            "max_loops": 5,
        }
        assert route_after_observe(state) == "finish"


class TestPlanPath:
    def test_plan_path_completes(self, tmp_path):
        """Plan mode should produce a plan without executing tools."""
        from aicoder.tests.conftest import make_graph_coder, invoke_graph

        coder = make_graph_coder(
            responses=["Here is my plan:\n1. Read files\n2. Analyze"],
            mode="plan",
            root=str(tmp_path),
        )
        result = invoke_graph(coder, "Analyze this project", mode="plan")

        assert result["phase"] == "done"
        assert result.get("current_plan") or result.get("final_response")


class TestActPathTermination:
    def test_act_path_text_only_terminates(self, tmp_path):
        """Act mode with no tool calls should terminate in one loop."""
        from aicoder.tests.conftest import make_graph_coder, invoke_graph

        coder = make_graph_coder(
            responses=["Just a text answer."],
            root=str(tmp_path),
        )
        result = invoke_graph(coder, "Say hello")

        assert result["phase"] == "done"
        assert result["loop_count"] == 1


class TestRouteAfterVerify:
    def test_no_decisions_routes_to_continue(self):
        state = {"recovery_decisions": []}
        assert route_after_verify(state) == "continue"

    def test_empty_state_routes_to_continue(self):
        state = {}
        assert route_after_verify(state) == "continue"

    def test_retry_routes_to_continue(self):
        state = {
            "recovery_decisions": [
                {"action": "retry", "reason": "verification failed", "next_hint": "try a different approach"},
            ],
        }
        assert route_after_verify(state) == "continue"

    def test_fallback_routes_to_continue(self):
        state = {
            "recovery_decisions": [
                {"action": "fallback", "reason": "non-retryable error", "next_hint": "use alternative tool"},
            ],
        }
        assert route_after_verify(state) == "continue"

    def test_halt_routes_to_halt(self):
        state = {
            "recovery_decisions": [
                {"action": "retry", "reason": "verification failed", "next_hint": "retry"},
                {"action": "halt", "reason": "max retries exceeded", "next_hint": ""},
            ],
        }
        assert route_after_verify(state) == "halt"

    def test_mixed_decisions_with_halt_routes_to_halt(self):
        state = {
            "recovery_decisions": [
                {"action": "retry", "reason": "first failure", "next_hint": "retry"},
                {"action": "retry", "reason": "second failure", "next_hint": "retry again"},
                {"action": "halt", "reason": "budget exhausted", "next_hint": ""},
            ],
        }
        assert route_after_verify(state) == "halt"

    def test_graph_compiles_with_conditional_verify_edge(self):
        """Verify the graph compiles with the new conditional verify->observe edge."""
        graph = build_agent_graph()
        assert graph is not None
