"""Tests for FC structured history persistence across turns (Fix 2)."""
import pytest
from unittest.mock import MagicMock

from aicoder.agent_step_store import AgentStepStore
from aicoder.agent_history_rebuilder import AgentHistoryRebuilder, _step_to_stored_items
from aicoder.messages.types import ToolCallRecord, ToolResultRecord


class TestFcStepStructuredData:
    """FC steps with tool_calls/tool_results should produce structured StoredItems."""

    def test_step_with_structured_tool_data(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(
            step,
            thought="I need to read the file.",
            action_name="read_file",
            action_input={"path": "main.py"},
        )
        # Simulate what execute_tool_node does for FC path:
        step.tool_calls.append({
            "tool_call_id": "call_abc123",
            "tool_name": "read_file",
            "arguments": {"path": "main.py"},
        })
        step.tool_results.append({
            "tool_call_id": "call_abc123",
            "tool_name": "read_file",
            "success": True,
            "content": "print('hello')",
            "is_error": False,
            "rejected": False,
        })
        store.update_step_after_tool(
            step,
            observation="print('hello')",
            tool_meta={"success": True, "tool_name": "read_file"},
        )

        items = _step_to_stored_items(step)
        # thought + ToolCallRecord + ToolResultRecord = 3 items
        assert len(items) == 3
        assert isinstance(items[0], type(items[0]))  # AssistantText
        assert items[1].tool_call_id == "call_abc123"  # ToolCallRecord
        assert items[2].tool_call_id == "call_abc123"  # ToolResultRecord

    def test_fc_rebuild_preserves_tool_structure(self):
        """build_for_fc with structured step data must produce role=tool messages."""
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(
            step,
            thought="Let me check this.",
            action_name="read_file",
            action_input={"path": "x.py"},
        )
        step.tool_calls.append({
            "tool_call_id": "call_fc_001",
            "tool_name": "read_file",
            "arguments": {"path": "x.py"},
        })
        step.tool_results.append({
            "tool_call_id": "call_fc_001",
            "tool_name": "read_file",
            "success": True,
            "content": "file contents here",
            "is_error": False,
        })
        store.update_step_after_tool(
            step,
            observation="file contents here",
            tool_meta={"success": True, "tool_name": "read_file"},
        )

        result = AgentHistoryRebuilder.build_for_fc([], store.load_steps())

        # Should produce: assistant (with tool_calls) + tool message
        assert len(result) == 2
        assert result[0]["role"] == "assistant"
        assert result[0]["tool_calls"] is not None
        assert result[0]["tool_calls"][0]["id"] == "call_fc_001"
        assert result[0]["tool_calls"][0]["function"]["name"] == "read_file"

        assert result[1]["role"] == "tool"
        assert result[1]["tool_call_id"] == "call_fc_001"
        assert result[1]["content"] == "file contents here"

    def test_fc_rebuild_with_failure_preserves_structure(self):
        """FC failure must still be role=tool, not role=user text."""
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(
            step,
            action_name="read_file",
            action_input={"path": "missing.py"},
        )
        step.tool_calls.append({
            "tool_call_id": "call_fc_002",
            "tool_name": "read_file",
            "arguments": {"path": "missing.py"},
        })
        step.tool_results.append({
            "tool_call_id": "call_fc_002",
            "tool_name": "read_file",
            "success": False,
            "content": "File not found",
            "is_error": True,
        })
        store.update_step_after_tool(
            step,
            observation="File not found",
            tool_meta={"success": False, "tool_name": "read_file"},
        )

        result = AgentHistoryRebuilder.build_for_fc([], store.load_steps())
        assert len(result) == 2
        assert result[1]["role"] == "tool", "FC failure must be role=tool"
        assert result[1]["tool_call_id"] == "call_fc_002"
        assert result[1]["content"] == "File not found"

    def test_fc_cross_turn_history_rebuild(self):
        """Steps from turn 1 must rebuild correctly when turn 2 starts."""
        # Simulate turn 1: one tool call with result
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(
            step,
            thought="Reading main.py",
            action_name="read_file",
            action_input={"path": "main.py"},
        )
        step.tool_calls.append({
            "tool_call_id": "call_turn1_001",
            "tool_name": "read_file",
            "arguments": {"path": "main.py"},
        })
        step.tool_results.append({
            "tool_call_id": "call_turn1_001",
            "tool_name": "read_file",
            "success": True,
            "content": "def main(): pass",
            "is_error": False,
        })
        store.update_step_after_tool(
            step,
            observation="def main(): pass",
            tool_meta={"success": True, "tool_name": "read_file"},
        )

        # Turn 2 starts: rebuild history from steps
        done_messages = [
            {"role": "user", "content": "Read main.py"},
        ]
        rebuilt = AgentHistoryRebuilder.build_for_fc(done_messages, store.load_steps())

        # done_messages should be preserved
        assert rebuilt[0] == {"role": "user", "content": "Read main.py"}

        # Then structured FC messages from steps
        assert rebuilt[1]["role"] == "assistant"
        assert rebuilt[1]["tool_calls"][0]["id"] == "call_turn1_001"
        assert rebuilt[2]["role"] == "tool"
        assert rebuilt[2]["tool_call_id"] == "call_turn1_001"
        assert rebuilt[2]["content"] == "def main(): pass"

    def test_cot_unchanged_by_structured_fields(self):
        """CoT rebuild should ignore tool_calls/tool_results and use legacy fields."""
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(
            step,
            thought="Checking file",
            action_name="read_file",
            action_input={"path": "x.py"},
            action_raw="<read_file><path>x.py</path></read_file>",
        )
        # Even if tool_calls has data, CoT path uses legacy fields
        step.tool_calls.append({
            "tool_call_id": "should_be_ignored",
            "tool_name": "read_file",
            "arguments": {"path": "x.py"},
        })
        store.update_step_after_tool(
            step,
            observation="file text",
            tool_meta={"success": True, "tool_name": "read_file"},
        )

        result = AgentHistoryRebuilder.build_for_cot([], store.load_steps())
        # CoT path: all textual
        for msg in result:
            assert msg["role"] in ("assistant", "user"), (
                f"CoT should only have assistant/user, got {msg['role']}"
            )
