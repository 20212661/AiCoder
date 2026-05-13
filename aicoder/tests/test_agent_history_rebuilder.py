"""Tests for AgentHistoryRebuilder."""

import pytest

from aicoder.agent_history_rebuilder import AgentHistoryRebuilder
from aicoder.agent_step_store import AgentStep, AgentStepStore


def _make_step(store, iteration, *, action_name=None, observation="", final_answer="", error="", thought="", status="observed"):
    step = store.create_step(iteration=iteration, mode="act", runner_type="cot")
    if action_name:
        store.update_step_after_parse(step, thought=thought, action_name=action_name, action_input={"path": "test.py"}, action_raw=f"<{action_name}>...</{action_name}>")
    elif final_answer:
        store.update_step_after_parse(step, thought=thought)
        store.finalize_step(step, final_answer=final_answer)
        return step
    else:
        store.update_step_after_parse(step, thought=thought)

    if observation:
        store.update_step_after_tool(step, observation=observation)
    elif error:
        store.mark_error(step, error=error)
    return step


class TestBuildForCot:
    def test_empty_history_empty_steps(self):
        result = AgentHistoryRebuilder.build_for_cot([], [])
        assert result == []

    def test_done_messages_only(self):
        done = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
        result = AgentHistoryRebuilder.build_for_cot(done, [])
        assert result == done

    def test_single_observed_step(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, thought="I'll read the file", action_name="read_file", action_input={"path": "a.py"}, action_raw="<read_file>...</read_file>")
        store.update_step_after_tool(step, observation="file contents here")

        result = AgentHistoryRebuilder.build_for_cot([], store.load_steps())
        assert len(result) == 2
        assert result[0]["role"] == "assistant"
        assert "read_file" in result[0]["content"]
        assert result[1]["role"] == "user"
        assert "Result" in result[1]["content"]
        assert "file contents here" in result[1]["content"]

    def test_final_step(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, thought="Done")
        store.finalize_step(step, final_answer="The file has 42 lines.")

        result = AgentHistoryRebuilder.build_for_cot([], store.load_steps())
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert "42 lines" in result[0]["content"]

    def test_error_step(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="read_file", action_input={"path": "x.py"}, action_raw="<read_file>...</read_file>")
        store.mark_error(step, error="file not found")

        result = AgentHistoryRebuilder.build_for_cot([], store.load_steps())
        assert len(result) == 2
        assert "FAILED" in result[1]["content"]
        assert "file not found" in result[1]["content"]

    def test_done_messages_plus_steps(self):
        done = [{"role": "user", "content": "Previous question"}, {"role": "assistant", "content": "Previous answer"}]
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="read_file", action_input={"path": "a.py"}, action_raw="<read_file>...</read_file>")
        store.update_step_after_tool(step, observation="contents")

        result = AgentHistoryRebuilder.build_for_cot(done, store.load_steps())
        assert len(result) == 4
        assert result[0]["content"] == "Previous question"
        assert result[2]["role"] == "assistant"

    def test_created_step_skipped(self):
        store = AgentStepStore(session_id="test")
        store.create_step(iteration=0, mode="act", runner_type="cot")
        # status is "created" — should be skipped

        result = AgentHistoryRebuilder.build_for_cot([], store.load_steps())
        assert result == []

    def test_multiple_iterations(self):
        store = AgentStepStore(session_id="test")
        # Iteration 0: read file
        s0 = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(s0, action_name="read_file", action_input={"path": "a.py"}, action_raw="<read_file>...</read_file>")
        store.update_step_after_tool(s0, observation="content A")

        # Iteration 1: search files
        s1 = store.create_step(iteration=1, mode="act", runner_type="cot")
        store.update_step_after_parse(s1, action_name="search_files", action_input={"path": "."}, action_raw="<search_files>...</search_files>")
        store.update_step_after_tool(s1, observation="found 3 files")

        # Iteration 2: final
        s2 = store.create_step(iteration=2, mode="act", runner_type="cot")
        store.update_step_after_parse(s2, thought="Done")
        store.finalize_step(s2, final_answer="Analysis complete.")

        result = AgentHistoryRebuilder.build_for_cot([], store.load_steps())
        # 2 iterations × 2 messages + 1 final = 5 messages
        assert len(result) == 5
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "user"
        assert result[2]["role"] == "assistant"
        assert result[3]["role"] == "user"
        assert result[4]["role"] == "assistant"
        assert "Analysis complete" in result[4]["content"]


class TestBuildForFc:
    def test_single_tool_call_step(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(step, action_name="read_file", action_input={"path": "a.py"}, action_raw="{}")
        store.update_step_after_tool(step, observation="file contents")

        result = AgentHistoryRebuilder.build_for_fc([], store.load_steps())
        assert len(result) == 2
        assert result[0]["role"] == "assistant"
        assert "tool_calls" in result[0]
        assert result[0]["tool_calls"][0]["function"]["name"] == "read_file"
        assert result[1]["role"] == "tool"
        assert "file contents" in result[1]["content"]

    def test_final_step(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(step, thought="I see")
        store.finalize_step(step, final_answer="The answer is 42.")

        result = AgentHistoryRebuilder.build_for_fc([], store.load_steps())
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert "42" in result[0]["content"]

    def test_error_step(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(step, action_name="read_file", action_input={"path": "x"}, action_raw="{}")
        store.mark_error(step, error="not found")

        result = AgentHistoryRebuilder.build_for_fc([], store.load_steps())
        assert len(result) == 2
        assert result[1]["content"] == "Error: not found"

    def test_tool_call_id_is_step_id(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(step, action_name="read_file", action_input={"path": "a.py"}, action_raw="{}")
        store.update_step_after_tool(step, observation="ok")

        result = AgentHistoryRebuilder.build_for_fc([], store.load_steps())
        assert result[0]["tool_calls"][0]["id"] == step.id
        assert result[1]["tool_call_id"] == step.id


class TestBuildForCotFailureSemantics:
    """Test CoT rebuild distinguishes success/failure/rejection via tool_meta."""

    def test_observed_success_rebuilds_as_result(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="read_file", action_input={}, action_raw="<read_file/>")
        store.update_step_after_tool(
            step, observation="file content",
            tool_meta={"success": True, "rejected": False, "tool_name": "read_file"},
        )
        result = AgentHistoryRebuilder.build_for_cot([], store.load_steps())
        assert len(result) == 2
        assert "Result" in result[1]["content"]
        assert "FAILED" not in result[1]["content"]

    def test_observed_failure_rebuilds_as_failed(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="read_file", action_input={}, action_raw="<read_file/>")
        store.update_step_after_tool(
            step, observation="file not found",
            tool_meta={"success": False, "rejected": False, "tool_name": "read_file"},
        )
        result = AgentHistoryRebuilder.build_for_cot([], store.load_steps())
        assert len(result) == 2
        assert "FAILED" in result[1]["content"]
        assert "file not found" in result[1]["content"]

    def test_observed_rejected_rebuilds_as_rejected(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="run_shell", action_input={}, action_raw="<run_shell/>")
        store.update_step_after_tool(
            step, observation="",
            tool_meta={"success": False, "rejected": True, "tool_name": "run_shell"},
        )
        result = AgentHistoryRebuilder.build_for_cot([], store.load_steps())
        assert len(result) == 2
        assert "REJECTED" in result[1]["content"]

    def test_error_status_still_shows_failed(self):
        """Framework-level error (status=error) still shows FAILED."""
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="read_file", action_input={}, action_raw="<read_file/>")
        store.mark_error(step, error="LLM connection lost")
        result = AgentHistoryRebuilder.build_for_cot([], store.load_steps())
        assert "FAILED" in result[1]["content"]
        assert "LLM connection lost" in result[1]["content"]


class TestBuildForFcFailureSemantics:
    """Test FC rebuild distinguishes success/failure/rejection via tool_meta."""

    def test_observed_success_rebuilds_tool_message(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(step, action_name="read_file", action_input={"path": "a.py"}, action_raw="{}")
        store.update_step_after_tool(
            step, observation="file contents here",
            tool_meta={"success": True, "rejected": False, "tool_name": "read_file"},
        )
        result = AgentHistoryRebuilder.build_for_fc([], store.load_steps())
        assert len(result) == 2
        assert result[1]["role"] == "tool"
        assert "file contents here" in result[1]["content"]
        assert "FAILED" not in result[1]["content"]

    def test_observed_failure_rebuilds_as_failed(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(step, action_name="read_file", action_input={"path": "x"}, action_raw="{}")
        store.update_step_after_tool(
            step, observation="not found",
            tool_meta={"success": False, "rejected": False, "tool_name": "read_file"},
        )
        result = AgentHistoryRebuilder.build_for_fc([], store.load_steps())
        assert len(result) == 2
        assert result[1]["role"] == "tool"
        assert "FAILED" in result[1]["content"]
        assert "not found" in result[1]["content"]

    def test_observed_rejected_rebuilds_as_rejected(self):
        store = AgentStepStore(session_id="test")
        step = store.create_step(iteration=0, mode="act", runner_type="function-calling")
        store.update_step_after_parse(step, action_name="run_shell", action_input={}, action_raw="{}")
        store.update_step_after_tool(
            step, observation="",
            tool_meta={"success": False, "rejected": True, "tool_name": "run_shell"},
        )
        result = AgentHistoryRebuilder.build_for_fc([], store.load_steps())
        assert len(result) == 2
        assert result[1]["role"] == "tool"
        assert "User rejected the tool call." in result[1]["content"]
