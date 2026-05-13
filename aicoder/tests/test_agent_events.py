"""Tests for StepEvent and emit_step_event."""

from unittest.mock import MagicMock

import pytest

from aicoder.agent_events import StepEvent, emit_step_event


# ---------------------------------------------------------------------------
# StepEvent creation
# ---------------------------------------------------------------------------


class TestStepEvent:
    def test_creation(self):
        event = StepEvent(
            type="agent.step.created",
            step_id="step-1",
            iteration=0,
        )
        assert event.type == "agent.step.created"
        assert event.step_id == "step-1"
        assert event.iteration == 0
        assert event.data == {}

    def test_creation_with_data(self):
        event = StepEvent(
            type="agent.step.action",
            step_id="step-2",
            iteration=1,
            data={"action_name": "read_file", "action_input": {"path": "/tmp/a.py"}},
        )
        assert event.data["action_name"] == "read_file"

    @pytest.mark.parametrize(
        "event_type",
        [
            "agent.step.created",
            "agent.step.thought",
            "agent.step.action",
            "agent.step.observation",
            "agent.step.final",
            "agent.step.error",
        ],
    )
    def test_all_event_types(self, event_type):
        event = StepEvent(type=event_type, step_id="s", iteration=0)
        assert event.type == event_type


# ---------------------------------------------------------------------------
# emit_step_event — RPC path (has _notify)
# ---------------------------------------------------------------------------


class TestEmitRpc:
    def test_rpc_notify_called(self):
        io = MagicMock()
        event = StepEvent(
            type="agent.step.created",
            step_id="step-1",
            iteration=0,
            data={"mode": "act"},
        )

        emit_step_event(io, event)

        io._notify.assert_called_once_with("agent/step", {
            "type": "agent.step.created",
            "step_id": "step-1",
            "iteration": 0,
            "data": {"mode": "act"},
        })

    def test_rpc_notify_with_empty_data(self):
        io = MagicMock()
        event = StepEvent(
            type="agent.step.thought",
            step_id="step-2",
            iteration=1,
        )

        emit_step_event(io, event)

        io._notify.assert_called_once()
        call_args = io._notify.call_args
        assert call_args[0][0] == "agent/step"
        assert call_args[0][1]["data"] == {}


# ---------------------------------------------------------------------------
# emit_step_event — CLI fallback (no _notify)
# ---------------------------------------------------------------------------


class TestEmitCli:
    def test_cli_error_event(self):
        io = MagicMock(spec=["tool_error", "tool_output", "print_assistant_output"])
        event = StepEvent(
            type="agent.step.error",
            step_id="step-1",
            iteration=0,
            data={"error": "something went wrong"},
        )

        emit_step_event(io, event)

        io.tool_error.assert_called_once_with("something went wrong")

    def test_cli_final_event(self):
        io = MagicMock(spec=["tool_error", "tool_output", "print_assistant_output"])
        event = StepEvent(
            type="agent.step.final",
            step_id="step-1",
            iteration=2,
            data={"final_answer": "The file has 42 lines."},
        )

        emit_step_event(io, event)

        io.print_assistant_output.assert_called_once_with("The file has 42 lines.")

    def test_cli_thought_event(self):
        io = MagicMock(spec=["tool_error", "tool_output", "print_assistant_output"])
        event = StepEvent(
            type="agent.step.thought",
            step_id="step-1",
            iteration=0,
            data={"thought": "I should read the file first."},
        )

        emit_step_event(io, event)

        io.tool_output.assert_called_once_with("[thought] I should read the file first.")

    def test_cli_observation_event(self):
        io = MagicMock(spec=["tool_error", "tool_output", "print_assistant_output"])
        event = StepEvent(
            type="agent.step.observation",
            step_id="step-1",
            iteration=1,
            data={"observation": "file contents here"},
        )

        emit_step_event(io, event)

        io.tool_output.assert_called_once_with("[observation] file contents here")

    def test_cli_created_event_no_text(self):
        io = MagicMock(spec=["tool_error", "tool_output", "print_assistant_output"])
        event = StepEvent(
            type="agent.step.created",
            step_id="step-1",
            iteration=0,
        )

        emit_step_event(io, event)

        # No text to display, should not call tool_output
        io.tool_output.assert_not_called()
