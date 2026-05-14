"""Tests for Condensation Pipeline — prune, summarize, replace."""

import pytest

from aicoder.agent_step_store import AgentStepStore
from aicoder.context.condense import (
    CondensedBlock,
    prune_history_events,
    summarize_history_events,
    apply_condensation_to_history_view,
    _PRUNE_OBSERVATION_MAX,
)
from aicoder.context.summary_types import SummaryBlock
from aicoder.events.types import AgentEventRecord
from aicoder.events.store import AgentEventStore


# ---------------------------------------------------------------------------
# Helpers to build event fixtures
# ---------------------------------------------------------------------------


def _make_event(
    event_id: str = "ev-0",
    iteration: int = 0,
    kind: str = "tool_result",
    payload: dict | None = None,
) -> AgentEventRecord:
    return AgentEventRecord(
        event_id=event_id,
        session_id="s1",
        iteration=iteration,
        kind=kind,
        payload=payload or {},
    )


def _make_many_events(count: int) -> list[AgentEventRecord]:
    """Build a realistic sequence of events across multiple iterations."""
    store = AgentEventStore(session_id="s1")
    step_store = AgentStepStore(session_id="s1")

    for i in range(count):
        step = step_store.create_step(iteration=i, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step,
            thought=f"Thinking about step {i}",
            action_name="read_file",
            action_input={"path": f"/tmp/file{i}.py"},
        )
        obs = "x" * 500 if i % 3 == 0 else f"contents of file {i}"
        step_store.update_step_after_tool(
            step,
            observation=obs,
            tool_meta={"success": True, "tool_name": "read_file"},
            files=[f"/tmp/file{i}.py"],
        )

    return step_store.event_store.all_events()


def _make_events_with_errors() -> list[AgentEventRecord]:
    """Build events that include tool_error events."""
    store = AgentEventStore(session_id="s1")
    step_store = AgentStepStore(session_id="s1")

    # Step 0: successful read
    step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
    step_store.update_step_after_parse(step, thought="read file", action_name="read_file", action_input={"path": "a.py"})
    step_store.update_step_after_tool(step, observation="ok", tool_meta={"success": True})

    # Step 1: failed write
    step = step_store.create_step(iteration=1, mode="act", runner_type="cot")
    step_store.update_step_after_parse(step, thought="write file", action_name="write_file", action_input={"path": "b.py"})
    step_store.update_step_after_tool(step, observation="permission denied", tool_error=True)

    return step_store.event_store.all_events()


# ---------------------------------------------------------------------------
# Prune tests
# ---------------------------------------------------------------------------


class TestPrune:
    def test_prune_truncates_long_observation(self):
        long_obs = "a" * 600
        events = [
            _make_event("ev-1", kind="tool_result", payload={
                "observation": long_obs,
                "tool_name": "read_file",
                "tool_meta": {"success": True},
            }),
        ]
        pruned = prune_history_events(events, "act")
        assert len(pruned) == 1
        obs = pruned[0].payload.get("observation", "")
        assert len(obs) <= _PRUNE_OBSERVATION_MAX + 3  # +3 for "..."
        assert pruned[0].payload.get("observation_truncated") is True

    def test_prune_preserves_short_observation(self):
        short_obs = "file contents here"
        events = [
            _make_event("ev-1", kind="tool_result", payload={
                "observation": short_obs,
                "tool_name": "read_file",
            }),
        ]
        pruned = prune_history_events(events, "act")
        assert pruned[0].payload["observation"] == short_obs
        assert "observation_truncated" not in pruned[0].payload

    def test_prune_keeps_essential_fields(self):
        events = [
            _make_event("ev-1", kind="tool_result", payload={
                "observation": "result",
                "tool_name": "write_file",
                "tool_input": {"path": "a.py"},
                "success": True,
                "files": ["/tmp/a.py"],
                "summary": "wrote the file",
                "recommended_next": "run tests",
                "tool_meta": {"duration_ms": 50},
            }),
        ]
        pruned = prune_history_events(events, "act")
        p = pruned[0].payload
        assert p["tool_name"] == "write_file"
        assert p["success"] is True
        assert p["files"] == ["/tmp/a.py"]
        assert p["summary"] == "wrote the file"
        assert p["recommended_next"] == "run tests"

    def test_prune_does_not_delete_records(self):
        events = _make_many_events(10)
        pruned = prune_history_events(events, "act")
        assert len(pruned) == len(events)

    def test_prune_does_not_mutate_input(self):
        events = [
            _make_event("ev-1", kind="tool_result", payload={
                "observation": "x" * 600,
                "tool_name": "read_file",
            }),
        ]
        original_payload = dict(events[0].payload)
        prune_history_events(events, "act")
        assert events[0].payload == original_payload, "Input should not be mutated"

    def test_prune_non_tool_events_unchanged(self):
        events = [
            _make_event("ev-1", kind="assistant_thought", payload={"thought": "hello"}),
            _make_event("ev-2", kind="step_started", payload={"mode": "act"}),
        ]
        pruned = prune_history_events(events, "act")
        assert pruned[0].payload["thought"] == "hello"
        assert pruned[1].payload["mode"] == "act"


# ---------------------------------------------------------------------------
# Summarize tests
# ---------------------------------------------------------------------------


class TestSummarize:
    def test_empty_events_returns_none(self):
        assert summarize_history_events([]) is None

    def test_produces_condensed_block(self):
        events = _make_many_events(8)
        block = summarize_history_events(events)
        assert block is not None
        # v1.5: now returns SummaryBlock (which has .summary property)
        assert isinstance(block, (CondensedBlock, SummaryBlock))
        assert len(block.summary) > 0
        assert len(block.covered_event_ids) > 0

    def test_summary_contains_goal(self):
        events = [
            _make_event("ev-1", kind="assistant_thought", payload={"thought": "Read the config"}),
            _make_event("ev-2", kind="tool_call", payload={"tool_name": "read_file", "tool_input": {"path": "config.py"}}),
            _make_event("ev-3", kind="tool_result", payload={"observation": "DEBUG=True", "tool_name": "read_file"}),
        ]
        block = summarize_history_events(events)
        assert "Goal:" in block.summary

    def test_summary_contains_actions(self):
        events = [
            _make_event("ev-1", kind="tool_call", payload={"tool_name": "read_file", "tool_input": {"path": "a.py"}}),
            _make_event("ev-2", kind="tool_call", payload={"tool_name": "write_file", "tool_input": {"path": "b.py", "content": "x"}}),
            _make_event("ev-3", kind="tool_result", payload={"observation": "ok"}),
        ]
        block = summarize_history_events(events)
        assert "Actions taken:" in block.summary
        assert "read_file" in block.summary
        assert "write_file" in block.summary

    def test_summary_contains_failures(self):
        events = _make_events_with_errors()
        block = summarize_history_events(events)
        assert "Failures:" in block.summary

    def test_summary_contains_files_touched(self):
        events = [
            _make_event("ev-1", kind="tool_result", payload={
                "observation": "ok", "files": ["/tmp/a.py", "/tmp/b.py"],
            }),
        ]
        block = summarize_history_events(events)
        assert "Files touched:" in block.summary
        assert "/tmp/a.py" in block.summary

    def test_covered_event_ids_match_input(self):
        events = [
            _make_event("ev-1", kind="tool_call", payload={"tool_name": "read_file"}),
            _make_event("ev-2", kind="tool_result", payload={"observation": "ok"}),
        ]
        block = summarize_history_events(events)
        assert block.covered_event_ids == ["ev-1", "ev-2"]

    def test_no_tool_events_no_summary(self):
        events = [
            _make_event("ev-1", kind="step_started", payload={"mode": "act"}),
            _make_event("ev-2", kind="step_finished", payload={}),
        ]
        block = summarize_history_events(events)
        # v1.5: summarizer returns None, fallback creates a minimal block
        # Either None or a minimal block is acceptable
        if block is not None:
            assert len(block.summary) > 0 or len(block.covered_event_ids) > 0


# ---------------------------------------------------------------------------
# Apply condensation tests
# ---------------------------------------------------------------------------


class TestApplyCondensation:
    def test_none_condensed_returns_unchanged(self):
        view = [{"role": "user", "content": "hi"}]
        result = apply_condensation_to_history_view(view, None)
        assert result == view

    def test_empty_history_returns_empty(self):
        result = apply_condensation_to_history_view([], CondensedBlock(
            summary="test", covered_event_ids=["ev-1"],
        ))
        assert result == []

    def test_short_history_not_condensed(self):
        """History <= _KEEP_RECENT_COUNT should not be condensed."""
        view = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "msg4"},
        ]
        result = apply_condensation_to_history_view(view, CondensedBlock(
            summary="summary", covered_event_ids=["ev-1"],
        ))
        # Should be unchanged
        assert len(result) == 4
        assert result == view

    def test_condensation_replaces_older_messages(self):
        view = [
            {"role": "user", "content": f"old msg {i}"}
            for i in range(10)
        ]
        condensed = CondensedBlock(
            summary="This is a summary of previous work.",
            covered_event_ids=["ev-1", "ev-2", "ev-3"],
        )
        result = apply_condensation_to_history_view(view, condensed)

        # Should have summary pair + recent messages
        assert len(result) < len(view)
        assert result[0]["content"] == "[Previous conversation condensed]"
        assert result[1]["content"] == "This is a summary of previous work."
        assert result[1].get("condensed") is True
        assert result[1]["covered_event_ids"] == ["ev-1", "ev-2", "ev-3"]

    def test_recent_messages_preserved(self):
        view = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(10)
        ]
        condensed = CondensedBlock(
            summary="summary", covered_event_ids=["ev-1"],
        )
        result = apply_condensation_to_history_view(view, condensed)

        # Last 4 messages should be preserved exactly
        for i, original_idx in enumerate(range(6, 10)):
            # The recent messages are at the end of result (after summary pair)
            assert result[2 + i]["content"] == f"msg {original_idx}"

    def test_does_not_mutate_input(self):
        view = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        original = list(view)
        condensed = CondensedBlock(summary="s", covered_event_ids=["ev-1"])
        apply_condensation_to_history_view(view, condensed)
        assert view == original, "Input should not be mutated"


# ---------------------------------------------------------------------------
# Integration: condensation through LLM history view
# ---------------------------------------------------------------------------


class TestCondensationViaLLMView:
    def _make_coder_with_long_history(self):
        """Create a coder with enough events to trigger condensation."""
        from unittest.mock import MagicMock
        from pathlib import Path
        from aicoder.runners.cot_agent_runner import CotAgentRunner
        from aicoder.runners import register_runner
        from aicoder.tools.registry import ToolRegistry
        from aicoder.tools.executor import ToolCoordinator, ToolExecutor
        from aicoder.tools.result import ExecutionState

        session_id = "condense-integ-test"
        coder = MagicMock()
        coder.session_id = session_id
        coder.done_messages = []
        for i in range(5):
            coder.done_messages.append({"role": "user", "content": f"question {i}"})
            coder.done_messages.append({"role": "assistant", "content": f"answer {i}"})
        coder.cur_messages = []
        coder.stream = True
        coder.io = MagicMock()

        registry = ToolRegistry()
        coord = ToolCoordinator()
        exec_state = ExecutionState()
        exec_state.mode = "act"
        coder.tool_registry = registry
        coder.tool_coordinator = coord
        coder.tool_exec_state = exec_state
        coder.tool_executor = ToolExecutor(coord, coder, exec_state)

        step_store = AgentStepStore(session_id=session_id)
        # Create 5 steps with long observations
        for i in range(5):
            step = step_store.create_step(iteration=i, mode="act", runner_type="cot")
            step_store.update_step_after_parse(
                step,
                thought=f"Step {i}: analyzing",
                action_name="read_file",
                action_input={"path": f"/tmp/file{i}.py"},
            )
            step_store.update_step_after_tool(
                step,
                observation="x" * 500,
                tool_meta={"success": True, "tool_name": "read_file"},
                files=[f"/tmp/file{i}.py"],
            )

        runner = CotAgentRunner(
            coder=coder, session_id=session_id,
            mode="act", tool_registry=registry, step_store=step_store,
        )
        register_runner(session_id, runner)
        return coder, session_id

    def teardown_method(self):
        from aicoder.runners import unregister_runner
        unregister_runner("condense-integ-test")

    def test_llm_view_applies_condensation(self):
        from aicoder.context.history_view import build_llm_history_view

        coder, _ = self._make_coder_with_long_history()
        view = build_llm_history_view(coder, "act", "cot")

        # Should contain condensed summary
        condensed_msgs = [m for m in view if m.get("condensed")]
        assert len(condensed_msgs) >= 1, "LLM view should contain condensed summary"

    def test_ui_view_not_condensed(self):
        from aicoder.context.history_view import build_ui_history_view

        coder, _ = self._make_coder_with_long_history()
        view = build_ui_history_view(coder, "act", "cot")

        # UI view should NOT have condensed messages
        condensed = [e for e in view if isinstance(e, dict) and e.get("condensed")]
        assert len(condensed) == 0, "UI view should not be condensed"

    def test_runtime_view_not_condensed(self):
        from aicoder.context.history_view import build_runtime_history_view

        coder, _ = self._make_coder_with_long_history()
        view = build_runtime_history_view(coder, "act", "cot")

        # Runtime view should NOT have condensed messages
        condensed = [e for e in view if isinstance(e, dict) and e.get("condensed")]
        assert len(condensed) == 0, "Runtime view should not be condensed"

    def test_original_events_preserved(self):
        """Condensation must not destroy the original events in the store."""
        coder, _ = self._make_coder_with_long_history()

        from aicoder.runners import get_runner
        runner = get_runner("condense-integ-test")
        event_count_before = len(runner.step_store.event_store.all_events())

        from aicoder.context.history_view import build_llm_history_view
        build_llm_history_view(coder, "act", "cot")

        event_count_after = len(runner.step_store.event_store.all_events())
        assert event_count_before == event_count_after, "Original events must be preserved"


# ---------------------------------------------------------------------------
# v1.2.1: condensation consumes structured observation fields
# ---------------------------------------------------------------------------


class TestCondensationUsesStructuredFields:
    def test_pruned_truncated_result_still_appears_in_findings_via_summary(self):
        """Long observation pruned + truncated should still appear in Findings
        because tool_meta.summary is used."""
        from aicoder.context.condense import prune_history_events, summarize_history_events

        events = [
            _make_event("ev-1", kind="assistant_thought", payload={"thought": "Read files"}),
            _make_event("ev-2", kind="tool_call", payload={"tool_name": "read_file", "tool_input": {"path": "a.py"}}),
            _make_event("ev-3", kind="tool_result", payload={
                "observation": "x" * 600,  # will be truncated
                "tool_meta": {
                    "success": True,
                    "tool_name": "read_file",
                    "summary": "Read a.py: found 42 functions",
                    "files": ["/tmp/a.py"],
                },
            }),
        ]

        pruned = prune_history_events(events, "act")
        # Observation should be truncated
        assert pruned[2].payload.get("observation_truncated") is True

        block = summarize_history_events(pruned)
        assert block is not None
        assert "Findings:" in block.summary
        # Structured summary should appear, not the truncated gibberish
        assert "found 42 functions" in block.summary

    def test_failure_uses_error_type_and_summary(self):
        """Failure summary should use error_type and summary from structured fields."""
        events = [
            _make_event("ev-1", kind="tool_call", payload={"tool_name": "write_file", "tool_input": {"path": "b.py"}}),
            _make_event("ev-2", kind="tool_error", payload={
                "error": "permission denied",
                "tool_meta": {
                    "success": False,
                    "tool_name": "write_file",
                    "error_type": "permission_denied",
                    "summary": "write_file blocked: read-only mode",
                    "recommended_next": "Switch to act mode to write files.",
                },
            }),
        ]

        block = summarize_history_events(events)
        assert block is not None
        assert "Failures:" in block.summary
        # Structured summary should appear
        assert "read-only mode" in block.summary

    def test_next_steps_includes_recommended_next(self):
        """recommended_next from failures should appear in Next steps section."""
        events = [
            _make_event("ev-1", kind="tool_error", payload={
                "error": "not found",
                "tool_meta": {
                    "success": False,
                    "tool_name": "read_file",
                    "error_type": "execution_error",
                    "summary": "read_file failed: not found",
                    "recommended_next": "Check the file path and try again.",
                },
            }),
        ]

        block = summarize_history_events(events)
        assert block is not None
        assert "Next steps:" in block.summary
        assert "Check the file path" in block.summary

    def test_findings_prefers_payload_summary_over_observation(self):
        """When both payload.summary and observation exist, summary takes priority."""
        events = [
            _make_event("ev-1", kind="tool_result", payload={
                "observation": "raw output text that is very long " * 20,
                "summary": "Extracted 3 key findings from data",
                "tool_meta": {"success": True, "tool_name": "search_files"},
            }),
        ]

        block = summarize_history_events(events)
        assert block is not None
        assert "Extracted 3 key findings" in block.summary

    def test_findings_falls_back_to_tool_meta_summary(self):
        """When payload has no summary, tool_meta.summary is used."""
        events = [
            _make_event("ev-1", kind="tool_result", payload={
                "observation": "long raw output " * 30,
                "tool_meta": {
                    "success": True,
                    "tool_name": "list_files",
                    "summary": "Listed 15 files in the project",
                },
            }),
        ]

        block = summarize_history_events(events)
        assert block is not None
        assert "Listed 15 files" in block.summary

    def test_findings_last_resort_uses_observation(self):
        """When no summary exists anywhere, observation text is used as fallback."""
        events = [
            _make_event("ev-1", kind="tool_result", payload={
                "observation": "def main(): pass",
                "tool_meta": {"success": True, "tool_name": "read_file"},
            }),
        ]

        block = summarize_history_events(events)
        assert block is not None
        assert "def main()" in block.summary

    def test_failure_uses_error_type_when_no_summary(self):
        """Failure without summary should show error_type + error message."""
        events = [
            _make_event("ev-1", kind="tool_error", payload={
                "error": "timeout after 30s",
                "tool_meta": {
                    "success": False,
                    "tool_name": "run_shell",
                    "error_type": "execution_error",
                },
            }),
        ]

        block = summarize_history_events(events)
        assert block is not None
        assert "run_shell" in block.summary
        assert "execution_error" in block.summary
        assert "timeout" in block.summary
