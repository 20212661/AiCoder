"""Tests for the unified message conversion layer (Phase 2)."""
import pytest

from aicoder.messages.types import (
    AssistantText,
    ToolCallRecord,
    ToolResultRecord,
    UserText,
)
from aicoder.messages.conversion import (
    build_llm_messages_for_fc,
    build_llm_messages_for_cot,
)


# ---------------------------------------------------------------------------
# FC conversion
# ---------------------------------------------------------------------------

class TestFcConversion:
    def test_assistant_text_becomes_assistant_message(self):
        items = [AssistantText(content="Hello world")]
        msgs = build_llm_messages_for_fc(items)
        assert len(msgs) == 1
        assert msgs[0] == {"role": "assistant", "content": "Hello world"}

    def test_user_text_becomes_user_message(self):
        items = [UserText(content="Do something")]
        msgs = build_llm_messages_for_fc(items)
        assert len(msgs) == 1
        assert msgs[0] == {"role": "user", "content": "Do something"}

    def test_tool_call_becomes_assistant_with_tool_calls(self):
        items = [
            ToolCallRecord(
                tool_call_id="call_1",
                tool_name="read_file",
                arguments={"path": "main.py"},
            ),
        ]
        msgs = build_llm_messages_for_fc(items)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["tool_calls"] is not None
        assert len(msgs[0]["tool_calls"]) == 1
        assert msgs[0]["tool_calls"][0]["id"] == "call_1"
        assert msgs[0]["tool_calls"][0]["function"]["name"] == "read_file"

    def test_tool_result_becomes_tool_message(self):
        items = [
            ToolResultRecord(
                tool_call_id="call_1",
                tool_name="read_file",
                success=True,
                content="file contents",
            ),
        ]
        msgs = build_llm_messages_for_fc(items)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["tool_call_id"] == "call_1"
        assert msgs[0]["content"] == "file contents"

    def test_full_fc_round_trip(self):
        """assistant thought + tool_call -> tool result -> next round structure."""
        items = [
            AssistantText(content="Let me read the file."),
            ToolCallRecord(
                tool_call_id="call_1",
                tool_name="read_file",
                arguments={"path": "a.py"},
            ),
            ToolResultRecord(
                tool_call_id="call_1",
                tool_name="read_file",
                success=True,
                content="print('hello')",
            ),
        ]
        msgs = build_llm_messages_for_fc(items)
        # Should produce: assistant (with tool_calls) + tool message
        assert len(msgs) == 2
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] == "Let me read the file."
        assert "tool_calls" in msgs[0]
        assert msgs[0]["tool_calls"][0]["id"] == "call_1"
        assert msgs[1]["role"] == "tool"
        assert msgs[1]["tool_call_id"] == "call_1"

    def test_multiple_tool_calls_correspondence(self):
        """Multiple tool calls must preserve tool_call_id correspondence."""
        items = [
            ToolCallRecord(
                tool_call_id="call_a",
                tool_name="read_file",
                arguments={"path": "a.py"},
            ),
            ToolCallRecord(
                tool_call_id="call_b",
                tool_name="search_files",
                arguments={"query": "TODO"},
            ),
            ToolResultRecord(
                tool_call_id="call_a",
                tool_name="read_file",
                success=True,
                content="content of a",
            ),
            ToolResultRecord(
                tool_call_id="call_b",
                tool_name="search_files",
                success=True,
                content="3 matches",
            ),
        ]
        msgs = build_llm_messages_for_fc(items)
        # 1 assistant msg with 2 tool_calls + 2 tool messages
        assert len(msgs) == 3
        assert msgs[0]["role"] == "assistant"
        assert len(msgs[0].get("tool_calls", [])) == 2
        assert msgs[1]["role"] == "tool"
        assert msgs[1]["tool_call_id"] == "call_a"
        assert msgs[2]["role"] == "tool"
        assert msgs[2]["tool_call_id"] == "call_b"

    def test_failed_result_is_structured_tool_message(self):
        """Failed tool result must be role=tool, NOT role=user."""
        items = [
            ToolResultRecord(
                tool_call_id="call_1",
                tool_name="read_file",
                success=False,
                content="file not found",
                is_error=True,
            ),
        ]
        msgs = build_llm_messages_for_fc(items)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "tool", "FC failed result must be tool message"
        assert msgs[0]["tool_call_id"] == "call_1"
        assert msgs[0]["content"] == "file not found"

    def test_thought_merges_with_tool_call(self):
        """AssistantText followed by ToolCallRecord merges into one message."""
        items = [
            AssistantText(content="Thinking..."),
            ToolCallRecord(
                tool_call_id="call_1",
                tool_name="read_file",
                arguments={"path": "x.py"},
            ),
        ]
        msgs = build_llm_messages_for_fc(items)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] == "Thinking..."
        assert "tool_calls" in msgs[0]


# ---------------------------------------------------------------------------
# CoT conversion
# ---------------------------------------------------------------------------

class TestCotConversion:
    def test_assistant_text(self):
        items = [AssistantText(content="Hello")]
        msgs = build_llm_messages_for_cot(items)
        assert msgs[0] == {"role": "assistant", "content": "Hello"}

    def test_tool_result_success_is_text_observation(self):
        items = [
            ToolResultRecord(
                tool_call_id="call_1",
                tool_name="read_file",
                success=True,
                content="file content",
            ),
        ]
        msgs = build_llm_messages_for_cot(items)
        assert msgs[0]["role"] == "user"
        assert "Result" in msgs[0]["content"]
        assert "file content" in msgs[0]["content"]

    def test_tool_result_failure_is_failed_text(self):
        items = [
            ToolResultRecord(
                tool_call_id="call_1",
                tool_name="read_file",
                success=False,
                content="not found",
                is_error=True,
            ),
        ]
        msgs = build_llm_messages_for_cot(items)
        assert msgs[0]["role"] == "user"
        assert "FAILED" in msgs[0]["content"]

    def test_tool_result_rejected_is_rejected_text(self):
        items = [
            ToolResultRecord(
                tool_call_id="call_1",
                tool_name="run_shell",
                success=False,
                content="User rejected",
                rejected=True,
            ),
        ]
        msgs = build_llm_messages_for_cot(items)
        assert msgs[0]["role"] == "user"
        assert "REJECTED" in msgs[0]["content"]

    def test_tool_call_is_textual_action(self):
        items = [
            ToolCallRecord(
                tool_call_id="call_1",
                tool_name="read_file",
                arguments={"path": "x.py"},
                thought="I need to check x.py",
            ),
        ]
        msgs = build_llm_messages_for_cot(items)
        assert msgs[0]["role"] == "assistant"
        assert "x.py" in msgs[0]["content"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_items(self):
        assert build_llm_messages_for_fc([]) == []
        assert build_llm_messages_for_cot([]) == []

    def test_fc_never_produces_user_tool_result(self):
        """FC conversion must NEVER produce role=user for tool results."""
        items = [
            ToolResultRecord(
                tool_call_id="c1",
                tool_name="read_file",
                success=True,
                content="ok",
            ),
            ToolResultRecord(
                tool_call_id="c2",
                tool_name="write_file",
                success=False,
                content="error",
                is_error=True,
            ),
        ]
        msgs = build_llm_messages_for_fc(items)
        for msg in msgs:
            if msg.get("tool_call_id"):
                assert msg["role"] == "tool", (
                    f"FC tool result must be role=tool, got {msg['role']}"
                )
