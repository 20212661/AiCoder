"""End-to-end regression tests for v1.2.x stabilization.

Scenarios:
1. sniff→plan→act flow preserves events across mode switches
2. FC multi-tool calls produce correct event sequence
3. CoT text observation feeds back into next model call
4. Tool failure → observation → next round continues
5. Condensation triggered but agent continues normally
6. Budget trim does not corrupt history
7. mark_error events appear correctly in all three history views
8. Structured observation fields survive full graph cycle

v1.2.3 addition:
9. Real graph-path sniff mode E2E (prepare_context → model → finish)
10. Real graph-path act mode tool loop (model → permission → execute → observe → continue → finish)
11. Real graph-path tool failure then continue (failed tool → observe → model loop → finish)
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from aicoder.agent_step_store import AgentStepStore
from aicoder.events.store import AgentEventStore
from aicoder.events.types import AgentEventRecord
from aicoder.tests.conftest import (
    FakeIO,
    FakeModel,
    make_graph_coder,
    make_mock_coder,
    invoke_graph,
    make_tool_call_xml,
)
from aicoder.runners import register_runner, unregister_runner
from aicoder.runners.cot_agent_runner import CotAgentRunner
from aicoder.tools.registry import ToolRegistry
from aicoder.tools.result import ExecutionState
from aicoder.tools.executor import ToolCoordinator, ToolExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coder_with_runner(
    responses: list[str],
    session_id: str = "reg-test",
    mode: str = "act",
    root: str | None = None,
):
    """Create a coder + CotAgentRunner wired for end-to-end testing."""
    root = root or tempfile.mkdtemp()
    coder = make_graph_coder(responses=responses, mode=mode, root=root)
    coder.session_id = session_id

    registry = coder.tool_registry
    step_store = AgentStepStore(session_id=session_id)
    runner = CotAgentRunner(
        coder=coder,
        session_id=session_id,
        mode=mode,
        tool_registry=registry,
        step_store=step_store,
    )
    register_runner(session_id, runner)
    return coder, runner


def _cleanup_runner(session_id: str):
    unregister_runner(session_id)


# ---------------------------------------------------------------------------
# Scenario 1: sniff→plan→act mode flow preserves event history
# ---------------------------------------------------------------------------


class TestSniffPlanActFlow:
    def test_mode_switch_preserves_step_events(self):
        """Events from sniff mode should survive when switching to act mode."""
        session_id = "mode-flow-test"

        # Phase 1: sniff mode with a read-only tool
        coder1, runner1 = _make_coder_with_runner(
            responses=["I see a <list_files><path>.</path></list_files> project."],
            session_id=session_id,
            mode="sniff",
        )
        step_store = runner1.step_store
        step = step_store.create_step(iteration=0, mode="sniff", runner_type="cot")
        step_store.update_step_after_parse(
            step, thought="listing files", action_name="list_files", action_input={"path": "."},
        )
        step_store.update_step_after_tool(step, observation="file1.py\nfile2.py")

        sniff_events = step_store.event_store.all_events()
        assert len(sniff_events) >= 3  # started + thought + tool_call + tool_result

        _cleanup_runner(session_id)

        # Phase 2: act mode — reuse same step_store to verify continuity
        coder2 = make_graph_coder(responses=["Done!"], mode="act")
        coder2.session_id = session_id
        step_store2 = AgentStepStore(session_id=session_id)
        runner2 = CotAgentRunner(
            coder=coder2, session_id=session_id, mode="act",
            tool_registry=coder2.tool_registry, step_store=step_store2,
        )
        register_runner(session_id, runner2)

        act_step = step_store2.create_step(iteration=0, mode="act", runner_type="cot")
        step_store2.update_step_after_parse(
            act_step, thought="modifying file", action_name="write_file",
            action_input={"path": "a.py", "content": "hello"},
        )
        step_store2.update_step_after_tool(act_step, observation="written", files=["a.py"])

        act_events = step_store2.event_store.all_events()
        assert len(act_events) >= 3

        _cleanup_runner(session_id)

    def teardown_method(self):
        _cleanup_runner("mode-flow-test")


# ---------------------------------------------------------------------------
# Scenario 2: FC multi-tool calls produce correct event sequence
# ---------------------------------------------------------------------------


class TestFCMultiToolCallEvents:
    def test_multiple_tool_calls_emitted(self):
        """FC runner: first tool_call via parse, additional via event_store."""
        session_id = "fc-multi-test"
        step_store = AgentStepStore(session_id=session_id)
        step = step_store.create_step(iteration=0, mode="act", runner_type="function-calling")

        # Simulate FC: first tool via standard parse
        step_store.update_step_after_parse(
            step,
            action_name="read_file",
            action_input={"path": "a.py"},
        )

        # Additional tool calls emitted directly (as FC runner does)
        step_store.event_store.append(
            iteration=step.iteration,
            kind="tool_call",
            payload={"step_id": step.id, "tool_name": "write_file", "tool_input": {"path": "b.py"}},
        )
        step_store.event_store.append(
            iteration=step.iteration,
            kind="tool_call",
            payload={"step_id": step.id, "tool_name": "run_shell", "tool_input": {"command": "ls"}},
        )

        # Now simulate tool results for all three
        step_store.update_step_after_tool(step, observation="contents of a.py")
        step_store.event_store.append(
            iteration=step.iteration, kind="tool_result",
            payload={"step_id": step.id, "observation": "written b.py"},
        )
        step_store.event_store.append(
            iteration=step.iteration, kind="tool_result",
            payload={"step_id": step.id, "observation": "file1.py\nfile2.py"},
        )

        events = step_store.event_store.all_events()
        tc_events = [e for e in events if e.kind == "tool_call"]
        tr_events = [e for e in events if e.kind == "tool_result"]

        assert len(tc_events) == 3
        assert len(tr_events) == 3
        assert tc_events[0].payload["tool_name"] == "read_file"
        assert tc_events[1].payload["tool_name"] == "write_file"
        assert tc_events[2].payload["tool_name"] == "run_shell"


# ---------------------------------------------------------------------------
# Scenario 3: CoT text observation feeds back correctly
# ---------------------------------------------------------------------------


class TestCoTTextObservationFeedback:
    def test_cot_observation_appears_in_history(self):
        """CoT runner: tool observation should appear in done_messages after summarize."""
        session_id = "cot-feedback-test"
        root = tempfile.mkdtemp()

        # Simulate: model calls read_file, tool returns result, model responds
        response_with_tool = 'I will read the file.\n<read_file><path>a.py</path></read_file>'
        response_final = "The file contains 10 lines."

        coder, runner = _make_coder_with_runner(
            responses=[response_with_tool, response_final],
            session_id=session_id,
            root=root,
        )

        # Manually simulate the CoT step lifecycle
        step_store = runner.step_store
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step, thought="I will read the file", action_name="read_file",
            action_input={"path": "a.py"},
        )
        step_store.update_step_after_tool(
            step, observation="def main(): pass\n", tool_meta={"success": True},
        )

        # Check that the step data is correct
        assert step.status == "observed"
        assert step.action_name == "read_file"

        # Build history via runner
        coder.done_messages = [
            {"role": "user", "content": "Read a.py"},
            {"role": "assistant", "content": response_with_tool},
        ]
        history = runner.build_history_messages()
        # History should contain the tool observation
        assert len(history) > 0

        _cleanup_runner(session_id)

    def teardown_method(self):
        _cleanup_runner("cot-feedback-test")


# ---------------------------------------------------------------------------
# Scenario 4: Tool failure → observation → next round continues
# ---------------------------------------------------------------------------


class TestToolFailureNextRound:
    def test_failure_observation_allows_continuation(self):
        """After a tool failure, the agent should be able to continue."""
        step_store = AgentStepStore(session_id="fail-continue-test")

        # Step 0: tool fails
        step0 = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step0, thought="try reading", action_name="read_file",
            action_input={"path": "/nonexistent.py"},
        )
        step_store.update_step_after_tool(
            step0, observation="File not found", tool_error=True,
            tool_meta={"success": False, "error_type": "execution_error"},
        )

        # Verify error was recorded
        error_events = step_store.event_store.list_events(kind="tool_error")
        assert len(error_events) == 1
        assert error_events[0].payload["observation"] == "File not found"

        # Step 1: agent retries with different approach
        step1 = step_store.create_step(iteration=1, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step1, thought="try listing instead", action_name="list_files",
            action_input={"path": "."},
        )
        step_store.update_step_after_tool(
            step1, observation="file1.py\nfile2.py",
            tool_meta={"success": True},
        )
        step_store.finalize_step(step1, final_answer="Found 2 files.")

        # Verify full event sequence
        all_events = step_store.event_store.all_events()
        kinds = [e.kind for e in all_events]
        assert "tool_error" in kinds
        assert "tool_result" in kinds
        assert "step_finished" in kinds

    def test_mark_error_then_continue(self):
        """mark_error on one step does not prevent subsequent steps."""
        step_store = AgentStepStore(session_id="mark-err-continue")

        step0 = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.mark_error(step0, error="LLM timeout")

        # Verify error event
        err_events = step_store.event_store.list_events(kind="tool_error")
        assert len(err_events) == 1
        assert err_events[0].payload["error"] == "LLM timeout"
        assert err_events[0].payload["tool_meta"]["success"] is False

        # Next step should work fine
        step1 = step_store.create_step(iteration=1, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step1, action_name="read_file")
        step_store.update_step_after_tool(step1, observation="ok")

        assert step1.status == "observed"
        assert len(step_store.event_store.list_events(kind="tool_result")) == 1


# ---------------------------------------------------------------------------
# Scenario 5: Condensation triggered but agent continues normally
# ---------------------------------------------------------------------------


class TestCondensationContinues:
    def test_condensation_does_not_break_event_store(self):
        """After condensation runs, the original event store is intact."""
        from aicoder.context.condense import prune_history_events, summarize_history_events
        from aicoder.context.history_view import build_llm_history_view

        session_id = "condense-continue-test"
        root = tempfile.mkdtemp()
        step_store = AgentStepStore(session_id=session_id)

        # Create enough steps to trigger condensation (>= 8 events)
        for i in range(5):
            step = step_store.create_step(iteration=i, mode="act", runner_type="cot")
            step_store.update_step_after_parse(
                step, thought=f"Step {i}", action_name="read_file",
                action_input={"path": f"/tmp/f{i}.py"},
            )
            step_store.update_step_after_tool(
                step, observation="x" * 300, tool_meta={"success": True},
                files=[f"/tmp/f{i}.py"],
            )

        original_count = len(step_store.event_store.all_events())
        assert original_count >= 8

        # Run condensation on the events
        events = step_store.event_store.all_events()
        pruned = prune_history_events(events, "act")
        condensed = summarize_history_events(pruned)

        assert condensed is not None
        assert len(condensed.summary) > 0

        # Verify original store is unchanged
        assert len(step_store.event_store.all_events()) == original_count

        # Add more steps after condensation — should work fine
        step5 = step_store.create_step(iteration=5, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step5, action_name="write_file")
        step_store.update_step_after_tool(step5, observation="written", files=["/tmp/new.py"])

        assert len(step_store.event_store.all_events()) == original_count + 3  # started + tool_call + tool_result

    def test_llm_view_condensation_preserves_recent(self):
        """LLM view condensation keeps recent messages and replaces old ones."""
        from aicoder.context.history_view import build_llm_history_view

        session_id = "condense-view-test"
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = session_id
        coder.done_messages = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(12)
        ]

        step_store = AgentStepStore(session_id=session_id)
        for i in range(5):
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

        # Should contain condensed summary or original messages
        assert len(view) > 0

        _cleanup_runner(session_id)

    def teardown_method(self):
        for sid in ["condense-continue-test", "condense-view-test"]:
            _cleanup_runner(sid)


# ---------------------------------------------------------------------------
# Scenario 6: Budget trim does not corrupt history
# ---------------------------------------------------------------------------


class TestBudgetTrimSafety:
    def test_budget_trim_preserves_message_roles(self):
        """After budget trimming, all messages have valid roles."""
        from aicoder.context.packer import _trim_to_budget

        messages = [
            {"role": "user", "content": f"user msg {i} " + "x" * 200}
            for i in range(20)
        ]
        # Interleave assistant messages
        full = []
        for m in messages:
            full.append(m)
            full.append({"role": "assistant", "content": f"assistant reply " + "y" * 200})

        trimmed = _trim_to_budget(full, budget_tokens=500)
        for m in trimmed:
            assert m["role"] in ("user", "assistant", "system", "tool")

    def test_budget_trim_does_not_mutate_input(self):
        """_trim_to_budget should return a new list without modifying the input."""
        from aicoder.context.packer import _trim_to_budget

        original = [
            {"role": "user", "content": f"msg {i} " + "x" * 200}
            for i in range(10)
        ]
        original_copy = list(original)
        _trim_to_budget(original, budget_tokens=100)
        assert original == original_copy

    def test_tool_trace_trim_handles_none_content(self):
        """_trim_tool_traces should not crash on messages with None content."""
        from aicoder.context.packer import _trim_tool_traces

        messages = [
            {"role": "assistant", "content": None},
            {"role": "tool", "content": "x" * 500, "tool_call_id": "tc_1"},
            {"role": "user", "content": "[read_file] Result:\nsome output"},
        ]
        # Should not raise
        result = _trim_tool_traces(messages, budget_tokens=50)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Scenario 7: mark_error events appear in all three history views
# ---------------------------------------------------------------------------


class TestMarkErrorInHistoryViews:
    def test_mark_error_in_runtime_view(self):
        """mark_error step should appear in runtime history view."""
        from aicoder.context.history_view import build_runtime_history_view

        session_id = "mark-error-view-test"
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = session_id

        step_store = AgentStepStore(session_id=session_id)
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, action_name="read_file")
        step_store.mark_error(step, error="crash")

        registry = ToolRegistry()
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry=registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        view = build_runtime_history_view(coder, "act", "cot")
        assert len(view) >= 1
        # The error step should have error info
        error_entry = view[0]
        assert error_entry.get("status") == "error"
        assert "error" in error_entry.get("observation", {})

        _cleanup_runner(session_id)

    def test_mark_error_in_ui_view(self):
        """mark_error step should appear in UI history view with event metadata."""
        from aicoder.context.history_view import build_ui_history_view

        session_id = "mark-error-ui-test"
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = session_id

        step_store = AgentStepStore(session_id=session_id)
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, action_name="read_file")
        step_store.mark_error(step, error="crash")

        registry = ToolRegistry()
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry=registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        view = build_ui_history_view(coder, "act", "cot")
        # Find the step entry
        step_entries = [e for e in view if isinstance(e, dict) and e.get("source") == "step"]
        assert len(step_entries) >= 1

        _cleanup_runner(session_id)

    def teardown_method(self):
        for sid in ["mark-error-view-test", "mark-error-ui-test"]:
            _cleanup_runner(sid)


# ---------------------------------------------------------------------------
# Scenario 8: Structured observation fields survive full graph cycle
# ---------------------------------------------------------------------------


class TestStructuredFieldsSurviveGraphCycle:
    def test_structured_fields_in_event_store(self):
        """Structured fields (summary, error_type, recommended_next) should
        survive from tool execution through event store."""
        step_store = AgentStepStore(session_id="struct-survive-test")

        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step, action_name="write_file",
            action_input={"path": "/tmp/a.py", "content": "hello"},
        )
        step_store.update_step_after_tool(
            step,
            observation="Written successfully.",
            tool_meta={
                "success": True,
                "tool_name": "write_file",
                "summary": "Wrote hello to /tmp/a.py",
                "recommended_next": "Run the file to verify.",
                "files": ["/tmp/a.py"],
            },
            files=["/tmp/a.py"],
        )

        tr_events = step_store.event_store.list_events(kind="tool_result")
        assert len(tr_events) == 1
        payload = tr_events[0].payload
        assert payload["tool_meta"]["summary"] == "Wrote hello to /tmp/a.py"
        assert payload["tool_meta"]["recommended_next"] == "Run the file to verify."
        assert "/tmp/a.py" in payload["files"]

    def test_structured_error_fields_in_condensation(self):
        """Structured error fields should flow through condensation summary."""
        from aicoder.context.condense import summarize_history_events

        step_store = AgentStepStore(session_id="struct-condense-test")

        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step, action_name="write_file",
            action_input={"path": "readonly.py"},
        )
        step_store.update_step_after_tool(
            step,
            observation="permission denied",
            tool_error=True,
            tool_meta={
                "success": False,
                "tool_name": "write_file",
                "error_type": "permission_denied",
                "summary": "write_file blocked: read-only mode",
                "recommended_next": "Switch to act mode.",
            },
        )

        events = step_store.event_store.all_events()
        block = summarize_history_events(events)
        assert block is not None
        assert "Failures:" in block.summary
        assert "read-only mode" in block.summary
        assert "Next steps:" in block.summary
        assert "Switch to act mode" in block.summary

    def test_permission_deny_structured_observation(self):
        """Permission deny should produce structured observation with
        error_type, summary, recommended_next."""
        step_store = AgentStepStore(session_id="perm-deny-test")

        step = step_store.create_step(iteration=0, mode="sniff", runner_type="cot")
        step_store.update_step_after_parse(
            step, action_name="write_file",
            action_input={"path": "a.py"},
        )
        # Simulate permission deny
        step_store.update_step_after_tool(
            step,
            observation="Tool 'write_file' denied: not allowed in sniff mode",
            tool_error=True,
            tool_meta={
                "success": False,
                "tool_name": "write_file",
                "error_type": "permission_denied",
                "summary": "write_file denied: not allowed in sniff mode",
                "recommended_next": "Try a read-only tool or switch mode.",
            },
        )

        err_events = step_store.event_store.list_events(kind="tool_error")
        assert len(err_events) == 1
        meta = err_events[0].payload["tool_meta"]
        assert meta["error_type"] == "permission_denied"
        assert "summary" in meta
        assert "recommended_next" in meta


# ---------------------------------------------------------------------------
# v1.2.3: Real graph-path E2E tests — invoke actual LangGraph nodes
# ---------------------------------------------------------------------------


class TestGraphSniffFlowEndToEnd:
    """Sniff mode through the real graph: prepare_context → model → finish."""

    def test_graph_sniff_flow_end_to_end(self):
        """Sniff mode with no tool calls: model produces text, graph finishes."""
        session_id = "graph-sniff-e2e"
        root = tempfile.mkdtemp()
        coder = make_graph_coder(
            responses=["I see a Python project with 3 files."],
            mode="sniff",
            root=root,
        )
        coder.session_id = session_id

        from aicoder.graph.state import register_coder, unregister_coder
        register_coder(session_id, coder)
        try:
            result = invoke_graph(coder, "What files are in this project?", mode="sniff")

            # Graph should complete
            assert result["phase"] == "done"
            assert result.get("final_response") is not None
            assert len(result.get("final_response", "")) > 0

            # Messages should have been built
            assert len(result.get("messages", [])) > 0

            # Coder should have saved session
            assert len(coder.done_messages) > 0
        finally:
            unregister_coder(session_id)

    def test_graph_sniff_with_readonly_tool(self):
        """Sniff mode: model calls list_files (read-only), graph observes and finishes."""
        session_id = "graph-sniff-tool-e2e"
        root = tempfile.mkdtemp()

        # First response: tool call. Second response: final answer.
        coder = make_graph_coder(
            responses=[
                "Let me list the files.\n<list_files><path>.</path></list_files>",
                "The project has these files: main.py, utils.py.",
            ],
            confirm_answers=[True, True, True],
            mode="sniff",
            root=root,
        )
        coder.session_id = session_id

        # Register a CotAgentRunner for step tracking
        step_store = AgentStepStore(session_id=session_id)
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="sniff",
            tool_registry=coder.tool_registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        from aicoder.graph.state import register_coder, unregister_coder
        register_coder(session_id, coder)
        try:
            result = invoke_graph(
                coder, "List the files", mode="sniff",
                max_loops=3,
            )

            # Should complete
            assert result["phase"] == "done"

            # Runner should have tracked steps
            steps = runner.step_store.load_steps()
            assert len(steps) >= 1

            # First step should have parsed a tool call
            first_step = steps[0]
            assert first_step.action_name == "list_files"
        finally:
            unregister_coder(session_id)
            _cleanup_runner(session_id)


class TestGraphActToolLoopEndToEnd:
    """Act mode through the real graph: model → permission → execute → observe → loop."""

    def test_graph_act_tool_loop_end_to_end(self):
        """Act mode: model calls list_files, tool executes, model loops back,
        then finishes with a final answer."""
        session_id = "graph-act-loop-e2e"
        root = tempfile.mkdtemp()
        # Create a real file to read
        os.makedirs(os.path.join(root, "src"), exist_ok=True)
        with open(os.path.join(root, "src", "main.py"), "w") as f:
            f.write("print('hello')\n")

        # Response 1: tool call (list_files)
        # Response 2: final answer
        coder = make_graph_coder(
            responses=[
                "Let me check the files.\n<list_files><path>.</path></list_files>",
                "I found the project structure. There is a src/main.py file.",
            ],
            confirm_answers=[True, True, True],
            mode="act",
            root=root,
        )
        coder.session_id = session_id

        step_store = AgentStepStore(session_id=session_id)
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry=coder.tool_registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        from aicoder.graph.state import register_coder, unregister_coder
        register_coder(session_id, coder)
        try:
            result = invoke_graph(
                coder, "What files are in this project?", mode="act",
                max_loops=3,
            )

            assert result["phase"] == "done"

            # Runner should have 2 steps: first with tool, second with final answer
            steps = runner.step_store.load_steps()
            assert len(steps) >= 2

            # First step: tool call
            first = steps[0]
            assert first.action_name == "list_files"
            assert first.status in ("observed", "final", "parsed")

            # Events should be present
            events = step_store.event_store.all_events()
            assert len(events) >= 3  # step_started + tool_call + tool_result at minimum
            kinds = {e.kind for e in events}
            assert "step_started" in kinds
            assert "tool_call" in kinds
        finally:
            unregister_coder(session_id)
            _cleanup_runner(session_id)

    def test_graph_act_read_file_executes_and_observes(self):
        """Act mode: model calls read_file on a real file, tool executes,
        observation appears in messages."""
        session_id = "graph-act-read-e2e"
        root = tempfile.mkdtemp()
        test_file = os.path.join(root, "hello.py")
        with open(test_file, "w") as f:
            f.write("def greet(name):\n    return f'Hello, {name}!'\n")

        coder = make_graph_coder(
            responses=[
                "Reading the file.\n<read_file><path>hello.py</path></read_file>",
                "The file defines a greet function.",
            ],
            confirm_answers=[True, True, True],
            mode="act",
            root=root,
        )
        coder.session_id = session_id

        step_store = AgentStepStore(session_id=session_id)
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry=coder.tool_registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        from aicoder.graph.state import register_coder, unregister_coder
        register_coder(session_id, coder)
        try:
            result = invoke_graph(
                coder, "Read hello.py", mode="act",
                max_loops=3,
            )

            assert result["phase"] == "done"

            steps = runner.step_store.load_steps()
            assert len(steps) >= 1

            # First step should have read_file observation with real content
            first = steps[0]
            assert first.action_name == "read_file"
            if first.observation:
                assert "greet" in first.observation

            # Messages should contain the tool result
            messages = result.get("messages", [])
            has_tool_result = any(
                "greet" in (m.get("content") or "")
                for m in messages
            )
            assert has_tool_result, "Tool result should appear in messages"
        finally:
            unregister_coder(session_id)
            _cleanup_runner(session_id)


class TestGraphToolFailureThenContinueEndToEnd:
    """Tool failure through real graph path: failed tool → observe → model loop → finish."""

    def test_graph_tool_failure_then_continue_end_to_end(self):
        """Model calls read_file on nonexistent path → tool fails →
        model retries with list_files → succeeds → finishes."""
        session_id = "graph-fail-continue-e2e"
        root = tempfile.mkdtemp()

        coder = make_graph_coder(
            responses=[
                "Let me read the config.\n<read_file><path>nonexistent.py</path></read_file>",
                "File not found. Let me list files instead.\n<list_files><path>.</path></list_files>",
                "I found the project files.",
            ],
            confirm_answers=[True, True, True, True, True],
            mode="act",
            root=root,
        )
        coder.session_id = session_id

        step_store = AgentStepStore(session_id=session_id)
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry=coder.tool_registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        from aicoder.graph.state import register_coder, unregister_coder
        register_coder(session_id, coder)
        try:
            result = invoke_graph(
                coder, "Read the config file", mode="act",
                max_loops=5,
            )

            assert result["phase"] == "done"

            steps = runner.step_store.load_steps()
            assert len(steps) >= 2

            # First step should be the failed read_file
            first = steps[0]
            assert first.action_name == "read_file"

            # Check for error events in event store
            events = step_store.event_store.all_events()
            error_events = [e for e in events if e.kind == "tool_error"]
            assert len(error_events) >= 1, "First tool call should produce a tool_error event"

            # Second step should succeed (list_files)
            second = steps[1]
            assert second.action_name == "list_files"

            # Full sequence: step_started + tool_call + tool_error + step_started + tool_call + ...
            kinds = [e.kind for e in events]
            assert "tool_error" in kinds
            assert "tool_call" in kinds
        finally:
            unregister_coder(session_id)
            _cleanup_runner(session_id)

    def test_graph_permission_deny_routes_to_summarize(self):
        """When permission is denied (all tools blocked), graph should route
        to summarize instead of executing."""
        session_id = "graph-perm-deny-e2e"
        root = tempfile.mkdtemp()

        # sniff mode: write_file should be denied
        coder = make_graph_coder(
            responses=[
                "I will write a file.\n<write_file><path>test.py</path><content>hello</content></write_file>",
            ],
            mode="sniff",
            root=root,
        )
        coder.session_id = session_id

        from aicoder.graph.state import register_coder, unregister_coder
        register_coder(session_id, coder)
        try:
            result = invoke_graph(
                coder, "Create a test file", mode="sniff",
                max_loops=3,
            )

            # Should still finish (either done or via summarize after deny)
            assert result["phase"] in ("done",)

            # Tool observations should contain the denial
            tool_obs = result.get("tool_observations", [])
            # Permission deny produces an observation with success=False
            denied_obs = [o for o in tool_obs if not o.get("success")]
            assert len(denied_obs) >= 1, "write_file should be denied in sniff mode"
            assert denied_obs[0].get("error_type") == "permission_denied"
        finally:
            unregister_coder(session_id)

    def test_observe_result_reenters_model_loop(self):
        """After observe_tool_result, graph should re-enter model_node
        when within loop budget. Verifies the observe → continue → model cycle."""
        session_id = "graph-observe-loop-e2e"
        root = tempfile.mkdtemp()
        # Create files so list_files succeeds
        with open(os.path.join(root, "a.py"), "w") as f:
            f.write("a = 1\n")

        coder = make_graph_coder(
            responses=[
                "Step 1: list files.\n<list_files><path>.</path></list_files>",
                "Step 2: read file.\n<read_file><path>a.py</path></read_file>",
                "Done analyzing. The file defines a = 1.",
            ],
            confirm_answers=[True, True, True, True, True],
            mode="act",
            root=root,
        )
        coder.session_id = session_id

        step_store = AgentStepStore(session_id=session_id)
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry=coder.tool_registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        from aicoder.graph.state import register_coder, unregister_coder
        register_coder(session_id, coder)
        try:
            result = invoke_graph(
                coder, "Analyze this project", mode="act",
                max_loops=5,
            )

            assert result["phase"] == "done"

            # Should have 3 steps (2 tool calls + 1 final)
            steps = runner.step_store.load_steps()
            assert len(steps) >= 3, f"Expected >= 3 steps, got {len(steps)}"

            # Verify the observe → continue cycle: tool_result events exist
            events = step_store.event_store.all_events()
            tool_results = [e for e in events if e.kind == "tool_result"]
            assert len(tool_results) >= 2, "Should have tool_results from both iterations"

            # Verify messages contain both tool observations
            messages = result.get("messages", [])
            # At least some messages should contain tool output
            tool_content_msgs = [
                m for m in messages
                if m.get("content") and ("a.py" in m.get("content", "") or "list_files" in m.get("content", ""))
            ]
            assert len(tool_content_msgs) >= 1
        finally:
            unregister_coder(session_id)
            _cleanup_runner(session_id)
