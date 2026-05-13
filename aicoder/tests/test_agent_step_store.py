"""Tests for AgentStep and AgentStepStore."""

import pytest

from aicoder.agent_step_store import AgentStep, AgentStepStore


# ---------------------------------------------------------------------------
# AgentStep creation
# ---------------------------------------------------------------------------


class TestAgentStepCreation:
    def test_create_step_defaults(self):
        store = AgentStepStore(session_id="sess-1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")

        assert step.session_id == "sess-1"
        assert step.iteration == 0
        assert step.mode == "act"
        assert step.runner_type == "cot"
        assert step.phase == "created"
        assert step.status == "created"
        assert step.thought == ""
        assert step.action_name is None
        assert step.action_input is None
        assert step.action_raw is None
        assert step.observation == ""
        assert step.final_answer == ""
        assert step.tool_meta == {}
        assert step.files == []
        assert step.error == ""
        assert len(step.id) > 0

    def test_create_step_unique_ids(self):
        store = AgentStepStore(session_id="sess-1")
        s1 = store.create_step(iteration=0, mode="act", runner_type="cot")
        s2 = store.create_step(iteration=1, mode="act", runner_type="cot")
        assert s1.id != s2.id

    def test_create_step_function_calling_type(self):
        store = AgentStepStore(session_id="sess-1")
        step = store.create_step(iteration=0, mode="plan", runner_type="function-calling")
        assert step.runner_type == "function-calling"
        assert step.mode == "plan"


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


class TestStateTransitions:
    def test_update_after_parse(self):
        store = AgentStepStore(session_id="sess-1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")

        store.update_step_after_parse(
            step,
            thought="I need to read the file",
            action_name="read_file",
            action_input={"path": "/tmp/test.py"},
            action_raw="<read_file><path>/tmp/test.py</path></read_file>",
        )

        assert step.status == "parsed"
        assert step.phase == "parsed"
        assert step.thought == "I need to read the file"
        assert step.action_name == "read_file"
        assert step.action_input == {"path": "/tmp/test.py"}
        assert step.action_raw == "<read_file><path>/tmp/test.py</path></read_file>"

    def test_update_after_tool(self):
        store = AgentStepStore(session_id="sess-1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="read_file")

        store.update_step_after_tool(
            step,
            observation="file contents here",
            tool_meta={"duration_ms": 150, "retries": 0},
            files=["/tmp/test.py"],
        )

        assert step.status == "observed"
        assert step.phase == "observed"
        assert step.observation == "file contents here"
        assert step.tool_meta == {"duration_ms": 150, "retries": 0}
        assert step.files == ["/tmp/test.py"]

    def test_finalize_step(self):
        store = AgentStepStore(session_id="sess-1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")

        store.finalize_step(step, final_answer="The file contains 42 lines.")

        assert step.status == "final"
        assert step.phase == "final"
        assert step.final_answer == "The file contains 42 lines."

    def test_finalize_step_after_observed(self):
        store = AgentStepStore(session_id="sess-1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="read_file")
        store.update_step_after_tool(step, observation="contents")

        store.finalize_step(step, final_answer="Done")

        assert step.status == "final"

    def test_mark_error(self):
        store = AgentStepStore(session_id="sess-1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")

        store.mark_error(step, error="LLM timeout")

        assert step.status == "error"
        assert step.phase == "error"
        assert step.error == "LLM timeout"

    def test_mark_error_after_parse(self):
        store = AgentStepStore(session_id="sess-1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="bad_tool")

        store.mark_error(step, error="tool not found")

        assert step.status == "error"
        assert step.action_name == "bad_tool"


# ---------------------------------------------------------------------------
# Store queries
# ---------------------------------------------------------------------------


class TestStoreQueries:
    def test_load_steps_empty(self):
        store = AgentStepStore(session_id="sess-1")
        assert store.load_steps() == []

    def test_load_steps_order(self):
        store = AgentStepStore(session_id="sess-1")
        s0 = store.create_step(iteration=0, mode="act", runner_type="cot")
        s1 = store.create_step(iteration=1, mode="act", runner_type="cot")
        s2 = store.create_step(iteration=2, mode="act", runner_type="cot")

        steps = store.load_steps()
        assert len(steps) == 3
        assert steps[0] is s0
        assert steps[1] is s1
        assert steps[2] is s2

    def test_steps_for_iteration(self):
        store = AgentStepStore(session_id="sess-1")
        store.create_step(iteration=0, mode="act", runner_type="cot")
        s1 = store.create_step(iteration=1, mode="act", runner_type="cot")
        store.create_step(iteration=2, mode="act", runner_type="cot")

        result = store.steps_for_iteration(1)
        assert len(result) == 1
        assert result[0] is s1

    def test_last_step(self):
        store = AgentStepStore(session_id="sess-1")
        assert store.last_step() is None

        s0 = store.create_step(iteration=0, mode="act", runner_type="cot")
        assert store.last_step() is s0

        s1 = store.create_step(iteration=1, mode="act", runner_type="cot")
        assert store.last_step() is s1

    def test_load_steps_returns_copy(self):
        store = AgentStepStore(session_id="sess-1")
        store.create_step(iteration=0, mode="act", runner_type="cot")

        steps = store.load_steps()
        steps.clear()

        assert len(store.load_steps()) == 1

    def test_session_id_property(self):
        store = AgentStepStore(session_id="test-session-42")
        assert store.session_id == "test-session-42"
