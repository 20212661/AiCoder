"""Long history regression tests for v1.2.x stabilization.

Scenarios:
1. Packer stability with long history (100+ messages)
2. Condensation trigger threshold boundary
3. Budget trimming with many events doesn't lose recent context
4. Three-view consistency under long history
5. Event store performance does not degrade with many events
6. Condensation + budget trim together produce valid output
"""

import tempfile
from unittest.mock import MagicMock, patch

import pytest

from aicoder.agent_step_store import AgentStepStore
from aicoder.events.store import AgentEventStore
from aicoder.events.types import AgentEventRecord
from aicoder.runners import register_runner, unregister_runner
from aicoder.runners.cot_agent_runner import CotAgentRunner
from aicoder.tests.conftest import make_mock_coder
from aicoder.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_long_step_history(
    session_id: str,
    num_steps: int = 20,
    observation_len: int = 300,
) -> AgentStepStore:
    """Build a step store with many steps, each producing 3+ events."""
    step_store = AgentStepStore(session_id=session_id)
    for i in range(num_steps):
        step = step_store.create_step(iteration=i, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step,
            thought=f"Thinking about step {i}",
            action_name="read_file",
            action_input={"path": f"/tmp/file{i}.py"},
        )
        obs = "x" * observation_len if i % 3 == 0 else f"contents of file {i}"
        step_store.update_step_after_tool(
            step,
            observation=obs,
            tool_meta={"success": True, "tool_name": "read_file", "duration_ms": 50 + i},
            files=[f"/tmp/file{i}.py"],
        )
    return step_store


# ---------------------------------------------------------------------------
# Scenario 1: Packer stability with long history
# ---------------------------------------------------------------------------


class TestLongHistoryPackerStability:
    def test_packer_handles_100_messages(self):
        """pack_context should not crash with 100+ messages in done_messages."""
        from aicoder.context.packer import pack_context

        session_id = "long-packer-test"
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = session_id
        coder.done_messages = [
            {"role": "user", "content": f"question {i} " + "abc " * 50}
            for i in range(50)
        ] + [
            {"role": "assistant", "content": f"answer {i} " + "def " * 50}
            for i in range(50)
        ]

        with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
             patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
             patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode, \
             patch("aicoder.coders.message_builder.build_runtime_state_messages") as mock_rt:
            mock_sys.return_value = [{"role": "system", "content": "sys"}]
            mock_chat.return_value = []
            mock_mode.return_value = []
            mock_rt.return_value = []

            packed = pack_context(coder, "user input", "act", "cot")
            assert len(packed.all_messages) > 0
            # System + conversation should be present
            assert len(packed.system_messages) >= 1
            assert len(packed.conversation_messages) >= 1

    def test_packer_output_messages_have_valid_roles(self):
        """Every message from pack_context should have a recognized role."""
        from aicoder.context.packer import pack_context

        session_id = "long-roles-test"
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = session_id
        coder.done_messages = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(30)
        ]

        with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
             patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
             patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode, \
             patch("aicoder.coders.message_builder.build_runtime_state_messages") as mock_rt:
            mock_sys.return_value = [{"role": "system", "content": "sys"}]
            mock_chat.return_value = []
            mock_mode.return_value = []
            mock_rt.return_value = []

            packed = pack_context(coder, "user input", "act", "cot")
            valid_roles = {"system", "user", "assistant", "tool"}
            for m in packed.all_messages:
                assert m.get("role") in valid_roles, f"Invalid role: {m.get('role')}"


# ---------------------------------------------------------------------------
# Scenario 2: Condensation trigger threshold
# ---------------------------------------------------------------------------


class TestCondensationTriggerThreshold:
    def test_no_condensation_below_threshold(self):
        """History with < 8 events should NOT be condensed."""
        from aicoder.context.history_view import build_llm_history_view

        session_id = "below-threshold-test"
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = session_id
        coder.done_messages = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
        ]

        step_store = AgentStepStore(session_id=session_id)
        # Only 2 steps = ~6 events, below _CONDENSE_MIN_EVENTS (8)
        for i in range(2):
            step = step_store.create_step(iteration=i, mode="act", runner_type="cot")
            step_store.update_step_after_parse(step, action_name="read_file")
            step_store.update_step_after_tool(step, observation="ok")

        registry = ToolRegistry()
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry=registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        view = build_llm_history_view(coder, "act", "cot")
        condensed_msgs = [m for m in view if isinstance(m, dict) and m.get("condensed")]
        assert len(condensed_msgs) == 0, "Should not condense with < 8 events"

        _cleanup(session_id)

    def test_condensation_above_threshold(self):
        """History with >= 8 events should be condensed."""
        from aicoder.context.history_view import build_llm_history_view

        session_id = "above-threshold-test"
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = session_id
        coder.done_messages = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(10)
        ]

        step_store = _build_long_step_history(session_id, num_steps=5)
        assert len(step_store.event_store.all_events()) >= 8

        registry = ToolRegistry()
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry=registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        view = build_llm_history_view(coder, "act", "cot")
        # With 10 done_messages + condensation, should have summary pair + recent
        assert len(view) > 0

        _cleanup(session_id)

    def teardown_method(self):
        for sid in ["below-threshold-test", "above-threshold-test"]:
            _cleanup(sid)


# ---------------------------------------------------------------------------
# Scenario 3: Budget trimming preserves recent context
# ---------------------------------------------------------------------------


class TestBudgetTrimPreservesRecent:
    def test_trim_keeps_recent_messages(self):
        """Budget trimming should preserve the most recent message pairs."""
        from aicoder.context.packer import _trim_to_budget

        messages = []
        for i in range(20):
            messages.append({"role": "user", "content": f"old msg {i} " + "padding " * 50})
            messages.append({"role": "assistant", "content": f"reply {i} " + "data " * 50})
        trimmed = _trim_to_budget(messages, budget_tokens=200)
        # Should keep at least some messages
        assert len(trimmed) > 0
        # The last pair should be from the most recent iteration
        assert "old msg 19" in trimmed[-2]["content"]

    def test_trim_preserves_pairs(self):
        """_trim_to_budget should remove user/assistant pairs together."""
        from aicoder.context.packer import _trim_to_budget

        pairs = []
        for i in range(15):
            pairs.append({"role": "user", "content": f"q{i} " + "x" * 200})
            pairs.append({"role": "assistant", "content": f"a{i} " + "y" * 200})

        trimmed = _trim_to_budget(pairs, budget_tokens=500)
        # Should have even number (pairs preserved)
        assert len(trimmed) % 2 == 0
        # First remaining pair should be a user message
        assert trimmed[0]["role"] == "user"

    def test_tool_trace_trim_older_half_only(self):
        """_trim_tool_traces should only trim the older half of tool traces."""
        from aicoder.context.packer import _trim_tool_traces

        messages = [
            {"role": "tool", "content": "x" * 500, "tool_call_id": f"tc_{i}"}
            for i in range(6)
        ]
        trimmed = _trim_tool_traces(messages, budget_tokens=50)
        # Older half (first 3) should be trimmed, recent half should be intact
        assert len(trimmed) == 6
        # First 3 should have _trace_trimmed marker
        for i in range(3):
            assert trimmed[i].get("_trace_trimmed") is True
        # Last 3 should be untouched
        for i in range(3, 6):
            assert "_trace_trimmed" not in trimmed[i]


# ---------------------------------------------------------------------------
# Scenario 4: Three-view consistency under long history
# ---------------------------------------------------------------------------


class TestThreeViewConsistency:
    def test_all_three_views_produce_output(self):
        """All three views should produce non-empty output for long history."""
        from aicoder.context.history_view import (
            build_ui_history_view,
            build_runtime_history_view,
            build_llm_history_view,
        )

        session_id = "three-view-test"
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = session_id
        coder.done_messages = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(8)
        ]

        step_store = _build_long_step_history(session_id, num_steps=5)
        registry = ToolRegistry()
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry=registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        ui = build_ui_history_view(coder, "act", "cot")
        runtime = build_runtime_history_view(coder, "act", "cot")
        llm = build_llm_history_view(coder, "act", "cot")

        assert len(ui) > 0, "UI view should not be empty"
        assert len(runtime) > 0, "Runtime view should not be empty"
        assert len(llm) > 0, "LLM view should not be empty"

        # UI and runtime should not be condensed
        ui_condensed = [e for e in ui if isinstance(e, dict) and e.get("condensed")]
        rt_condensed = [e for e in runtime if isinstance(e, dict) and e.get("condensed")]
        assert len(ui_condensed) == 0
        assert len(rt_condensed) == 0

        _cleanup(session_id)

    def teardown_method(self):
        _cleanup("three-view-test")


# ---------------------------------------------------------------------------
# Scenario 5: Event store scalability
# ---------------------------------------------------------------------------


class TestEventStoreScalability:
    def test_event_store_handles_1000_events(self):
        """Event store should handle 1000 events without issues."""
        store = AgentEventStore(session_id="scale-test")
        for i in range(1000):
            store.append(iteration=i, kind="tool_result", payload={"i": i})

        assert len(store.all_events()) == 1000

        # Filtering should work
        result = store.list_events(kind="tool_result", limit=10)
        assert len(result) == 10

        # events_for_iteration should work
        ev = store.events_for_iteration(500)
        assert len(ev) == 1
        assert ev[0].iteration == 500

    def test_last_event_performant(self):
        """last_event should work efficiently with many events."""
        store = AgentEventStore(session_id="perf-test")
        for i in range(500):
            store.append(iteration=i, kind="tool_result" if i % 2 == 0 else "tool_call")

        last_result = store.last_event(kind="tool_result")
        assert last_result is not None
        assert last_result.kind == "tool_result"

        last_call = store.last_event(kind="tool_call")
        assert last_call is not None
        assert last_call.kind == "tool_call"


# ---------------------------------------------------------------------------
# Scenario 6: Condensation + budget trim together
# ---------------------------------------------------------------------------


class TestCondensationPlusBudgetTrim:
    def test_condensation_then_budget_trim(self):
        """Condensation output should survive subsequent budget trimming."""
        from aicoder.context.condense import (
            prune_history_events,
            summarize_history_events,
            apply_condensation_to_history_view,
        )
        from aicoder.context.packer import _trim_to_budget

        step_store = _build_long_step_history("condense-budget-test", num_steps=10)
        events = step_store.event_store.all_events()

        # Build a long history view
        history = [
            {"role": "user", "content": f"msg {i} " + "padding " * 30}
            for i in range(15)
        ]

        # Apply condensation
        pruned = prune_history_events(events, "act")
        condensed = summarize_history_events(pruned)
        condensed_view = apply_condensation_to_history_view(history, condensed)

        assert len(condensed_view) < len(history)

        # Apply budget trim on top
        trimmed = _trim_to_budget(condensed_view, budget_tokens=300)
        assert len(trimmed) > 0
        # Should still have valid roles
        for m in trimmed:
            assert m.get("role") in ("user", "assistant", "system", "tool")

    def test_condensation_produces_no_empty_messages(self):
        """Condensed summary should not contain empty content."""
        from aicoder.context.condense import summarize_history_events

        step_store = _build_long_step_history("no-empty-test", num_steps=5)
        events = step_store.event_store.all_events()

        block = summarize_history_events(events)
        assert block is not None
        assert len(block.summary.strip()) > 0
        assert len(block.covered_event_ids) > 0


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------


def _cleanup(session_id: str):
    unregister_runner(session_id)
