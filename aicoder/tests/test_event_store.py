"""Tests for AgentEventStore and event emission from AgentStepStore lifecycle."""

import pytest

from aicoder.agent_step_store import AgentStep, AgentStepStore
from aicoder.events.store import AgentEventStore
from aicoder.events.types import AgentEventRecord, EventKind


# ---------------------------------------------------------------------------
# AgentEventStore basics
# ---------------------------------------------------------------------------


class TestEventStoreBasics:
    def test_append_returns_record(self):
        store = AgentEventStore(session_id="sess-1")
        rec = store.append(iteration=0, kind="step_started", payload={"mode": "act"})

        assert isinstance(rec, AgentEventRecord)
        assert rec.session_id == "sess-1"
        assert rec.iteration == 0
        assert rec.kind == "step_started"
        assert rec.payload == {"mode": "act"}
        assert len(rec.event_id) > 0
        assert rec.created_at > 0

    def test_append_many(self):
        store = AgentEventStore(session_id="sess-1")
        records = [
            AgentEventRecord(event_id="e1", session_id="sess-1", iteration=0, kind="step_started"),
            AgentEventRecord(event_id="e2", session_id="sess-1", iteration=0, kind="tool_call"),
        ]
        store.append_many(records)
        assert len(store.all_events()) == 2

    def test_list_events_all(self):
        store = AgentEventStore(session_id="s")
        store.append(iteration=0, kind="step_started")
        store.append(iteration=0, kind="tool_call")
        store.append(iteration=1, kind="step_started")

        assert len(store.list_events()) == 3

    def test_list_events_filter_kind(self):
        store = AgentEventStore(session_id="s")
        store.append(iteration=0, kind="step_started")
        store.append(iteration=0, kind="tool_call")
        store.append(iteration=1, kind="step_started")

        result = store.list_events(kind="step_started")
        assert len(result) == 2
        assert all(e.kind == "step_started" for e in result)

    def test_list_events_filter_iteration(self):
        store = AgentEventStore(session_id="s")
        store.append(iteration=0, kind="step_started")
        store.append(iteration=1, kind="step_started")
        store.append(iteration=1, kind="tool_call")

        result = store.list_events(iteration=1)
        assert len(result) == 2

    def test_list_events_limit(self):
        store = AgentEventStore(session_id="s")
        for i in range(10):
            store.append(iteration=i, kind="step_started")

        result = store.list_events(limit=3)
        assert len(result) == 3
        # Should return the last 3
        assert result[0].iteration == 7
        assert result[2].iteration == 9

    def test_events_for_iteration(self):
        store = AgentEventStore(session_id="s")
        store.append(iteration=0, kind="step_started")
        store.append(iteration=1, kind="step_started")
        store.append(iteration=1, kind="tool_call")
        store.append(iteration=2, kind="step_started")

        result = store.events_for_iteration(1)
        assert len(result) == 2

    def test_last_event(self):
        store = AgentEventStore(session_id="s")
        assert store.last_event() is None

        store.append(iteration=0, kind="step_started")
        store.append(iteration=0, kind="tool_call")
        store.append(iteration=0, kind="tool_result")

        last = store.last_event()
        assert last.kind == "tool_result"

    def test_last_event_filtered(self):
        store = AgentEventStore(session_id="s")
        store.append(iteration=0, kind="step_started")
        store.append(iteration=0, kind="tool_call")
        store.append(iteration=0, kind="tool_result")
        store.append(iteration=0, kind="step_finished")

        last_tc = store.last_event(kind="tool_call")
        assert last_tc is not None
        assert last_tc.kind == "tool_call"

        last_sr = store.last_event(kind="step_started")
        assert last_sr is not None
        assert last_sr.kind == "step_started"

    def test_last_event_missing_kind(self):
        store = AgentEventStore(session_id="s")
        store.append(iteration=0, kind="step_started")
        assert store.last_event(kind="tool_error") is None

    def test_session_id_property(self):
        store = AgentEventStore(session_id="test-session-42")
        assert store.session_id == "test-session-42"


# ---------------------------------------------------------------------------
# Step lifecycle produces events
# ---------------------------------------------------------------------------


class TestStepLifecycleEvents:
    def test_create_step_emits_step_started(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")

        events = step_store.event_store.list_events(kind="step_started")
        assert len(events) == 1
        assert events[0].payload["step_id"] == step.id
        assert events[0].payload["mode"] == "act"
        assert events[0].payload["runner_type"] == "cot"

    def test_parse_with_thought_emits_assistant_thought(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step,
            thought="I should read the file",
            action_name="read_file",
            action_input={"path": "/tmp/a.py"},
        )

        thought_events = step_store.event_store.list_events(kind="assistant_thought")
        assert len(thought_events) == 1
        assert thought_events[0].payload["thought"] == "I should read the file"

    def test_parse_with_action_emits_tool_call(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step,
            thought="thinking",
            action_name="read_file",
            action_input={"path": "/tmp/a.py"},
        )

        tc_events = step_store.event_store.list_events(kind="tool_call")
        assert len(tc_events) == 1
        assert tc_events[0].payload["tool_name"] == "read_file"
        assert tc_events[0].payload["tool_input"] == {"path": "/tmp/a.py"}

    def test_parse_without_action_no_tool_call_event(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, thought="just thinking")

        assert step_store.event_store.list_events(kind="tool_call") == []
        # But thought should still be emitted
        assert len(step_store.event_store.list_events(kind="assistant_thought")) == 1

    def test_tool_success_emits_tool_result(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, action_name="read_file")
        step_store.update_step_after_tool(
            step,
            observation="file contents here",
            tool_meta={"duration_ms": 100},
            files=["/tmp/a.py"],
        )

        result_events = step_store.event_store.list_events(kind="tool_result")
        assert len(result_events) == 1
        assert result_events[0].payload["observation"] == "file contents here"
        assert result_events[0].payload["files"] == ["/tmp/a.py"]
        assert result_events[0].payload["tool_meta"] == {"duration_ms": 100}

        # No tool_error event
        assert step_store.event_store.list_events(kind="tool_error") == []

    def test_tool_error_emits_tool_error_event(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, action_name="bad_tool")
        step_store.update_step_after_tool(
            step,
            observation="permission denied",
            tool_error=True,
        )

        error_events = step_store.event_store.list_events(kind="tool_error")
        assert len(error_events) == 1
        assert error_events[0].payload["observation"] == "permission denied"

        # No tool_result event
        assert step_store.event_store.list_events(kind="tool_result") == []

    def test_finalize_emits_step_finished(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.finalize_step(step, final_answer="Done")

        finished_events = step_store.event_store.list_events(kind="step_finished")
        assert len(finished_events) == 1
        assert finished_events[0].payload["final_answer"] == "Done"

    def test_mark_error_emits_tool_error(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.mark_error(step, error="LLM timeout")

        error_events = step_store.event_store.list_events(kind="tool_error")
        assert len(error_events) == 1
        assert error_events[0].payload["error"] == "LLM timeout"


# ---------------------------------------------------------------------------
# Full lifecycle event sequence
# ---------------------------------------------------------------------------


class TestFullLifecycleSequence:
    def test_complete_step_event_sequence(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step,
            thought="read the file",
            action_name="read_file",
            action_input={"path": "/tmp/a.py"},
        )
        step_store.update_step_after_tool(
            step,
            observation="contents",
            tool_meta={"success": True},
        )
        step_store.finalize_step(step, final_answer="The file has 42 lines.")

        events = step_store.event_store.all_events()
        kinds = [e.kind for e in events]

        assert kinds == [
            "step_started",
            "assistant_thought",
            "tool_call",
            "tool_result",
            "step_finished",
        ]

    def test_error_step_event_sequence(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, action_name="bad_tool")
        step_store.update_step_after_tool(
            step, observation="not found", tool_error=True,
        )

        events = step_store.event_store.all_events()
        kinds = [e.kind for e in events]

        assert "step_started" in kinds
        assert "tool_call" in kinds
        assert "tool_error" in kinds

    def test_multiple_steps_have_correct_iterations(self):
        step_store = AgentStepStore(session_id="s1")

        step0 = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step0, action_name="read_file")
        step_store.update_step_after_tool(step0, observation="ok")

        step1 = step_store.create_step(iteration=1, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step1, action_name="write_file")
        step_store.update_step_after_tool(step1, observation="written")

        iter0_events = step_store.event_store.events_for_iteration(0)
        iter1_events = step_store.event_store.events_for_iteration(1)

        assert len(iter0_events) >= 3  # started + tool_call + tool_result
        assert len(iter1_events) >= 3
        assert all(e.iteration == 0 for e in iter0_events)
        assert all(e.iteration == 1 for e in iter1_events)


# ---------------------------------------------------------------------------
# Multi tool_call events
# ---------------------------------------------------------------------------


class TestMultiToolCallEvents:
    def test_additional_tool_call_events_via_event_store(self):
        """Simulate what FC runner does: first tool_call via update_step_after_parse,
        additional tool_calls emitted directly to event_store."""
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="function-calling")

        # First tool call via standard parse path
        step_store.update_step_after_parse(
            step,
            action_name="read_file",
            action_input={"path": "/tmp/a.py"},
        )
        # Additional tool calls emitted directly (as FC runner does)
        step_store.event_store.append(
            iteration=step.iteration,
            kind="tool_call",
            payload={
                "step_id": step.id,
                "tool_name": "write_file",
                "tool_input": {"path": "/tmp/b.py", "content": "hello"},
            },
        )
        step_store.event_store.append(
            iteration=step.iteration,
            kind="tool_call",
            payload={
                "step_id": step.id,
                "tool_name": "run_command",
                "tool_input": {"command": "python /tmp/b.py"},
            },
        )

        tc_events = step_store.event_store.list_events(kind="tool_call")
        assert len(tc_events) == 3
        assert tc_events[0].payload["tool_name"] == "read_file"
        assert tc_events[1].payload["tool_name"] == "write_file"
        assert tc_events[2].payload["tool_name"] == "run_command"


# ---------------------------------------------------------------------------
# Payload structure validation
# ---------------------------------------------------------------------------


class TestPayloadStructure:
    def test_step_started_payload_fields(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="plan", runner_type="function-calling")

        event = step_store.event_store.last_event(kind="step_started")
        assert "step_id" in event.payload
        assert "mode" in event.payload
        assert "runner_type" in event.payload

    def test_tool_call_payload_has_tool_name_and_input(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step,
            action_name="read_file",
            action_input={"path": "/tmp/test.py"},
        )

        event = step_store.event_store.last_event(kind="tool_call")
        assert event.payload["tool_name"] == "read_file"
        assert isinstance(event.payload["tool_input"], dict)
        assert event.payload["tool_input"] == {"path": "/tmp/test.py"}

    def test_tool_result_payload_has_observation(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, action_name="read_file")
        step_store.update_step_after_tool(
            step,
            observation="contents",
            tool_meta={"duration_ms": 50},
            files=["/tmp/test.py"],
        )

        event = step_store.event_store.last_event(kind="tool_result")
        assert "observation" in event.payload
        assert "tool_meta" in event.payload
        assert "files" in event.payload

    def test_step_finished_payload_has_final_answer(self):
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.finalize_step(step, final_answer="All done.")

        event = step_store.event_store.last_event(kind="step_finished")
        assert event.payload["final_answer"] == "All done."

    def test_payload_not_single_string(self):
        """Ensure payloads are structured dicts, not raw strings."""
        step_store = AgentStepStore(session_id="s1")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step,
            thought="analyzing",
            action_name="list_files",
            action_input={"path": "."},
        )

        for event in step_store.event_store.all_events():
            assert isinstance(event.payload, dict)
            # No key should have the entire event as a single big string
            for val in event.payload.values():
                if isinstance(val, str):
                    assert len(val) < 2000  # not a giant blob


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_step_store_without_explicit_event_store(self):
        """AgentStepStore still works without passing an explicit event_store."""
        store = AgentStepStore(session_id="auto")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        assert store.event_store is not None
        assert store.event_store.session_id == "auto"

    def test_step_store_with_external_event_store(self):
        """AgentStepStore can accept an external event_store."""
        es = AgentEventStore(session_id="ext")
        store = AgentStepStore(session_id="ext", event_store=es)
        assert store.event_store is es

    def test_existing_step_store_tests_still_pass(self):
        """Verify existing step creation behavior is unchanged."""
        store = AgentStepStore(session_id="sess-1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")

        assert step.session_id == "sess-1"
        assert step.iteration == 0
        assert step.mode == "act"
        assert step.runner_type == "cot"
        assert step.status == "created"

        store.update_step_after_parse(step, action_name="read_file")
        assert step.status == "parsed"

        store.update_step_after_tool(step, observation="ok")
        assert step.status == "observed"

        store.finalize_step(step, final_answer="done")
        assert step.status == "final"


# ---------------------------------------------------------------------------
# v1.2.1: mark_error produces unified tool_error payload
# ---------------------------------------------------------------------------


class TestMarkErrorUnifiedPayload:
    def test_mark_error_has_tool_meta(self):
        store = AgentStepStore(session_id="s1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.mark_error(step, error="LLM timeout")

        event = store.event_store.last_event(kind="tool_error")
        assert "tool_meta" in event.payload
        meta = event.payload["tool_meta"]
        assert meta["success"] is False

    def test_mark_error_tool_meta_has_tool_name(self):
        store = AgentStepStore(session_id="s1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="read_file")
        store.mark_error(step, error="file not found")

        event = store.event_store.last_event(kind="tool_error")
        meta = event.payload["tool_meta"]
        assert meta["tool_name"] == "read_file"

    def test_mark_error_tool_meta_unknown_when_no_action(self):
        store = AgentStepStore(session_id="s1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.mark_error(step, error="LLM timeout")

        event = store.event_store.last_event(kind="tool_error")
        meta = event.payload["tool_meta"]
        assert meta["tool_name"] == "unknown"

    def test_mark_error_has_error_type(self):
        store = AgentStepStore(session_id="s1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.mark_error(step, error="LLM timeout")

        event = store.event_store.last_event(kind="tool_error")
        meta = event.payload["tool_meta"]
        assert meta["error_type"] == "step_error"

    def test_mark_error_has_summary(self):
        store = AgentStepStore(session_id="s1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.mark_error(step, error="LLM timeout")

        event = store.event_store.last_event(kind="tool_error")
        meta = event.payload["tool_meta"]
        assert "summary" in meta
        assert "LLM timeout" in meta["summary"]

    def test_mark_error_has_recommended_next(self):
        store = AgentStepStore(session_id="s1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.mark_error(step, error="LLM timeout")

        event = store.event_store.last_event(kind="tool_error")
        meta = event.payload["tool_meta"]
        assert "recommended_next" in meta
        assert isinstance(meta["recommended_next"], str)
        assert len(meta["recommended_next"]) > 0

    def test_mark_error_has_files_list(self):
        store = AgentStepStore(session_id="s1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.mark_error(step, error="crash")

        event = store.event_store.last_event(kind="tool_error")
        meta = event.payload["tool_meta"]
        assert "files" in meta
        assert isinstance(meta["files"], list)

    def test_mark_error_reuses_step_files(self):
        store = AgentStepStore(session_id="s1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.update_step_after_parse(step, action_name="write_file")
        store.update_step_after_tool(step, observation="written", files=["/tmp/a.py", "/tmp/b.py"])
        store.mark_error(step, error="verify failed")

        event = store.event_store.last_event(kind="tool_error")
        meta = event.payload["tool_meta"]
        assert "/tmp/a.py" in meta["files"]
        assert "/tmp/b.py" in meta["files"]

    def test_mark_error_payload_still_has_step_id_and_error(self):
        store = AgentStepStore(session_id="s1")
        step = store.create_step(iteration=0, mode="act", runner_type="cot")
        store.mark_error(step, error="bad input")

        event = store.event_store.last_event(kind="tool_error")
        assert event.payload["step_id"] == step.id
        assert event.payload["error"] == "bad input"
