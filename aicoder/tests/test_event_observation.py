"""Tests for structured observation payloads (v1.2 Phase 4).

Covers:
1. Permission deny produces structured observation
2. Tool success produces structured observation
3. Tool failure produces structured observation
4. FC / CoT both consume structured observations
5. Condensation can read summary / files / recommended_next
"""

from unittest.mock import MagicMock

import pytest

from aicoder.agent_step_store import AgentStepStore
from aicoder.graph.nodes import (
    _model_node_via_runner,
    execute_tool_node,
    observe_tool_result,
    permission_node,
)
from aicoder.graph.state import register_coder, unregister_coder
from aicoder.tools.result import ToolResult, ToolCall, ExecutionState
from aicoder.tools.executor import ToolExecutor, ToolCoordinator
from aicoder.tools.handlers.base import ToolHandler
from aicoder.runners import register_runner, unregister_runner
from aicoder.runners.cot_agent_runner import CotAgentRunner
from aicoder.runners.function_calling_agent_runner import FunctionCallingAgentRunner
from aicoder.runners.base_agent_runner import StepResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides):
    state = {
        "session_id": "obs-test",
        "mode": "act",
        "pending_tool_calls": [],
        "tool_observations": [],
        "messages": [],
        "loop_count": 0,
        "max_loops": 5,
    }
    state.update(overrides)
    return state


def _make_coder():
    coder = MagicMock()
    coder.io = MagicMock()
    coder.tool_exec_state = ExecutionState(mode="act")
    coder.cur_messages = []
    coder.done_messages = []
    coder.abs_fnames = set()
    return coder


def _register_coder_runner(session_id, coder, step_store, runner_cls):
    register_coder(session_id, coder)
    runner = runner_cls(
        coder=coder, session_id=session_id,
        mode="act", tool_registry=MagicMock(), step_store=step_store,
    )
    register_runner(session_id, runner)
    return runner


# ---------------------------------------------------------------------------
# ToolResult.meta unified fields
# ---------------------------------------------------------------------------


class TestToolResultMetaUnification:
    def test_ok_has_all_unified_fields(self):
        r = ToolResult.ok("read_file", "contents", meta={"files": ["/tmp/a.py"]})
        assert r.meta["tool_name"] == "read_file"
        assert r.meta["success"] is True
        assert r.meta["rejected"] is False
        assert r.meta["summary"] is not None
        assert r.meta["files"] == ["/tmp/a.py"]
        assert "error_type" in r.meta
        assert "recommended_next" in r.meta

    def test_fail_has_all_unified_fields(self):
        r = ToolResult.fail("write_file", "permission denied")
        assert r.meta["tool_name"] == "write_file"
        assert r.meta["success"] is False
        assert r.meta["rejected"] is False
        assert r.meta["error_type"] == "execution_error"
        assert r.meta["summary"] is not None
        assert "files" in r.meta
        assert "recommended_next" in r.meta

    def test_rejected_has_all_unified_fields(self):
        r = ToolResult.create_rejected("run_shell")
        assert r.meta["tool_name"] == "run_shell"
        assert r.meta["success"] is False
        assert r.meta["rejected"] is True
        assert r.meta["error_type"] == "user_rejected"
        assert r.meta["summary"] is not None
        assert "files" in r.meta
        assert "recommended_next" in r.meta

    def test_blocked_has_all_unified_fields(self):
        r = ToolResult.blocked("write_file", "read-only mode")
        assert r.meta["tool_name"] == "write_file"
        assert r.meta["success"] is False
        assert r.meta["rejected"] is False
        assert r.meta["error_type"] == "blocked"
        assert r.meta["summary"] is not None
        assert "files" in r.meta
        assert "recommended_next" in r.meta

    def test_meta_does_not_overwrite_provided_values(self):
        r = ToolResult.ok("read_file", "ok", meta={"summary": "Custom summary"})
        assert r.meta["summary"] == "Custom summary"


# ---------------------------------------------------------------------------
# Permission deny produces structured observation
# ---------------------------------------------------------------------------


class TestPermissionDenyStructured:
    def teardown_method(self):
        unregister_coder("obs-test")
        unregister_runner("obs-test")

    def test_deny_includes_error_type_and_summary(self):
        """permission_node deny should produce observation with error_type/summary."""
        coder = _make_coder()
        register_coder("obs-test", coder)

        # sniff mode denies write tools
        state = _make_state(
            mode="sniff",
            pending_tool_calls=[{"name": "write_file", "params": {"path": "a.py"}}],
        )
        result = permission_node(state)

        obs_list = result.get("tool_observations", [])
        assert len(obs_list) >= 1
        obs = obs_list[0]
        assert obs["success"] is False
        assert "error_type" in obs
        assert obs["error_type"] == "permission_denied"
        assert "summary" in obs
        assert "recommended_next" in obs
        assert obs["rejected"] is False

    def test_deny_observation_has_all_structured_fields(self):
        """Permission denied observation includes all v1.2 structured fields."""
        coder = _make_coder()
        register_coder("obs-test", coder)

        state = _make_state(
            mode="sniff",
            pending_tool_calls=[
                {"name": "write_file", "params": {"path": "a.py"}},
            ],
        )
        result = permission_node(state)
        obs = result["tool_observations"][0]

        # All structured fields should be present
        assert obs["tool_name"] == "write_file"
        assert obs["success"] is False
        assert obs["error_type"] == "permission_denied"
        assert isinstance(obs["summary"], str) and len(obs["summary"]) > 0
        assert isinstance(obs["recommended_next"], str) and len(obs["recommended_next"]) > 0
        assert obs["rejected"] is False


# ---------------------------------------------------------------------------
# Tool success produces structured observation
# ---------------------------------------------------------------------------


class TestToolSuccessStructured:
    def teardown_method(self):
        unregister_coder("obs-test")
        unregister_runner("obs-test")

    def test_success_observation_has_structured_fields(self):
        class OkHandler(ToolHandler):
            name = "ok_tool"
            requires_approval = False
            def execute(self, tc, coder):
                return ToolResult.ok("ok_tool", "hello world", meta={"files": ["/tmp/a.py"]})

        coord = ToolCoordinator()
        coord.register(OkHandler())

        coder = _make_coder()
        coder.tool_executor = ToolExecutor(coord, coder, ExecutionState(mode="act"))
        coder.tool_exec_state = coder.tool_executor.state
        register_coder("obs-test", coder)

        store = AgentStepStore(session_id="obs-test")
        _register_coder_runner("obs-test", coder, store, FunctionCallingAgentRunner)

        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(step, action_name="ok_tool", action_input={})

        state = _make_state(
            pending_tool_calls=[{"name": "ok_tool", "params": {}, "tool_call_id": "tc_1"}],
            loop_count=1,
        )

        result = execute_tool_node(state)
        obs_list = result["tool_observations"]
        assert len(obs_list) == 1

        obs = obs_list[0]
        assert obs["success"] is True
        assert obs["tool_name"] == "ok_tool"
        assert obs["output"] == "hello world"
        assert obs["tool_call_id"] == "tc_1"
        assert "summary" in obs
        assert "error_type" in obs
        assert "files" in obs
        assert obs["files"] == ["/tmp/a.py"]
        assert "recommended_next" in obs
        assert "iteration" in obs


# ---------------------------------------------------------------------------
# Tool failure produces structured observation
# ---------------------------------------------------------------------------


class TestToolFailureStructured:
    def teardown_method(self):
        unregister_coder("obs-test")
        unregister_runner("obs-test")

    def test_failure_observation_has_all_fields(self):
        class FailHandler(ToolHandler):
            name = "fail_tool"
            requires_approval = False
            def execute(self, tc, coder):
                return ToolResult.fail("fail_tool", "something broke", meta={"files": ["/tmp/b.py"]})

        coord = ToolCoordinator()
        coord.register(FailHandler())

        coder = _make_coder()
        coder.tool_executor = ToolExecutor(coord, coder, ExecutionState(mode="act"))
        coder.tool_exec_state = coder.tool_executor.state
        register_coder("obs-test", coder)

        store = AgentStepStore(session_id="obs-test")
        _register_coder_runner("obs-test", coder, store, CotAgentRunner)

        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="fail_tool", action_input={})

        state = _make_state(
            pending_tool_calls=[{"name": "fail_tool", "params": {}}],
            loop_count=2,
        )

        result = execute_tool_node(state)
        obs_list = result["tool_observations"]
        assert len(obs_list) == 1

        obs = obs_list[0]
        assert obs["success"] is False
        assert obs["tool_name"] == "fail_tool"
        assert obs["error"] == "something broke"
        assert obs["error_type"] == "execution_error"
        assert obs["summary"] is not None
        assert "fail_tool" in obs["summary"]
        assert obs["files"] == ["/tmp/b.py"]
        assert obs["recommended_next"] is not None
        assert obs["iteration"] == 2


class TestFcToolMessageSequence:
    def teardown_method(self):
        unregister_coder("obs-test")
        unregister_runner("obs-test")

    def test_runner_roundtrip_preserves_assistant_tool_calls_before_tool_result(self):
        """FC mode must keep assistant.tool_calls before appending role=tool."""
        coder = _make_coder()
        register_coder("obs-test", coder)

        store = AgentStepStore(session_id="obs-test")
        _register_coder_runner("obs-test", coder, store, FunctionCallingAgentRunner)

        runner = MagicMock()
        runner.run_step.return_value = StepResult(
            tool_calls=[ToolCall(name="list_files", params={"path": "."})],
            tool_call_ids=["call_001"],
            clean_text="Scanning repository",
            raw_response="Scanning repository",
            step=store.create_step(iteration=0, mode="sniff", runner_type="function-calling"),
        )

        state = _make_state(
            mode="sniff",
            messages=[{"role": "user", "content": "scan project"}],
            loop_count=0,
        )

        model_result = _model_node_via_runner(state, coder, state["messages"], runner, has_finalize=False)
        observed = observe_tool_result({
            **state,
            "messages": model_result["messages"],
            "tool_observations": [{
                "tool_name": "list_files",
                "success": True,
                "output": "aicoder\nREADME.md",
                "error": "",
                "rejected": False,
                "params": {"path": "."},
                "tool_call_id": "call_001",
            }],
        })

        assistant_msg = observed["messages"][-2]
        tool_msg = observed["messages"][-1]

        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["tool_calls"][0]["id"] == "call_001"
        assert assistant_msg["tool_calls"][0]["function"]["name"] == "list_files"
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "call_001"


# ---------------------------------------------------------------------------
# FC / CoT both consume structured observations
# ---------------------------------------------------------------------------


class TestFCAndCoTConsumeObservations:
    def teardown_method(self):
        unregister_coder("obs-test")
        unregister_runner("obs-test")

    def test_fc_path_consumes_structured_observation(self):
        """FC runner should produce tool messages with tool_call_id from observation."""
        obs = {
            "tool_name": "read_file",
            "success": True,
            "output": "file contents",
            "error": "",
            "rejected": False,
            "tool_call_id": "call_fc_123",
            "summary": "Tool 'read_file' succeeded.",
        }
        state = _make_state(
            tool_observations=[obs],
        )

        # Register FC runner to make _is_fc_runner return True
        coder = _make_coder()
        register_coder("obs-test", coder)
        store = AgentStepStore(session_id="obs-test")
        _register_coder_runner("obs-test", coder, store, FunctionCallingAgentRunner)

        result = observe_tool_result(state)
        msgs = result["messages"]
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "call_fc_123"
        assert tool_msgs[0]["content"] == "file contents"

    def test_cot_path_consumes_structured_observation(self):
        """CoT runner should produce text observation with structured data available."""
        obs = {
            "tool_name": "read_file",
            "success": True,
            "output": "file contents here",
            "error": "",
            "rejected": False,
            "summary": "Read file successfully",
            "files": ["/tmp/a.py"],
        }
        state = _make_state(tool_observations=[obs])

        # Register CoT runner
        coder = _make_coder()
        register_coder("obs-test", coder)
        store = AgentStepStore(session_id="obs-test")
        _register_coder_runner("obs-test", coder, store, CotAgentRunner)

        result = observe_tool_result(state)
        msgs = result["messages"]
        # CoT: text observation in user message
        user_msgs = [m for m in msgs if m.get("role") == "user"]
        assert len(user_msgs) == 1
        assert "read_file" in user_msgs[0]["content"]
        assert "file contents here" in user_msgs[0]["content"]


# ---------------------------------------------------------------------------
# Condensation compatibility
# ---------------------------------------------------------------------------


class TestCondensationReadsStructuredFields:
    def teardown_method(self):
        unregister_coder("obs-test")
        unregister_runner("obs-test")

    def test_event_payload_has_summary_and_files(self):
        """After tool execution, event store should have summary/files in payload."""
        class OkHandler(ToolHandler):
            name = "read_file"
            requires_approval = False
            def execute(self, tc, coder):
                return ToolResult.ok("read_file", "contents", meta={
                    "files": ["/tmp/a.py"],
                    "summary": "Read a.py successfully",
                })

        coord = ToolCoordinator()
        coord.register(OkHandler())

        coder = _make_coder()
        coder.tool_executor = ToolExecutor(coord, coder, ExecutionState(mode="act"))
        coder.tool_exec_state = coder.tool_executor.state
        register_coder("obs-test", coder)

        store = AgentStepStore(session_id="obs-test")
        _register_coder_runner("obs-test", coder, store, CotAgentRunner)

        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="read_file", action_input={"path": "/tmp/a.py"})

        state = _make_state(
            pending_tool_calls=[{"name": "read_file", "params": {"path": "/tmp/a.py"}}],
            loop_count=0,
        )

        execute_tool_node(state)

        # Check events have structured fields
        events = store.event_store.all_events()
        tool_result_events = [e for e in events if e.kind == "tool_result"]
        assert len(tool_result_events) >= 1

        payload = tool_result_events[0].payload
        assert "tool_meta" in payload
        meta = payload["tool_meta"]
        assert meta.get("success") is True
        assert meta.get("summary") == "Read a.py successfully"
        assert meta.get("files") == ["/tmp/a.py"]

    def test_condensation_can_extract_summary_and_files(self):
        """Condense pipeline should be able to extract summary/files from events."""
        from aicoder.context.condense import summarize_history_events

        events = [
            # Simulate events from a successful tool run
            MagicMock(
                event_id="ev-1",
                session_id="s1",
                iteration=0,
                kind="assistant_thought",
                payload={"thought": "Read config file"},
                created_at=0.0,
            ),
            MagicMock(
                event_id="ev-2",
                session_id="s1",
                iteration=0,
                kind="tool_call",
                payload={"tool_name": "read_file", "tool_input": {"path": "config.py"}},
                created_at=0.0,
            ),
            MagicMock(
                event_id="ev-3",
                session_id="s1",
                iteration=0,
                kind="tool_result",
                payload={
                    "observation": "DEBUG=True",
                    "files": ["/tmp/config.py"],
                    "tool_meta": {"summary": "Read config.py successfully", "success": True},
                },
                created_at=0.0,
            ),
        ]

        block = summarize_history_events(events)
        assert block is not None
        assert "config.py" in block.summary or "Files touched" in block.summary
        assert "Read config file" in block.summary


# ---------------------------------------------------------------------------
# ToolObservation TypedDict completeness
# ---------------------------------------------------------------------------


class TestToolObservationFields:
    def test_all_v12_fields_accessible(self):
        """Verify ToolObservation has all v1.2 fields."""
        obs: ToolObservation = {
            "tool_name": "read_file",
            "params": {"path": "a.py"},
            "success": True,
            "output": "contents",
            "error": "",
            "rejected": False,
            "tool_call_id": "tc_001",
            "error_type": "",
            "summary": "Read a.py successfully",
            "recommended_next": "",
            "files": ["/tmp/a.py"],
            "iteration": 0,
        }
        assert obs["tool_call_id"] == "tc_001"
        assert obs["error_type"] == ""
        assert obs["summary"] == "Read a.py successfully"
        assert obs["files"] == ["/tmp/a.py"]
        assert obs["iteration"] == 0

    def test_observation_backward_compatible(self):
        """Old-style observation (without v1.2 fields) still works."""
        obs: ToolObservation = {
            "tool_name": "read_file",
            "success": True,
            "output": "ok",
        }
        assert obs["success"] is True
        assert obs.get("summary") is None  # TypedDict total=False
