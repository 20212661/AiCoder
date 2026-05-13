"""Tests for event replay builders (v1.4 Phase 4)."""
import pytest

from aicoder.events.replay import (
    replay_llm_view,
    replay_runtime_view,
    replay_verification_trace,
)
from aicoder.events.types import AgentEventRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(event_id, iteration, kind, payload, session_id="replay-test"):
    return AgentEventRecord(
        event_id=event_id,
        session_id=session_id,
        iteration=iteration,
        kind=kind,
        payload=payload,
    )


def _make_full_step_events(iteration=0, step_id="step-1", mode="act",
                            runner_type="cot", tool_name="read_file",
                            observation="ok"):
    """Generate a complete step lifecycle event sequence."""
    return [
        _make_event(f"ev-start-{iteration}", iteration, "step_started",
                    {"step_id": step_id, "mode": mode, "runner_type": runner_type}),
        _make_event(f"ev-thought-{iteration}", iteration, "assistant_thought",
                    {"step_id": step_id, "thought": f"Thinking step {iteration}"}),
        _make_event(f"ev-call-{iteration}", iteration, "tool_call",
                    {"step_id": step_id, "tool_name": tool_name,
                     "tool_input": {"path": f"/tmp/f{iteration}.py"}}),
        _make_event(f"ev-result-{iteration}", iteration, "tool_result",
                    {"step_id": step_id, "observation": observation,
                     "files": [f"/tmp/f{iteration}.py"]}),
        _make_event(f"ev-finish-{iteration}", iteration, "step_finished",
                    {"step_id": step_id, "final_answer": f"Done step {iteration}"}),
    ]


# ---------------------------------------------------------------------------
# replay_runtime_view
# ---------------------------------------------------------------------------


class TestReplayRuntimeView:
    def test_empty_events(self):
        assert replay_runtime_view([]) == []

    def test_single_step(self):
        events = _make_full_step_events(iteration=0)
        result = replay_runtime_view(events)

        assert len(result) == 1
        step = result[0]
        assert step["iteration"] == 0
        assert step["status"] == "final"
        assert step["thought"] == "Thinking step 0"
        assert step["action"]["tool_name"] == "read_file"
        assert step["observation"]["output"] == "ok"
        assert step["final_answer"] == "Done step 0"

    def test_multiple_steps(self):
        events = []
        for i in range(3):
            events.extend(_make_full_step_events(iteration=i, step_id=f"step-{i}"))

        result = replay_runtime_view(events)
        assert len(result) == 3
        assert result[0]["iteration"] == 0
        assert result[2]["iteration"] == 2

    def test_tool_error_step(self):
        events = [
            _make_event("e1", 0, "step_started", {"step_id": "s1", "mode": "act", "runner_type": "cot"}),
            _make_event("e2", 0, "tool_call", {"step_id": "s1", "tool_name": "write_file", "tool_input": {}}),
            _make_event("e3", 0, "tool_error", {"step_id": "s1", "error": "permission denied"}),
        ]
        result = replay_runtime_view(events)
        assert len(result) == 1
        assert result[0]["status"] == "error"
        assert result[0]["observation"]["error"] == "permission denied"

    def test_partial_step_no_observation(self):
        events = [
            _make_event("e1", 0, "step_started", {"step_id": "s1", "mode": "act", "runner_type": "cot"}),
            _make_event("e2", 0, "tool_call", {"step_id": "s1", "tool_name": "read_file", "tool_input": {}}),
        ]
        result = replay_runtime_view(events)
        assert len(result) == 1
        assert result[0]["status"] == "parsed"

    def test_step_with_tool_meta(self):
        events = [
            _make_event("e1", 0, "step_started", {"step_id": "s1", "mode": "act", "runner_type": "cot"}),
            _make_event("e2", 0, "tool_call", {"step_id": "s1", "tool_name": "read_file", "tool_input": {}}),
            _make_event("e3", 0, "tool_result", {
                "step_id": "s1", "observation": "file content",
                "tool_meta": {"success": True, "duration_ms": 50},
            }),
        ]
        result = replay_runtime_view(events)
        obs = result[0]["observation"]
        assert obs["tool_meta"]["success"] is True
        assert obs["success"] is True


# ---------------------------------------------------------------------------
# replay_llm_view
# ---------------------------------------------------------------------------


class TestReplayLlmView:
    def test_empty_events_returns_done_messages(self):
        done = [{"role": "user", "content": "hello"}]
        result = replay_llm_view([], done)
        assert result == done

    def test_cot_tool_result(self):
        events = [
            _make_event("e1", 0, "tool_call", {"step_id": "s1", "tool_name": "read_file", "tool_input": {}}),
            _make_event("e2", 0, "tool_result", {"step_id": "s1", "observation": "file content"}),
        ]
        result = replay_llm_view(events, [], runner_type="cot")
        # Should have assistant + user message pair
        assert any(m["role"] == "assistant" for m in result)
        assert any(m["role"] == "user" and "read_file" in m.get("content", "") for m in result)

    def test_fc_tool_result(self):
        events = [
            _make_event("e1", 0, "tool_call",
                        {"step_id": "s1", "tool_name": "read_file", "tool_input": {},
                         "tool_call_id": "tc_001"}),
            _make_event("e2", 0, "tool_result",
                        {"step_id": "s1", "observation": "file content"}),
        ]
        result = replay_llm_view(events, [], runner_type="function-calling")
        # Should have assistant with tool_calls + tool message
        assistant = [m for m in result if m["role"] == "assistant"]
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(assistant) >= 1
        assert len(tool_msgs) >= 1
        assert tool_msgs[0]["tool_call_id"] == "tc_001"

    def test_tool_error_cot(self):
        events = [
            _make_event("e1", 0, "tool_call", {"step_id": "s1", "tool_name": "write_file", "tool_input": {}}),
            _make_event("e2", 0, "tool_error", {"step_id": "s1", "error": "disk full"}),
        ]
        result = replay_llm_view(events, [], runner_type="cot")
        error_msgs = [m for m in result if "Error" in m.get("content", "")]
        assert len(error_msgs) >= 1
        assert "disk full" in error_msgs[0]["content"]

    def test_tool_error_fc(self):
        events = [
            _make_event("e1", 0, "tool_call",
                        {"step_id": "s1", "tool_name": "write_file", "tool_input": {},
                         "tool_call_id": "tc_002"}),
            _make_event("e2", 0, "tool_error",
                        {"step_id": "s1", "error": "permission denied"}),
        ]
        result = replay_llm_view(events, [], runner_type="function-calling")
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) >= 1
        assert "permission denied" in tool_msgs[0]["content"]

    def test_done_messages_preserved(self):
        done = [{"role": "user", "content": "original"}]
        events = [
            _make_event("e1", 0, "tool_call", {"step_id": "s1", "tool_name": "read_file", "tool_input": {}}),
            _make_event("e2", 0, "tool_result", {"step_id": "s1", "observation": "ok"}),
        ]
        result = replay_llm_view(events, done, runner_type="cot")
        assert result[0]["content"] == "original"
        assert len(result) > 1  # done messages + replay messages

    def test_cot_with_thought(self):
        events = [
            _make_event("e1", 0, "assistant_thought", {"step_id": "s1", "thought": "I should read the file"}),
            _make_event("e2", 0, "tool_call", {"step_id": "s1", "tool_name": "read_file", "tool_input": {}}),
            _make_event("e3", 0, "tool_result", {"step_id": "s1", "observation": "contents"}),
        ]
        result = replay_llm_view(events, [], runner_type="cot")
        # The assistant message for the tool_call should include the thought
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        assert "I should read the file" in assistant_msgs[0]["content"]


# ---------------------------------------------------------------------------
# Cross-format: same events produce both views
# ---------------------------------------------------------------------------


class TestReplayCrossFormat:
    def test_runtime_and_llm_from_same_events(self):
        events = _make_full_step_events(iteration=0, step_id="s1")

        runtime = replay_runtime_view(events)
        llm = replay_llm_view(events, [], runner_type="cot")

        assert len(runtime) == 1
        assert runtime[0]["status"] == "final"
        assert len(llm) > 0

    def test_fc_and_cot_produce_different_formats(self):
        events = _make_full_step_events(iteration=0, step_id="s1")

        cot_result = replay_llm_view(events, [], runner_type="cot")
        fc_result = replay_llm_view(events, [], runner_type="function-calling")

        # CoT should have user messages with [tool] prefix
        cot_users = [m for m in cot_result if m["role"] == "user"]
        assert any("[" in m["content"] for m in cot_users)


# ---------------------------------------------------------------------------
# replay_verification_trace (v1.6 Phase 4)
# ---------------------------------------------------------------------------


def _make_verification_events(
    iteration: int = 0,
    results: list[dict] | None = None,
    decisions: list[dict] | None = None,
    all_passed: bool = True,
):
    """Generate a complete verification event sequence."""
    events = [
        _make_event(f"vstart-{iteration}", iteration, "verification_started", {
            "task_count": len(results) if results else 0,
            "changed_files": ["test.py"],
            "mode": "act",
        }),
    ]
    for idx, result in enumerate(results or []):
        events.append(
            _make_event(f"vresult-{iteration}-{idx}", iteration, "verification_result", result),
        )
    for idx, decision in enumerate(decisions or []):
        events.append(
            _make_event(f"vdecision-{iteration}-{idx}", iteration, "recovery_decision", decision),
        )
    pass_count = sum(1 for r in (results or []) if r.get("status") == "passed")
    fail_count = sum(1 for r in (results or []) if r.get("status") == "failed")
    events.append(
        _make_event(f"vfinish-{iteration}", iteration, "verification_finished", {
            "all_passed": all_passed,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "error_count": 0,
        }),
    )
    return events


class TestReplayVerificationTrace:
    def test_empty_events(self):
        assert replay_verification_trace([]) == []

    def test_single_passing_round(self):
        events = _make_verification_events(
            iteration=1,
            results=[
                {"task_id": "syntax_check", "status": "passed", "exit_code": 0},
            ],
            all_passed=True,
        )
        trace = replay_verification_trace(events)
        assert len(trace) == 1
        assert trace[0]["iteration"] == 1
        assert trace[0]["all_passed"] is True
        assert trace[0]["pass_count"] == 1
        assert len(trace[0]["results"]) == 1
        assert trace[0]["results"][0]["task_id"] == "syntax_check"

    def test_failing_round_with_recovery(self):
        events = _make_verification_events(
            iteration=0,
            results=[
                {"task_id": "lint", "status": "failed", "exit_code": 1},
            ],
            decisions=[
                {"action": "retry", "reason": "Retryable error", "next_hint": "check syntax"},
            ],
            all_passed=False,
        )
        trace = replay_verification_trace(events)
        assert len(trace) == 1
        assert trace[0]["all_passed"] is False
        assert trace[0]["fail_count"] == 1
        assert len(trace[0]["decisions"]) == 1
        assert trace[0]["decisions"][0]["action"] == "retry"

    def test_multiple_iterations(self):
        events = []
        events.extend(_make_verification_events(
            iteration=0,
            results=[{"task_id": "syntax_check", "status": "passed"}],
            all_passed=True,
        ))
        events.extend(_make_verification_events(
            iteration=1,
            results=[{"task_id": "lint", "status": "failed"}],
            decisions=[{"action": "halt", "reason": "exhausted"}],
            all_passed=False,
        ))
        trace = replay_verification_trace(events)
        assert len(trace) == 2
        assert trace[0]["iteration"] == 0
        assert trace[1]["iteration"] == 1

    def test_mixed_events_with_step_events(self):
        """Verification events coexist with step events."""
        events = _make_full_step_events(iteration=0, step_id="s1")
        events.extend(_make_verification_events(
            iteration=0,
            results=[{"task_id": "syntax_check", "status": "passed"}],
            all_passed=True,
        ))
        trace = replay_verification_trace(events)
        assert len(trace) == 1
        assert trace[0]["all_passed"] is True

    def test_verification_started_without_finished(self):
        """Handles partial verification (started but not finished)."""
        events = [
            _make_event("vs", 0, "verification_started", {
                "task_count": 1, "changed_files": ["a.py"], "mode": "act",
            }),
            _make_event("vr", 0, "verification_result", {
                "task_id": "lint", "status": "failed", "exit_code": 1,
            }),
        ]
        trace = replay_verification_trace(events)
        assert len(trace) == 1
        assert trace[0].get("finished") is not True
        assert len(trace[0]["results"]) == 1
