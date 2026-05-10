"""Tests for AgentRuntime adapter and integration."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from aicoder.agent_runtime import AgentRuntime, _create_runtime
from aicoder.exceptions import LLMError
from aicoder.tests.conftest import FakeModel, make_graph_coder


class TestAgentRuntimeInit:
    def test_builds_graph(self):
        coder = make_graph_coder(responses=[])
        runtime = AgentRuntime(coder)
        assert runtime.graph is not None
        assert runtime.coder is coder

    def test_default_no_checkpointer(self):
        coder = make_graph_coder(responses=[])
        runtime = AgentRuntime(coder)
        assert runtime.checkpointer is None


class TestInitialBuildConfig:
    def test_no_checkpointer_returns_none(self):
        coder = make_graph_coder(responses=[])
        runtime = AgentRuntime(coder)
        config = runtime._build_config()
        assert config is None

    def test_with_checkpointer_returns_thread_config(self):
        from aicoder.graph.checkpointer import get_checkpointer

        coder = make_graph_coder(responses=[])
        cp = get_checkpointer(":memory:")
        runtime = AgentRuntime(coder, checkpointer=cp)
        config = runtime._build_config()
        assert config is not None
        assert config["configurable"]["thread_id"] == "test-session"

    def test_default_session_id(self):
        from aicoder.graph.checkpointer import get_checkpointer

        coder = make_graph_coder(responses=[])
        coder.session_id = None
        cp = get_checkpointer(":memory:")
        runtime = AgentRuntime(coder, checkpointer=cp)
        config = runtime._build_config()
        assert config["configurable"]["thread_id"] == "default"


class TestInitialState:
    def test_act_mode_initial_state(self):
        coder = make_graph_coder(responses=[], mode="act")
        runtime = AgentRuntime(coder)
        state = runtime._initial_state("read foo.py")

        assert state["user_input"] == "read foo.py"
        assert state["mode"] == "act"
        assert state["phase"] == "idle"
        assert state["loop_count"] == 0
        assert state["max_loops"] == 5
        assert state["messages"] == []
        assert state["pending_tool_calls"] == []
        # _coder is no longer stored in state; it's in the module-level registry

    def test_plan_mode_initial_state(self):
        coder = make_graph_coder(responses=[], mode="plan")
        runtime = AgentRuntime(coder)
        state = runtime._initial_state("analyze this")

        assert state["mode"] == "plan"

    def test_session_id_propagated(self):
        coder = make_graph_coder(responses=[])
        coder.session_id = "abc-123"
        runtime = AgentRuntime(coder)
        state = runtime._initial_state("hello")

        assert state["session_id"] == "abc-123"

    def test_sniff_mode_initial_state(self):
        coder = make_graph_coder(responses=[], mode="sniff")
        runtime = AgentRuntime(coder)
        state = runtime._initial_state("investigate this")

        assert state["mode"] == "sniff"


class TestRunUserTurn:
    def test_successful_run(self, tmp_path):
        coder = make_graph_coder(
            responses=["Hello! I can help."],
            root=str(tmp_path),
        )
        runtime = AgentRuntime(coder)

        with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
             patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
             patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode:
            mock_sys.return_value = [{"role": "system", "content": "sys"}]
            mock_chat.return_value = []
            mock_mode.return_value = []
            result = runtime.run_user_turn("Hello")

        assert result is not None

    def test_llm_error_handled(self):
        """When the LLM fails after all retries, an error should be reported."""
        coder = make_graph_coder(responses=[])
        # Create a model that always raises
        coder.main_model = MagicMock()
        coder.main_model.name = "bad-model"
        coder.main_model.send_completion = MagicMock(side_effect=RuntimeError("API down"))
        coder.stream = False
        runtime = AgentRuntime(coder)

        with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
             patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
             patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode:
            mock_sys.return_value = [{"role": "system", "content": "sys"}]
            mock_chat.return_value = []
            mock_mode.return_value = []
            result = runtime.run_user_turn("test")

        assert result is None
        assert len(coder.io.errors) > 0

    def test_general_exception_handled(self):
        coder = make_graph_coder(responses=[])
        coder.session_id = None
        runtime = AgentRuntime(coder)
        # Corrupt the graph to force an error
        runtime.graph = MagicMock()
        runtime.graph.invoke = MagicMock(side_effect=RuntimeError("boom"))

        result = runtime.run_user_turn("test")

        assert result is None
        assert any("Runtime error" in e for e in coder.io.errors)


class TestCreateRuntimeFactory:
    def test_no_checkpoint_env(self):
        os.environ.pop("AICODER_LANGGRAPH_CHECKPOINT", None)
        coder = make_graph_coder(responses=[])
        runtime = _create_runtime(coder)
        assert runtime.checkpointer is None

    def test_with_checkpoint_env(self):
        os.environ["AICODER_LANGGRAPH_CHECKPOINT"] = "1"
        try:
            coder = make_graph_coder(responses=[])
            runtime = _create_runtime(coder)
            assert runtime.checkpointer is not None
        finally:
            os.environ.pop("AICODER_LANGGRAPH_CHECKPOINT", None)
