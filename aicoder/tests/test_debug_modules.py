"""Tests for debug/diagnostics modules: context_trace, condense_trace, dump_helpers."""

import tempfile

import pytest

from aicoder.agent_step_store import AgentStepStore
from aicoder.debug.context_trace import trace_context
from aicoder.debug.condense_trace import trace_condensation
from aicoder.debug.dump_helpers import (
    dump_llm_history_view,
    dump_runtime_history_view,
    dump_packed_context,
    dump_condensation_state,
    dump_repo_context,
    dump_event_store,
    dump_replay_runtime_view,
    dump_replay_llm_view,
    dump_summary_blocks,
    dump_snapshot_state,
    dump_tool_trace_retention,
)
from aicoder.runners import register_runner, unregister_runner
from aicoder.runners.cot_agent_runner import CotAgentRunner
from aicoder.tests.conftest import make_mock_coder
from aicoder.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coder_with_steps(
    session_id: str = "debug-test",
    num_steps: int = 5,
    done_messages_count: int = 4,
):
    """Create a mock coder with a runner and steps for debug testing."""
    root = tempfile.mkdtemp()
    coder = make_mock_coder(root=root)
    coder.session_id = session_id
    coder.done_messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(done_messages_count)
    ]

    step_store = AgentStepStore(session_id=session_id)
    for i in range(num_steps):
        step = step_store.create_step(iteration=i, mode="act", runner_type="cot")
        step_store.update_step_after_parse(
            step, thought=f"Step {i}", action_name="read_file",
            action_input={"path": f"/tmp/f{i}.py"},
        )
        obs = "x" * 300 if i % 3 == 0 else f"contents of file {i}"
        step_store.update_step_after_tool(
            step, observation=obs,
            tool_meta={"success": True, "tool_name": "read_file"},
            files=[f"/tmp/f{i}.py"],
        )

    registry = ToolRegistry()
    runner = CotAgentRunner(
        coder=coder, session_id=session_id, mode="act",
        tool_registry=registry, step_store=step_store,
    )
    register_runner(session_id, runner)
    return coder


def _cleanup(session_id: str):
    unregister_runner(session_id)


# ---------------------------------------------------------------------------
# context_trace tests
# ---------------------------------------------------------------------------


class TestContextTrace:
    def _trace(self, coder, mode="act", runner_type="cot", **kwargs):
        """Call trace_context with message_builder patches for mock coders."""
        from unittest.mock import patch
        with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
             patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
             patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode, \
             patch("aicoder.coders.message_builder.build_runtime_state_messages") as mock_rt:
            mock_sys.return_value = [{"role": "system", "content": "You are a helpful assistant."}]
            mock_chat.return_value = []
            mock_mode.return_value = []
            mock_rt.return_value = []
            return trace_context(coder, mode, runner_type, **kwargs)

    def test_trace_context_returns_report(self):
        coder = _make_coder_with_steps(session_id="ctx-trace-1")
        report = self._trace(coder, user_input="fix bug")

        assert "layers" in report
        assert "condensation" in report
        assert "budget" in report
        assert "summary" in report
        assert isinstance(report["summary"], str)
        assert len(report["summary"]) > 0

        _cleanup("ctx-trace-1")

    def test_trace_context_event_count(self):
        coder = _make_coder_with_steps(session_id="ctx-trace-2", num_steps=3)
        report = self._trace(coder)

        assert report["layers"]["event_count"] >= 9  # 3 steps * 3+ events
        assert report["layers"]["step_count"] >= 3

        _cleanup("ctx-trace-2")

    def test_trace_context_budget_info(self):
        coder = _make_coder_with_steps(session_id="ctx-trace-3")
        report = self._trace(coder)

        assert "history_tokens" in report["budget"]
        assert "tool_trace_tokens" in report["budget"]
        assert report["budget"]["history_tokens"] > 0

        _cleanup("ctx-trace-3")

    def test_trace_context_condensation_info(self):
        coder = _make_coder_with_steps(session_id="ctx-trace-4", num_steps=5)
        report = self._trace(coder)

        assert "triggered" in report["condensation"]
        assert "threshold" in report["condensation"]
        assert report["condensation"]["triggered"] is True

        _cleanup("ctx-trace-4")

    def test_trace_context_no_runner(self):
        """trace_context should handle coder without a runner gracefully."""
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = "no-runner"
        coder.done_messages = [{"role": "user", "content": "hi"}]

        report = self._trace(coder)
        assert "layers" in report
        assert report["layers"]["event_count"] == 0

    # -- v1.2.3: per-layer stats from pack_context() --

    def test_trace_context_has_per_layer_structure(self):
        """trace_context should report per-layer stats from pack_context."""
        coder = _make_coder_with_steps(session_id="ctx-layers-1")
        report = self._trace(coder, user_input="fix bug")

        layers = report["layers"]
        assert "system" in layers
        assert "history" in layers
        assert "repo" in layers
        assert "chat_files" in layers
        assert "current" in layers
        assert "user_input" in layers
        assert "total" in layers

        for layer_name in ("system", "history", "repo", "chat_files", "current", "user_input", "total"):
            assert "count" in layers[layer_name], f"Layer {layer_name} missing 'count'"
            assert "tokens" in layers[layer_name], f"Layer {layer_name} missing 'tokens'"

        _cleanup("ctx-layers-1")

    def test_trace_context_system_count_positive(self):
        """System messages should always be present (at least from build_system_messages)."""
        coder = _make_coder_with_steps(session_id="ctx-layers-2")
        report = self._trace(coder)

        system = report["layers"]["system"]
        assert system["count"] >= 1, "Should have at least 1 system message"
        assert system["tokens"] >= 0

        _cleanup("ctx-layers-2")

    def test_trace_context_history_count_positive(self):
        """History layer should contain done_messages or rebuilt history."""
        coder = _make_coder_with_steps(session_id="ctx-layers-3", done_messages_count=6)
        report = self._trace(coder)

        history = report["layers"]["history"]
        assert history["count"] >= 1, "History should have messages from done_messages"

        _cleanup("ctx-layers-3")

    def test_trace_context_total_count_matches_sum(self):
        """Total count should equal system + conversation messages."""
        coder = _make_coder_with_steps(session_id="ctx-layers-4")
        report = self._trace(coder, user_input="test")

        total = report["layers"]["total"]["count"]
        system_count = report["layers"]["system"]["count"]
        conv_layers = (
            report["layers"]["repo"]["count"]
            + report["layers"]["history"]["count"]
            + report["layers"]["chat_files"]["count"]
            + report["layers"]["current"]["count"]
            + report["layers"]["user_input"]["count"]
        )
        assert total == system_count + conv_layers

        _cleanup("ctx-layers-4")

    def test_trace_context_user_input_counted(self):
        """user_input should appear as exactly 1 message when provided."""
        coder = _make_coder_with_steps(session_id="ctx-layers-5")
        report = self._trace(coder, user_input="fix the bug")

        assert report["layers"]["user_input"]["count"] == 1
        assert report["layers"]["user_input"]["tokens"] > 0

        _cleanup("ctx-layers-5")

    def test_trace_context_no_user_input(self):
        """user_input count should be 0 when not provided."""
        coder = _make_coder_with_steps(session_id="ctx-layers-6")
        report = self._trace(coder)

        assert report["layers"]["user_input"]["count"] == 0

        _cleanup("ctx-layers-6")

    def test_trace_context_history_source(self):
        """history_source should indicate where history came from."""
        coder = _make_coder_with_steps(session_id="ctx-layers-7")
        report = self._trace(coder)

        assert "history_source" in report["layers"]
        source = report["layers"]["history_source"]
        assert source in ("runner.build_history_messages", "done_messages")

        _cleanup("ctx-layers-7")

    def test_trace_context_summary_includes_all_layers(self):
        """Human-readable summary should mention key layer token counts."""
        coder = _make_coder_with_steps(session_id="ctx-layers-8")
        report = self._trace(coder, user_input="test")

        summary = report["summary"]
        assert "system=" in summary
        assert "hist=" in summary
        assert "user_input=" in summary

        _cleanup("ctx-layers-8")

    # -- Phase 7: repo and focused file details --

    def test_trace_repo_details(self):
        """Trace should include repo selected count and budget utilization."""
        coder = _make_coder_with_steps(session_id="ctx-repo-1")
        report = self._trace(coder, user_input="test")

        assert "repo" in report
        repo = report["repo"]
        assert "selected_count" in repo
        assert "budget_tokens" in repo
        assert "token_estimate" in repo
        assert "utilization" in repo
        assert "top_reasons" in repo
        assert repo["budget_tokens"] > 0

        _cleanup("ctx-repo-1")

    def test_trace_focused_files_details(self):
        """Trace should include focused file budget before/after."""
        coder = _make_coder_with_steps(session_id="ctx-ff-1")
        report = self._trace(coder, user_input="test")

        assert "focused_files" in report
        ff = report["focused_files"]
        assert "tokens_before_trim" in ff
        assert "tokens_after_trim" in ff
        assert "budget" in ff
        assert "preference" in ff
        assert "trimmed" in ff

        _cleanup("ctx-ff-1")

    def test_trace_mode_differences_visible(self):
        """Different modes should show different trace details."""
        coder_sniff = _make_coder_with_steps(session_id="ctx-diff-sniff")
        report_sniff = self._trace(coder_sniff, mode="sniff", user_input="test")

        coder_act = _make_coder_with_steps(session_id="ctx-diff-act")
        report_act = self._trace(coder_act, mode="act", user_input="test")

        # Preference should differ
        assert report_sniff["focused_files"]["preference"] == "breadth"
        assert report_act["focused_files"]["preference"] == "depth"

        # Budget should differ
        assert report_sniff["focused_files"]["budget"] != report_act["focused_files"]["budget"]

        _cleanup("ctx-diff-sniff")
        _cleanup("ctx-diff-act")

    # -- Phase 6: event source in trace --

    def test_trace_includes_event_source(self):
        """Trace should include event source info (memory/file)."""
        coder = _make_coder_with_steps(session_id="ctx-evsrc-1")
        report = self._trace(coder, user_input="test")

        assert "event_source" in report
        es = report["event_source"]
        assert "type" in es
        assert "persisted" in es
        assert "event_count" in es

        _cleanup("ctx-evsrc-1")


# ---------------------------------------------------------------------------
# condense_trace tests
# ---------------------------------------------------------------------------


class TestCondenseTrace:
    def test_trace_condensation_returns_report(self):
        coder = _make_coder_with_steps(session_id="cond-trace-1")
        report = trace_condensation(coder, "act")

        assert "events" in report
        assert "pruning" in report
        assert "summary" in report
        assert "warnings" in report

        _cleanup("cond-trace-1")

    def test_trace_condensation_event_stats(self):
        coder = _make_coder_with_steps(session_id="cond-trace-2", num_steps=3)
        report = trace_condensation(coder, "act")

        assert report["events"]["total"] >= 9
        assert "by_kind" in report["events"]
        assert "step_started" in report["events"]["by_kind"]
        assert "tool_call" in report["events"]["by_kind"]

        _cleanup("cond-trace-2")

    def test_trace_condensation_with_truncated_obs(self):
        """Steps with long observations should trigger truncation warnings."""
        coder = _make_coder_with_steps(session_id="cond-trace-3", num_steps=5)
        report = trace_condensation(coder, "act")

        # Steps 0, 3 have observations of 300 chars (truncated to 200)
        assert report["pruning"]["truncated_observations"] > 0
        assert any("truncated" in w.lower() for w in report["warnings"])

        _cleanup("cond-trace-3")

    def test_trace_condensation_summary_sections(self):
        coder = _make_coder_with_steps(session_id="cond-trace-4", num_steps=5)
        report = trace_condensation(coder, "act")

        if report["summary"].get("produced"):
            sections = report["summary"]["sections_present"]
            assert "Actions" in sections
            assert "Findings" in sections

        _cleanup("cond-trace-4")

    def test_trace_condensation_no_events(self):
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = "no-events"
        report = trace_condensation(coder, "act")
        assert "events" in report
        # When no events, total may not be set but events dict exists
        assert report.get("summary_text") is not None


# ---------------------------------------------------------------------------
# dump_helpers tests
# ---------------------------------------------------------------------------


class TestDumpHelpers:
    def test_dump_llm_history_view(self):
        coder = _make_coder_with_steps(session_id="dump-llm-1", num_steps=5)
        result = dump_llm_history_view(coder, "act", "cot")

        assert "message_count" in result
        assert "messages" in result
        assert "has_condensed" in result
        assert result["message_count"] > 0
        assert isinstance(result["messages"], list)

        _cleanup("dump-llm-1")

    def test_dump_runtime_history_view(self):
        coder = _make_coder_with_steps(session_id="dump-rt-1", num_steps=3)
        result = dump_runtime_history_view(coder, "act", "cot")

        assert "step_count" in result
        assert "steps" in result
        assert result["step_count"] >= 3

        # Each step should have iteration, status
        for step in result["steps"]:
            assert "iteration" in step
            assert "status" in step

        _cleanup("dump-rt-1")

    def test_dump_packed_context(self):
        coder = _make_coder_with_steps(session_id="dump-pack-1")
        from unittest.mock import patch

        with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
             patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
             patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode, \
             patch("aicoder.coders.message_builder.build_runtime_state_messages") as mock_rt:
            mock_sys.return_value = [{"role": "system", "content": "sys"}]
            mock_chat.return_value = []
            mock_mode.return_value = []
            mock_rt.return_value = []

            result = dump_packed_context(coder, "fix the bug", "act", "cot")

        assert "system_count" in result
        assert "conversation_count" in result
        assert "total_tokens_approx" in result
        assert result["system_count"] >= 1
        assert result["conversation_count"] >= 1

        _cleanup("dump-pack-1")

    def test_dump_condensation_state(self):
        coder = _make_coder_with_steps(session_id="dump-cond-1", num_steps=5)
        result = dump_condensation_state(coder, "act")

        assert "events_available" in result
        assert "threshold" in result
        assert "triggered" in result
        assert result["events_available"] >= 15  # 5 steps * 3+ events
        assert result["triggered"] is True

        _cleanup("dump-cond-1")

    def test_dump_condensation_state_no_events(self):
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = "dump-no-events"

        result = dump_condensation_state(coder, "act")
        assert result["events_available"] == 0
        assert result["triggered"] is False

    # -- Phase 7: repo layer / focused files layer in dump --

    def test_dump_packed_context_has_repo_layer(self):
        coder = _make_coder_with_steps(session_id="dump-repo-1")
        from unittest.mock import patch

        with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
             patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
             patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode, \
             patch("aicoder.coders.message_builder.build_runtime_state_messages") as mock_rt:
            mock_sys.return_value = [{"role": "system", "content": "sys"}]
            mock_chat.return_value = []
            mock_mode.return_value = []
            mock_rt.return_value = []

            result = dump_packed_context(coder, "fix bug", "act", "cot")

        assert "repo_layer" in result
        assert isinstance(result["repo_layer"], dict)

        _cleanup("dump-repo-1")

    def test_dump_packed_context_has_focused_files_layer(self):
        coder = _make_coder_with_steps(session_id="dump-ff-1")
        from unittest.mock import patch

        with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
             patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
             patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode, \
             patch("aicoder.coders.message_builder.build_runtime_state_messages") as mock_rt:
            mock_sys.return_value = [{"role": "system", "content": "sys"}]
            mock_chat.return_value = []
            mock_mode.return_value = []
            mock_rt.return_value = []

            result = dump_packed_context(coder, "fix bug", "act", "cot")

        assert "focused_files_layer" in result
        ff = result["focused_files_layer"]
        assert "tokens_before" in ff
        assert "tokens_after" in ff
        assert "preference" in ff

        _cleanup("dump-ff-1")

    def test_dump_repo_context(self):
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        result = dump_repo_context(coder, "act")

        assert "mode" in result
        assert "budget_tokens" in result
        assert result["mode"] == "act"
        assert result["budget_tokens"] > 0

    # -- Phase 6: dump_event_store / dump_replay_views --

    def test_dump_event_store(self):
        coder = _make_coder_with_steps(session_id="dump-es-1", num_steps=3)
        result = dump_event_store(coder)

        assert "event_count" in result
        assert "backend_type" in result
        assert "persisted" in result
        assert "event_kinds" in result
        assert "iteration_range" in result
        assert result["event_count"] >= 9  # 3 steps * 3+ events

        _cleanup("dump-es-1")

    def test_dump_event_store_no_runner(self):
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        result = dump_event_store(coder)

        assert result["event_count"] == 0

    def test_dump_replay_runtime_view(self):
        coder = _make_coder_with_steps(session_id="dump-replay-rt-1", num_steps=3)
        result = dump_replay_runtime_view(coder, "act")

        assert "step_count" in result
        assert "event_count" in result
        assert "steps" in result
        assert result["step_count"] >= 3
        assert result["event_count"] >= 9

        _cleanup("dump-replay-rt-1")

    def test_dump_replay_llm_view(self):
        coder = _make_coder_with_steps(session_id="dump-replay-llm-1", num_steps=2)
        result = dump_replay_llm_view(coder, "act", "cot")

        assert "message_count" in result
        assert "event_count" in result
        assert "source" in result
        assert "messages" in result

        _cleanup("dump-replay-llm-1")

    def teardown_method(self):
        for sid in [
            "dump-llm-1", "dump-rt-1", "dump-pack-1", "dump-cond-1", "dump-no-events",
            "dump-repo-1", "dump-ff-1", "dump-es-1", "dump-replay-rt-1", "dump-replay-llm-1",
        ]:
            _cleanup(sid)


# ---------------------------------------------------------------------------
# v1.5 Phase 6: dump_summary_blocks / dump_snapshot_state / dump_tool_trace_retention
# ---------------------------------------------------------------------------


class TestDumpSummaryBlocks:
    def test_no_snapshot(self):
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = "dump-sb-no"

        result = dump_summary_blocks(coder, "act")
        assert result["snapshot_available"] is False
        assert result["blocks"] == []

    def test_with_snapshot(self):
        from aicoder.context.summary_types import SummaryBlock, CondensationSnapshot
        from aicoder.context.summary_store import save_snapshot

        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = "dump-sb-yes"

        snap = CondensationSnapshot(
            snapshot_id="snap-dump-1",
            session_id="dump-sb-yes",
            source_event_count=10,
            latest_event_id="ev-10",
            blocks=[SummaryBlock(
                summary_id="sb-dump", goal="Fix bug",
                findings=["Found X"], actions_taken=["read_file(a.py)"],
            )],
            mode="act",
        )
        save_snapshot(snap, root)

        result = dump_summary_blocks(coder, "act")
        assert result["snapshot_available"] is True
        assert result["snapshot_id"] == "snap-dump-1"
        assert result["block_count"] == 1
        assert result["blocks"][0]["goal"] == "Fix bug"
        assert result["blocks"][0]["findings_count"] == 1

    def test_no_session(self):
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = ""

        result = dump_summary_blocks(coder, "act")
        assert result["snapshot_available"] is False


class TestDumpSnapshotState:
    def test_no_snapshot(self):
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = "dump-ss-no"

        result = dump_snapshot_state(coder, "act")
        assert result["snapshot_reused"] is False

    def test_with_snapshot_and_events(self):
        from aicoder.context.summary_types import SummaryBlock, CondensationSnapshot
        from aicoder.context.summary_store import save_snapshot

        coder = _make_coder_with_steps(session_id="dump-ss-yes", num_steps=3)

        # Build snapshot covering all events
        from aicoder.context.history_view import _get_event_records
        events = _get_event_records(coder)
        snap = CondensationSnapshot(
            snapshot_id="snap-dump-ss",
            session_id="dump-ss-yes",
            source_event_count=len(events),
            latest_event_id=events[-1].event_id if events else "",
            blocks=[SummaryBlock(
                summary_id="sb-dump-ss", goal="Test",
                covered_event_ids=[e.event_id for e in events],
            )],
            mode="act",
        )
        # Save to coder's root directory
        save_snapshot(snap, coder.root)

        result = dump_snapshot_state(coder, "act")
        assert result["snapshot_reused"] is True
        assert result["coverage"] == "full"
        assert result["uncovered_event_count"] == 0

        _cleanup("dump-ss-yes")


class TestDumpToolTraceRetention:
    def test_with_events(self):
        coder = _make_coder_with_steps(session_id="dump-ttr-1", num_steps=5)
        result = dump_tool_trace_retention(coder, "act")

        assert result["total_traces"] >= 5
        assert result["must_keep"] >= 0
        assert result["summarize_only"] >= 0
        assert result["trim_aggressively"] >= 0
        assert "/" in result["retention_ratio"]

        _cleanup("dump-ttr-1")

    def test_no_events(self):
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = "dump-ttr-no"

        result = dump_tool_trace_retention(coder, "act")
        assert result["total_traces"] == 0


# ---------------------------------------------------------------------------
# v1.5 Phase 6: context_trace snapshot and retention info
# ---------------------------------------------------------------------------


class TestContextTraceV15:
    def _trace(self, coder, mode="act", runner_type="cot", **kwargs):
        from unittest.mock import patch
        with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
             patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
             patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode, \
             patch("aicoder.coders.message_builder.build_runtime_state_messages") as mock_rt:
            mock_sys.return_value = [{"role": "system", "content": "You are a helpful assistant."}]
            mock_chat.return_value = []
            mock_mode.return_value = []
            mock_rt.return_value = []
            return trace_context(coder, mode, runner_type, **kwargs)

    def test_trace_includes_snapshot_section(self):
        coder = _make_coder_with_steps(session_id="ctx-v15-1")
        report = self._trace(coder, user_input="test")

        assert "snapshot" in report
        snap = report["snapshot"]
        assert "available" in snap

        _cleanup("ctx-v15-1")

    def test_trace_includes_retention_section(self):
        coder = _make_coder_with_steps(session_id="ctx-v15-2")
        report = self._trace(coder, user_input="test")

        assert "tool_trace_retention" in report
        ret = report["tool_trace_retention"]
        assert "total_traces" in ret
        assert "must_keep" in ret
        assert "retention_ratio" in ret

        _cleanup("ctx-v15-2")

    def test_trace_snapshot_with_persisted_snapshot(self):
        from aicoder.context.summary_types import SummaryBlock, CondensationSnapshot
        from aicoder.context.summary_store import save_snapshot

        coder = _make_coder_with_steps(session_id="ctx-v15-3", num_steps=3)
        from aicoder.context.history_view import _get_event_records
        events = _get_event_records(coder)

        snap = CondensationSnapshot(
            snapshot_id="snap-ctx-v15",
            session_id="ctx-v15-3",
            source_event_count=len(events),
            latest_event_id=events[-1].event_id if events else "",
            blocks=[SummaryBlock(
                summary_id="sb-ctx-v15", goal="test",
                covered_event_ids=[e.event_id for e in events],
            )],
            mode="act",
        )
        save_snapshot(snap, getattr(coder, "root", tempfile.mkdtemp()))

        report = self._trace(coder, user_input="test")
        assert report["snapshot"]["available"] is True
        assert report["snapshot"]["snapshot_id"] == "snap-ctx-v15"

        _cleanup("ctx-v15-3")

    def test_trace_summary_includes_snapshot_status(self):
        coder = _make_coder_with_steps(session_id="ctx-v15-4")
        report = self._trace(coder, user_input="test")

        assert "snapshot=" in report["summary"]

        _cleanup("ctx-v15-4")


# ---------------------------------------------------------------------------
# Phase 4: v1.6.1 Debug/Dump observability
# ---------------------------------------------------------------------------


class TestDumpQualitySummaryV161:
    """dump_quality_summary must include checkpoint skip and verification suppression."""

    def test_quality_summary_includes_checkpoint_skip_count(self):
        """dump_quality_summary must have checkpoint skip metrics."""
        from aicoder.debug.dump_helpers import dump_quality_summary
        from aicoder.events.types import AgentEventRecord

        coder = _make_coder_with_steps(session_id="qs-v161-1")
        # Manually inject checkpoint_skip events
        from aicoder.context.history_view import _get_event_records
        # We need to add events to the event store
        runner = _get_runner_from_coder(coder)
        if runner and runner.step_store:
            runner.step_store.event_store.append(
                iteration=0, kind="checkpoint_skip",
                payload={"tool_name": "read_file", "tool_call_id": "tc_1", "session_id": "qs-v161-1", "step_id": "s1"},
            )

        result = dump_quality_summary(coder)
        assert "checkpoint_skip_count" in result, "dump_quality_summary must include checkpoint_skip_count"
        assert result["checkpoint_skip_count"] >= 0

        _cleanup("qs-v161-1")

    def test_quality_summary_includes_verification_suppressed_count(self):
        """dump_quality_summary must have verification_suppressed count."""
        from aicoder.debug.dump_helpers import dump_quality_summary

        coder = _make_coder_with_steps(session_id="qs-v161-2")
        result = dump_quality_summary(coder)
        assert "verification_suppressed_count" in result, "dump_quality_summary must include verification_suppressed_count"
        assert result["verification_suppressed_count"] >= 0

        _cleanup("qs-v161-2")


class TestTraceContextV161:
    """trace_context must include verification.recent_tasks, recovery.last_action, checkpoint.last_skip."""

    def _trace(self, coder, mode="act", runner_type="cot", **kwargs):
        from unittest.mock import patch
        with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
             patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
             patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode, \
             patch("aicoder.coders.message_builder.build_runtime_state_messages") as mock_rt:
            mock_sys.return_value = [{"role": "system", "content": "You are a helpful assistant."}]
            mock_chat.return_value = []
            mock_mode.return_value = []
            mock_rt.return_value = []
            from aicoder.debug.context_trace import trace_context
            return trace_context(coder, mode, runner_type, **kwargs)

    def test_trace_includes_recovery_last_action(self):
        """trace_context report must have recovery.last_action."""
        coder = _make_coder_with_steps(session_id="tc-v161-1")
        report = self._trace(coder, user_input="test")

        assert "recovery" in report
        assert "last_action" in report["recovery"], "trace_context recovery section must have last_action"

        _cleanup("tc-v161-1")

    def test_trace_includes_checkpoint_last_skip(self):
        """trace_context report must have checkpoint.last_skip."""
        coder = _make_coder_with_steps(session_id="tc-v161-2")
        report = self._trace(coder, user_input="test")

        assert "checkpoint" in report
        assert "last_skip" in report["checkpoint"], "trace_context must have checkpoint.last_skip"

        _cleanup("tc-v161-2")

    def test_trace_includes_verification_recent_tasks(self):
        """trace_context report must have verification.recent_tasks."""
        coder = _make_coder_with_steps(session_id="tc-v161-3")
        report = self._trace(coder, user_input="test")

        assert "verification" in report
        assert "recent_tasks" in report["verification"], "trace_context verification section must have recent_tasks"

        _cleanup("tc-v161-3")


def _get_runner_from_coder(coder):
    """Helper to get runner from coder."""
    try:
        from aicoder.context.history_view import _get_runner
        return _get_runner(coder)
    except Exception:
        return None
