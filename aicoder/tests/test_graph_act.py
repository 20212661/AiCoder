"""Tests for Phase 3: LangGraph act tool loop."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from aicoder.graph.state import AgentGraphState
from aicoder.graph.workflow import build_agent_graph
from aicoder.tests.conftest import (
    FakeIO,
    FakeModel,
    make_graph_coder,
    make_tool_call_xml,
    invoke_graph,
)


# ===========================================================================
# Tests
# ===========================================================================


class TestGraphBuilds:
    def test_graph_compiles(self):
        graph = build_agent_graph()
        assert graph is not None
        nodes = list(graph.nodes.keys())
        assert "model" in nodes
        assert "execute_tool" in nodes
        assert "permission" in nodes
        assert "observe_tool_result" in nodes


class TestActModeReadTool:
    def test_read_file_tool_executes(self, tmp_path):
        """Act mode should call read_file and return file contents."""
        test_file = tmp_path / "README.md"
        test_file.write_text("Hello World from README", encoding="utf-8")

        read_xml = make_tool_call_xml("read_file", path="README.md")
        coder = make_graph_coder(
            responses=[
                f"Let me read the file.\n{read_xml}",
                "I've read the file. It contains 'Hello World from README'.",
            ],
            confirm_answers=[True],
            root=str(tmp_path),
        )

        result = invoke_graph(coder, "Read the file README.md")

        assert result["phase"] == "done"
        assert result.get("final_response")
        msgs = coder.done_messages
        has_tool_result = any("read_file" in str(m) for m in msgs)
        assert has_tool_result


class TestActModeWriteTool:
    def test_write_file_tool_executes(self, tmp_path):
        """Act mode should successfully call write_file (with approval)."""
        write_xml = make_tool_call_xml("write_file", path="output.txt", content="new content")
        coder = make_graph_coder(
            responses=[
                f"Writing file.\n{write_xml}",
                "File written successfully.",
            ],
            confirm_answers=[True],
            root=str(tmp_path),
        )

        result = invoke_graph(coder, "Write 'new content' to output.txt")

        assert result["phase"] == "done"
        assert (tmp_path / "output.txt").read_text(encoding="utf-8") == "new content"


class TestToolResultFlowsBack:
    def test_tool_result_in_messages(self, tmp_path):
        """Tool results should appear in state messages for the next LLM call."""
        (tmp_path / "data.txt").write_text("some data here", encoding="utf-8")

        read_xml = make_tool_call_xml("read_file", path="data.txt")
        coder = make_graph_coder(
            responses=[
                f"Reading.\n{read_xml}",
                "I see the data.",
            ],
            confirm_answers=[True],
            root=str(tmp_path),
        )

        result = invoke_graph(coder, "Read data.txt")

        messages = result.get("messages", [])
        tool_result_msgs = [
            m for m in messages
            if m.get("role") == "user" and "read_file" in m.get("content", "")
        ]
        assert len(tool_result_msgs) >= 1
        assert "some data here" in tool_result_msgs[0]["content"]


class TestToolLoop:
    def test_multi_round_tool_calls(self, tmp_path):
        """Agent should loop: read file then write file across two rounds."""
        (tmp_path / "src.txt").write_text("source content", encoding="utf-8")

        read_xml = make_tool_call_xml("read_file", path="src.txt")
        write_xml = make_tool_call_xml("write_file", path="dst.txt", content="source content")

        coder = make_graph_coder(
            responses=[
                f"Reading source.\n{read_xml}",
                f"Now writing.\n{write_xml}",
                "Done copying.",
            ],
            confirm_answers=[True, True],
            root=str(tmp_path),
        )

        result = invoke_graph(coder, "Copy src.txt to dst.txt")

        assert result["phase"] == "done"
        assert (tmp_path / "dst.txt").read_text(encoding="utf-8") == "source content"
        assert result["loop_count"] == 3

    def test_max_loops_stops_loop(self):
        """Loop should stop after max_loops iterations even if tools keep coming."""
        responses = []
        for i in range(10):
            xml = make_tool_call_xml("list_files", path=".")
            responses.append(f"Round {i}.\n{xml}")

        coder = make_graph_coder(
            responses=responses,
            confirm_answers=[True] * 10,
        )

        result = invoke_graph(coder, "list files over and over", max_loops=3)

        assert result["loop_count"] <= 3

    def test_no_infinite_loop_without_tools(self):
        """If model always responds without tools, loop should terminate."""
        coder = make_graph_coder(
            responses=["Just a text response."],
        )

        result = invoke_graph(coder, "Say hello")

        assert result["phase"] == "done"
        assert result["loop_count"] == 1


class TestPermissionNode:
    def test_denied_tool_records_observation(self):
        """A tool denied by mode should produce an observation without execution."""
        edit_xml = make_tool_call_xml("edit_file", path="foo.py", old_text="a", new_text="b")
        coder = make_graph_coder(
            responses=[
                f"Editing.\n{edit_xml}",
                "Understood, I won't edit.",
            ],
            mode="plan",
        )

        result = invoke_graph(coder, "Edit foo.py", mode="plan")

        assert result["phase"] == "done"

    def test_user_rejected_tool_not_executed(self, tmp_path):
        """When user rejects a tool, it should not be executed."""
        (tmp_path / "readme.txt").write_text("secret data")

        read_xml = make_tool_call_xml("read_file", path="readme.txt")
        coder = make_graph_coder(
            responses=[
                f"Reading.\n{read_xml}",
                "OK, I won't read it.",
            ],
            confirm_answers=[False],
            root=str(tmp_path),
        )

        result = invoke_graph(coder, "Read readme.txt")

        assert result["phase"] == "done"
        all_content = str(coder.cur_messages) + str(result.get("tool_observations", []))
        assert "reject" in all_content.lower()

    def test_skip_permission_flag(self):
        """ToolExecutor.execute(skip_permission=True) should bypass permission checks."""
        from aicoder.tools.executor import ToolCoordinator, ToolExecutor
        from aicoder.tools.result import ToolCall, ExecutionState, ToolResult

        handler = MagicMock()
        handler.name = "test_tool"
        handler.requires_approval = True
        handler.default_timeout = 60
        handler.validate_params.return_value = None
        handler.execute.return_value = ToolResult.ok("test_tool", "ok")

        coord = ToolCoordinator()
        coord.register(handler)

        coder = MagicMock()
        coder.io = FakeIO()
        state = ExecutionState()
        executor = ToolExecutor(coord, coder, state)

        tc = ToolCall(name="test_tool", params={})

        result = executor.execute(tc, skip_permission=True)
        assert result.success
        handler.execute.assert_called_once()


class TestSummarizeNode:
    def test_final_response_is_last_assistant_message(self, tmp_path):
        """Summarize should extract the last assistant message."""
        (tmp_path / "f.txt").write_text("hi")

        read_xml = make_tool_call_xml("read_file", path="f.txt")
        coder = make_graph_coder(
            responses=[
                f"Reading.\n{read_xml}",
                "The file says 'hi'.",
            ],
            confirm_answers=[True],
            root=str(tmp_path),
        )

        result = invoke_graph(coder, "Read f.txt")

        assert result["final_response"] == "The file says 'hi'."


class TestSessionPersistence:
    def test_session_saved_after_completion(self, tmp_path):
        """Session should be saved when summarize_node runs."""
        coder = make_graph_coder(
            responses=["Direct answer, no tools."],
        )

        result = invoke_graph(coder, "Hello")

        assert result["phase"] == "done"
        coder._save_session.assert_called()

    def test_cur_messages_moved_to_done(self, tmp_path):
        """After summarize, cur_messages should be moved to done_messages."""
        coder = make_graph_coder(
            responses=["Hello back!"],
        )

        invoke_graph(coder, "Hello")

        assert len(coder.cur_messages) == 0
        assert len(coder.done_messages) > 0


class TestContextTrimming:
    def test_trim_messages_keeps_system_prefix(self):
        """_trim_messages should always keep the system message prefix."""
        from aicoder.graph.nodes import _trim_messages

        coder = make_graph_coder(responses=[])
        coder.main_model = FakeModel(responses=[], max_input_tokens=500)

        messages = [
            {"role": "system", "content": "Important system prompt"},
        ]
        for i in range(50):
            messages.append({"role": "user", "content": f"msg {i}"})
            messages.append({"role": "assistant", "content": f"reply {i}" * 100})

        trimmed = _trim_messages(coder, messages)

        assert trimmed[0]["role"] == "system"
        assert trimmed[0]["content"] == "Important system prompt"
        assert len(trimmed) < len(messages)

    def test_trim_messages_noop_when_small(self):
        """_trim_messages should not trim when messages fit."""
        from aicoder.graph.nodes import _trim_messages

        coder = make_graph_coder(responses=[])
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

        trimmed = _trim_messages(coder, messages)
        assert len(trimmed) == 3
