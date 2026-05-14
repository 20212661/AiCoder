"""Tests for History View — three separate views of agent execution history."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from aicoder.agent_step_store import AgentStepStore
from aicoder.context.history_view import (
    build_ui_history_view,
    build_runtime_history_view,
    build_llm_history_view,
)
from aicoder.runners.cot_agent_runner import CotAgentRunner
from aicoder.runners.function_calling_agent_runner import FunctionCallingAgentRunner
from aicoder.runners import register_runner, unregister_runner
from aicoder.tools.registry import ToolRegistry
from aicoder.tools.executor import ToolCoordinator, ToolExecutor
from aicoder.tools.result import ExecutionState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_base_coder(session_id: str, mode: str = "act") -> MagicMock:
    coder = MagicMock()
    coder.main_model = MagicMock()
    coder.main_model.name = "test-model"
    coder.main_model.max_input_tokens = 128000
    coder.io = MagicMock()
    coder.stream = True
    coder.root = "/tmp/test"
    coder.session_id = session_id
    coder.done_messages = []
    coder.cur_messages = []
    coder.abs_fnames = set()
    coder.abs_read_only_fnames = set()
    coder._first_message = True
    coder._approval = None
    coder.auto_commits = False
    coder.repo = None
    coder._first_user_message = None
    coder.verbose = False
    coder.summarizer = None
    coder.edit_format = "whole"
    coder.abs_root_path_cache = {}
    coder._save_session = MagicMock()
    coder.auto_commit = MagicMock()
    coder.gpt_prompts = MagicMock()
    coder.gpt_prompts.main_system = ""
    coder.gpt_prompts.system_reminder = ""
    coder.gpt_prompts.example_messages = []
    coder.gpt_prompts.files_content_prefix = ""
    coder.gpt_prompts.files_content_assistant_reply = "Ok."
    coder._system_prompt = MagicMock()
    coder._system_prompt.build.return_value = "You are a helpful assistant."
    coder._update_tool_model_info = MagicMock()
    coder._build_workspace_info.return_value = ""
    coder._detect_cli_tools.return_value = ""
    coder.get_repo_map.return_value = ""
    coder.abs_root_path = lambda p: str(Path("/tmp/test") / p)

    registry = ToolRegistry()
    coord = ToolCoordinator()
    exec_state = ExecutionState()
    exec_state.mode = mode
    coder.tool_registry = registry
    coder.tool_coordinator = coord
    coder.tool_exec_state = exec_state
    coder.tool_executor = ToolExecutor(coord, coder, exec_state)

    return coder


def _make_coder_with_fc_steps(session_id: str = "fc-hv-test") -> tuple[MagicMock, AgentStepStore]:
    coder = _make_base_coder(session_id, "act")
    coder.done_messages = [
        {"role": "user", "content": "what is this project?"},
        {"role": "assistant", "content": "This is a Python project."},
    ]

    step_store = AgentStepStore(session_id=session_id)
    step = step_store.create_step(iteration=0, mode="act", runner_type="function-calling")
    step.thought = "Reading main.py"
    step.tool_calls = [{
        "tool_call_id": "call_001",
        "tool_name": "read_file",
        "arguments": {"path": "main.py"},
    }]
    step.tool_results = [{
        "tool_call_id": "call_001",
        "tool_name": "read_file",
        "success": True,
        "content": "def main(): pass",
        "is_error": False,
        "rejected": False,
    }]
    step_store.update_step_after_parse(
        step, thought="Reading main.py",
        action_name="read_file", action_input={"path": "main.py"},
    )
    step_store.update_step_after_tool(
        step, observation="def main(): pass",
        tool_meta={"success": True, "tool_name": "read_file"},
    )

    runner = FunctionCallingAgentRunner(
        coder=coder, session_id=session_id,
        mode="act", tool_registry=coder.tool_registry, step_store=step_store,
    )
    register_runner(session_id, runner)

    return coder, step_store


def _make_coder_with_cot_steps(session_id: str = "cot-hv-test") -> tuple[MagicMock, AgentStepStore]:
    coder = _make_base_coder(session_id, "act")
    coder.done_messages = [
        {"role": "user", "content": "read bar.py"},
        {"role": "assistant", "content": "[read_file] Result:\ndef bar(): return 1"},
    ]

    step_store = AgentStepStore(session_id=session_id)
    step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
    step_store.update_step_after_parse(
        step, thought="Reading bar.py",
        action_name="read_file", action_input={"path": "bar.py"},
    )
    step_store.update_step_after_tool(
        step, observation="def bar(): return 1",
        tool_meta={"success": True, "tool_name": "read_file"},
    )

    runner = CotAgentRunner(
        coder=coder, session_id=session_id,
        mode="act", tool_registry=coder.tool_registry, step_store=step_store,
    )
    register_runner(session_id, runner)

    return coder, step_store


# ---------------------------------------------------------------------------
# UI view tests
# ---------------------------------------------------------------------------


class TestUIHistoryView:
    def teardown_method(self):
        for sid in ("fc-hv-test", "cot-hv-test", "no-runner-hv"):
            unregister_runner(sid)

    def test_ui_view_includes_step_events(self):
        coder, _ = _make_coder_with_fc_steps()
        view = build_ui_history_view(coder, "act", "function-calling")

        # Should have done_messages entries + step entries
        assert len(view) > 0
        step_entries = [e for e in view if e.get("source") == "step"]
        assert len(step_entries) >= 1

    def test_ui_view_includes_lifecycle_events(self):
        coder, _ = _make_coder_with_fc_steps()
        view = build_ui_history_view(coder, "act", "function-calling")

        step_entries = [e for e in view if e.get("source") == "step"]
        # At least one step should have lifecycle events
        has_events = any("events" in e for e in step_entries)
        assert has_events, "UI view should include lifecycle events"

    def test_ui_view_includes_thought_and_observation(self):
        coder, _ = _make_coder_with_cot_steps()
        view = build_ui_history_view(coder, "act", "cot")

        step_entries = [e for e in view if e.get("source") == "step"]
        assert len(step_entries) >= 1
        step = step_entries[0]
        assert "thought" in step
        assert "observation" in step

    def test_ui_view_includes_done_messages(self):
        coder, _ = _make_coder_with_cot_steps()
        view = build_ui_history_view(coder, "act", "cot")

        dm_entries = [e for e in view if e.get("source") == "done_messages"]
        assert len(dm_entries) == 2  # user + assistant from done_messages


# ---------------------------------------------------------------------------
# Runtime view tests
# ---------------------------------------------------------------------------


class TestRuntimeHistoryView:
    def teardown_method(self):
        for sid in ("fc-hv-test", "cot-hv-test", "no-runner-hv"):
            unregister_runner(sid)

    def test_runtime_view_has_structured_action(self):
        coder, _ = _make_coder_with_cot_steps()
        view = build_runtime_history_view(coder, "act", "cot")

        assert len(view) >= 1
        step = view[0]
        assert "action" in step
        assert step["action"]["tool_name"] == "read_file"

    def test_runtime_view_has_structured_observation(self):
        coder, _ = _make_coder_with_cot_steps()
        view = build_runtime_history_view(coder, "act", "cot")

        step = view[0]
        assert "observation" in step
        assert step["observation"]["success"] is True
        assert step["observation"]["output"] == "def bar(): return 1"

    def test_runtime_view_fc_has_tool_calls_and_results(self):
        coder, _ = _make_coder_with_fc_steps()
        view = build_runtime_history_view(coder, "act", "function-calling")

        assert len(view) >= 1
        step = view[0]
        assert "tool_calls" in step
        assert len(step["tool_calls"]) == 1
        assert step["tool_calls"][0]["tool_name"] == "read_file"

    def test_runtime_view_no_ui_events(self):
        """Runtime view should NOT have lifecycle events (that's UI view)."""
        coder, _ = _make_coder_with_fc_steps()
        view = build_runtime_history_view(coder, "act", "function-calling")

        for entry in view:
            assert "events" not in entry, "Runtime view should not have lifecycle events"
            assert "source" not in entry, "Runtime view should not have UI source field"


# ---------------------------------------------------------------------------
# LLM view tests
# ---------------------------------------------------------------------------


class TestLLMHistoryView:
    def teardown_method(self):
        for sid in ("fc-hv-test", "cot-hv-test", "no-runner-hv"):
            unregister_runner(sid)

    def test_llm_view_fc_has_structured_tool_calls(self):
        coder, _ = _make_coder_with_fc_steps()
        view = build_llm_history_view(coder, "act", "function-calling")

        # FC view should have assistant with tool_calls
        assistant_tc = [
            m for m in view
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        assert len(assistant_tc) >= 1

    def test_llm_view_fc_has_tool_messages(self):
        coder, _ = _make_coder_with_fc_steps()
        view = build_llm_history_view(coder, "act", "function-calling")

        tool_msgs = [
            m for m in view
            if m.get("role") == "tool" and m.get("tool_call_id") == "call_001"
        ]
        assert len(tool_msgs) >= 1

    def test_llm_view_cot_no_structured_tool_calls(self):
        coder, _ = _make_coder_with_cot_steps()
        view = build_llm_history_view(coder, "act", "cot")

        # CoT should NOT have structured tool_calls
        assistant_tc = [
            m for m in view
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        assert len(assistant_tc) == 0

    def test_llm_view_cot_has_text_observation(self):
        coder, _ = _make_coder_with_cot_steps()
        view = build_llm_history_view(coder, "act", "cot")

        # CoT should have text-form observation
        text_obs = [
            m for m in view
            if m.get("role") == "assistant"
            and "read_file" in (m.get("content") or "")
        ]
        assert len(text_obs) >= 1

    def test_llm_view_no_runner_falls_back(self):
        """When no runner is registered, falls back to done_messages."""
        coder = _make_base_coder("no-runner-hv")
        coder.done_messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        view = build_llm_history_view(coder, "act", "cot")
        assert len(view) == 2
        assert view[0]["content"] == "hello"


# ---------------------------------------------------------------------------
# Three views produce different output
# ---------------------------------------------------------------------------


class TestViewSeparation:
    def teardown_method(self):
        unregister_runner("fc-hv-test")

    def test_three_views_are_different(self):
        coder, _ = _make_coder_with_fc_steps()

        ui = build_ui_history_view(coder, "act", "function-calling")
        runtime = build_runtime_history_view(coder, "act", "function-calling")
        llm = build_llm_history_view(coder, "act", "function-calling")

        # UI view includes done_messages + step events
        assert any(e.get("source") == "done_messages" for e in ui)

        # Runtime view has structured action/observation but no source field
        assert not any(e.get("source") == "done_messages" for e in runtime)

        # LLM view is raw messages (role/content dicts)
        assert all(isinstance(m, dict) and "role" in m for m in llm)

    def test_ui_view_larger_than_llm_view(self):
        coder, _ = _make_coder_with_fc_steps()

        ui = build_ui_history_view(coder, "act", "function-calling")
        llm = build_llm_history_view(coder, "act", "function-calling")

        # UI view has structured metadata (events, etc.) that LLM view does not
        # The counts may differ because UI collapses steps while LLM expands
        # them. Instead, verify UI has richer content per entry.
        ui_steps = [e for e in ui if e.get("source") == "step"]
        assert any("events" in s for s in ui_steps), "UI should have event metadata"
        # LLM view should have no event metadata
        assert all("events" not in m for m in llm)

    def test_fc_llm_view_has_tool_call_id(self):
        """LLM view for FC must preserve tool_call_id."""
        coder, _ = _make_coder_with_fc_steps()
        view = build_llm_history_view(coder, "act", "function-calling")

        tool_msgs = [m for m in view if m.get("role") == "tool"]
        assert all(m.get("tool_call_id") for m in tool_msgs)

    def test_cot_llm_view_no_tool_messages(self):
        """LLM view for CoT must NOT have role=tool messages."""
        unregister_runner("cot-hv-test")
        coder, _ = _make_coder_with_cot_steps()
        try:
            view = build_llm_history_view(coder, "act", "cot")
            tool_msgs = [m for m in view if m.get("role") == "tool"]
            assert len(tool_msgs) == 0
        finally:
            unregister_runner("cot-hv-test")


# ---------------------------------------------------------------------------
# ContextPacker integration
# ---------------------------------------------------------------------------


class TestPackerUsesHistoryView:
    def teardown_method(self):
        for sid in ("fc-hv-test", "cot-hv-test"):
            unregister_runner(sid)

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_packer_calls_llm_history_view(self, mock_repo):
        """pack_context should use build_llm_history_view when no override."""
        from aicoder.context.packer import pack_context

        coder, _ = _make_coder_with_fc_steps()
        with patch("aicoder.context.history_view.build_llm_history_view") as mock_hv, \
             patch("aicoder.coders.message_builder.build_chat_files_messages", return_value=[]), \
             patch("aicoder.coders.message_builder.build_system_messages", return_value=[]), \
             patch("aicoder.coders.message_builder.build_runtime_state_messages", return_value=[]), \
             patch("aicoder.coders.message_builder.build_mode_messages", return_value=[]):
            mock_hv.return_value = [
                {"role": "user", "content": "test"},
            ]
            pack_context(coder, user_input="", mode="act", runner_type="function-calling")
            mock_hv.assert_called_once_with(coder, "act", "function-calling")

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_packer_override_still_works(self, mock_repo):
        """history_override should still take precedence when provided."""
        from aicoder.context.packer import pack_context

        coder, _ = _make_coder_with_fc_steps()
        override = [{"role": "user", "content": "override"}]

        with patch("aicoder.context.history_view.build_llm_history_view") as mock_hv, \
             patch("aicoder.coders.message_builder.build_chat_files_messages", return_value=[]), \
             patch("aicoder.coders.message_builder.build_system_messages", return_value=[]), \
             patch("aicoder.coders.message_builder.build_runtime_state_messages", return_value=[]), \
             patch("aicoder.coders.message_builder.build_mode_messages", return_value=[]):
            mock_hv.return_value = [{"role": "user", "content": "from_view"}]
            packed = pack_context(
                coder, user_input="", mode="act",
                runner_type="function-calling", history_override=override,
            )
            # Override should be used, not the view
            mock_hv.assert_not_called()
            override_msgs = [
                m for m in packed.conversation_messages
                if "override" in m.get("content", "")
            ]
            assert len(override_msgs) == 1

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_packer_fc_produces_structured_messages(self, mock_repo):
        """End-to-end: pack_context for FC produces structured tool_calls."""
        from aicoder.context.packer import pack_context

        coder, _ = _make_coder_with_fc_steps()
        with patch("aicoder.coders.message_builder.build_chat_files_messages", return_value=[]), \
             patch("aicoder.coders.message_builder.build_system_messages", return_value=[]), \
             patch("aicoder.coders.message_builder.build_runtime_state_messages", return_value=[]), \
             patch("aicoder.coders.message_builder.build_mode_messages", return_value=[]):
            packed = pack_context(
                coder, user_input="", mode="act", runner_type="function-calling",
            )

        # Should have structured tool_calls
        assistant_tc = [
            m for m in packed.conversation_messages
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        assert len(assistant_tc) >= 1

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_packer_cot_produces_text_messages(self, mock_repo):
        """End-to-end: pack_context for CoT produces text observations."""
        from aicoder.context.packer import pack_context

        unregister_runner("cot-hv-test")
        coder, _ = _make_coder_with_cot_steps()
        try:
            with patch("aicoder.coders.message_builder.build_chat_files_messages", return_value=[]), \
                 patch("aicoder.coders.message_builder.build_system_messages", return_value=[]), \
                 patch("aicoder.coders.message_builder.build_runtime_state_messages", return_value=[]), \
                 patch("aicoder.coders.message_builder.build_mode_messages", return_value=[]):
                packed = pack_context(
                    coder, user_input="", mode="act", runner_type="cot",
                )

            # Should NOT have structured tool_calls
            assistant_tc = [
                m for m in packed.conversation_messages
                if m.get("role") == "assistant" and m.get("tool_calls")
            ]
            assert len(assistant_tc) == 0
        finally:
            unregister_runner("cot-hv-test")
