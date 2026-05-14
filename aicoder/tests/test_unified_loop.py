"""Tests for unified three-mode loop (Phase 4) + Fix 1 (mode-specific routing)."""
import pytest
from unittest.mock import MagicMock, patch

from aicoder.graph.nodes import (
    route_mode,
    route_after_model,
    route_after_observe,
    should_finish_for_mode,
)
from aicoder.graph.state import register_coder
from aicoder.tests.conftest import make_graph_coder, invoke_graph


# ---------------------------------------------------------------------------
# Route mode
# ---------------------------------------------------------------------------

class TestUnifiedRouteMode:
    def test_all_modes_go_to_model(self):
        for mode in ("sniff", "plan", "act"):
            assert route_mode({"mode": mode}) == "model"

    def test_unknown_mode_goes_to_model(self):
        assert route_mode({"mode": "unknown"}) == "model"

    def test_empty_mode_goes_to_model(self):
        assert route_mode({}) == "model"


# ---------------------------------------------------------------------------
# should_finish_for_mode
# ---------------------------------------------------------------------------

class TestShouldFinishForMode:
    def test_sniff_finishes_without_tools(self):
        assert should_finish_for_mode({"mode": "sniff", "pending_tool_calls": []}) is True

    def test_plan_finishes_without_tools(self):
        assert should_finish_for_mode({"mode": "plan", "pending_tool_calls": []}) is True

    def test_act_does_not_force_finish_without_tools(self):
        assert should_finish_for_mode({"mode": "act", "pending_tool_calls": []}) is False

    def test_sniff_continues_with_tools(self):
        assert should_finish_for_mode({
            "mode": "sniff",
            "pending_tool_calls": [{"name": "read_file"}],
        }) is False

    def test_plan_continues_with_tools(self):
        assert should_finish_for_mode({
            "mode": "plan",
            "pending_tool_calls": [{"name": "read_file"}],
        }) is False

    def test_act_continues_with_tools(self):
        assert should_finish_for_mode({
            "mode": "act",
            "pending_tool_calls": [{"name": "edit_file"}],
        }) is False


# ---------------------------------------------------------------------------
# Integration: plan mode can execute read-only tools
# ---------------------------------------------------------------------------

class TestPlanModeReadOnlyLoop:
    def test_plan_mode_can_execute_read_only_tools(self, tmp_path):
        """Plan mode should be able to loop with read_file and produce output."""
        from aicoder.tests.conftest import make_tool_call_xml

        # First response: call read_file; Second response: final plan
        coder = make_graph_coder(
            responses=[
                f"Let me read the file.\n{make_tool_call_xml('read_file', path='main.py')}",
                "Based on my analysis, here is the plan:\n1. Refactor module X",
            ],
            mode="plan",
            root=str(tmp_path),
        )
        result = invoke_graph(coder, "Analyze main.py", mode="plan", max_loops=5)

        # Should complete (not crash), and should have a final response
        assert result["phase"] == "done"

    def test_plan_mode_still_denies_edit_tools(self, tmp_path):
        """Plan mode must deny edit_file even in the unified loop."""
        coder = make_graph_coder(
            responses=["I will edit this file now."],
            mode="plan",
            root=str(tmp_path),
        )
        # Even though we send a text-only response (no tool calls),
        # the permission system should still deny edits
        from aicoder.permission_modes import can_use_tool_in_mode, ToolPermissionContext
        from aicoder.approval import ApprovalController

        decision = can_use_tool_in_mode(
            "edit_file",
            {"path": "main.py"},
            ToolPermissionContext(mode="plan"),
            ApprovalController(),
        )
        assert decision.behavior == "deny"


# ---------------------------------------------------------------------------
# Integration: sniff mode uses same loop but read-only
# ---------------------------------------------------------------------------

class TestSniffModeReadOnlyLoop:
    def test_sniff_mode_uses_same_loop_but_read_only(self, tmp_path):
        """Sniff mode should go through model loop and produce output."""
        coder = make_graph_coder(
            responses=["I investigated the project. Here's what I found: ..."],
            mode="sniff",
            root=str(tmp_path),
        )
        result = invoke_graph(coder, "Look around", mode="sniff")

        assert result["phase"] == "done"
        assert result.get("final_response")

    def test_sniff_mode_denies_edits(self):
        from aicoder.permission_modes import can_use_tool_in_mode, ToolPermissionContext
        from aicoder.approval import ApprovalController

        decision = can_use_tool_in_mode(
            "write_file",
            {"path": "x.py", "content": "bad"},
            ToolPermissionContext(mode="sniff"),
            ApprovalController(),
        )
        assert decision.behavior == "deny"


# ---------------------------------------------------------------------------
# Integration: plan mode no longer short-circuits
# ---------------------------------------------------------------------------

class TestPlanModeNoShortCircuit:
    def test_plan_mode_no_longer_short_circuits_to_single_answer(self):
        """route_mode must return 'model' for plan — no special plan path."""
        assert route_mode({"mode": "plan"}) == "model"

    def test_plan_mode_goes_through_model_node(self, tmp_path):
        """Plan mode must produce output through the shared model loop, not plan_node."""
        coder = make_graph_coder(
            responses=["My analysis plan:\n1. Read\n2. Analyze"],
            mode="plan",
            root=str(tmp_path),
        )
        result = invoke_graph(coder, "What should we do?", mode="plan")

        # Should have loop_count (model_node was called, not plan_node)
        assert result.get("loop_count") is not None
        assert result["phase"] == "done"


# ---------------------------------------------------------------------------
# Integration: act mode no regression
# ---------------------------------------------------------------------------

class TestActModeNoRegression:
    def test_act_mode_still_works(self, tmp_path):
        coder = make_graph_coder(
            responses=["I'll do it!"],
            mode="act",
            root=str(tmp_path),
        )
        result = invoke_graph(coder, "Do something", mode="act")
        assert result["phase"] == "done"


# ---------------------------------------------------------------------------
# Fix 1: mode-specific route after model / route after observe
# ---------------------------------------------------------------------------

class TestModeSpecificRouteAfterModel:
    """route_after_model must use should_finish_for_mode."""

    def test_sniff_no_tools_finishes(self):
        state = {"mode": "sniff", "pending_tool_calls": [], "loop_count": 1, "max_loops": 5}
        assert route_after_model(state) == "finish"

    def test_plan_no_tools_finishes(self):
        state = {"mode": "plan", "pending_tool_calls": [], "loop_count": 1, "max_loops": 5}
        assert route_after_model(state) == "finish"

    def test_act_no_tools_finishes(self):
        """act with no tools also finishes (standard no-tool behaviour)."""
        state = {"mode": "act", "pending_tool_calls": [], "loop_count": 1, "max_loops": 5}
        assert route_after_model(state) == "finish"

    def test_sniff_with_tools_goes_to_tools(self):
        state = {
            "mode": "sniff",
            "pending_tool_calls": [{"name": "read_file", "params": {}}],
            "loop_count": 1,
            "max_loops": 5,
        }
        assert route_after_model(state) == "tools"

    def test_plan_with_tools_goes_to_tools(self):
        state = {
            "mode": "plan",
            "pending_tool_calls": [{"name": "read_file", "params": {}}],
            "loop_count": 1,
            "max_loops": 5,
        }
        assert route_after_model(state) == "tools"

    def test_act_with_tools_goes_to_tools(self):
        state = {
            "mode": "act",
            "pending_tool_calls": [{"name": "edit_file", "params": {}}],
            "loop_count": 1,
            "max_loops": 5,
        }
        assert route_after_model(state) == "tools"

    def test_too_many_errors_overrides_mode(self):
        coder = MagicMock()
        coder.tool_exec_state.too_many_errors = True
        register_coder("fix1-err", coder)
        state = {
            "session_id": "fix1-err",
            "mode": "act",
            "pending_tool_calls": [{"name": "read_file", "params": {}}],
            "loop_count": 1,
            "max_loops": 5,
        }
        assert route_after_model(state) == "finish"


class TestModeSpecificRouteAfterObserve:
    """route_after_observe must respect mode semantics."""

    def test_sniff_continues_after_observe_to_synthesize(self):
        """After observing read-only tool results, sniff gets one more model call."""
        state = {"mode": "sniff", "loop_count": 1, "max_loops": 5}
        assert route_after_observe(state) == "continue"

    def test_plan_continues_after_observe_to_synthesize(self):
        """After observing read-only tool results, plan gets one more model call."""
        state = {"mode": "plan", "loop_count": 1, "max_loops": 5}
        assert route_after_observe(state) == "continue"

    def test_act_continues_after_observe(self):
        state = {"mode": "act", "loop_count": 1, "max_loops": 5}
        assert route_after_observe(state) == "continue"

    def test_max_loops_overrides_mode(self):
        state = {"mode": "sniff", "loop_count": 5, "max_loops": 5}
        assert route_after_observe(state) == "finish"

    def test_too_many_errors_overrides_observe(self):
        coder = MagicMock()
        coder.tool_exec_state.too_many_errors = True
        register_coder("fix1-obs-err", coder)
        state = {
            "session_id": "fix1-obs-err",
            "mode": "act",
            "loop_count": 1,
            "max_loops": 5,
        }
        assert route_after_observe(state) == "finish"
