"""Tests for session resume from persisted events (v1.4 Phase 5)."""
import os
import tempfile

import pytest

from aicoder.agent_step_store import AgentStepStore
from aicoder.events.store import AgentEventStore
from aicoder.events.file_store import FileEventBackend
from aicoder.events.replay import replay_runtime_view, replay_llm_view
from aicoder.events.types import AgentEventRecord


# ---------------------------------------------------------------------------
# Session resume: rebuild event store from file
# ---------------------------------------------------------------------------


class TestEventStoreResume:
    def test_resume_empty_file(self):
        """No event file should give empty store."""
        root = tempfile.mkdtemp()
        store = AgentEventStore.for_session("no-file-session", persist=True, root=root)
        assert len(store.all_events()) == 0

    def test_resume_with_existing_events(self):
        """Events written in one instance should be available after resume."""
        root = tempfile.mkdtemp()

        # First session: write events
        store1 = AgentEventStore.for_session("resume-1", persist=True, root=root)
        store1.append(iteration=0, kind="step_started", payload={"mode": "act"})
        store1.append(iteration=0, kind="tool_call", payload={"tool_name": "read_file"})

        # Resume: new store reads from file
        store2 = AgentEventStore.for_session("resume-1", persist=True, root=root)
        events = store2.all_events()
        assert len(events) == 2
        assert events[0].kind == "step_started"
        assert events[1].payload["tool_name"] == "read_file"

    def test_resume_then_append(self):
        """After resume, new events should be appended to existing file."""
        root = tempfile.mkdtemp()

        store1 = AgentEventStore.for_session("resume-append", persist=True, root=root)
        store1.append(iteration=0, kind="step_started")

        store2 = AgentEventStore.for_session("resume-append", persist=True, root=root)
        store2.append(iteration=1, kind="step_started")

        # Third instance sees both
        store3 = AgentEventStore.for_session("resume-append", persist=True, root=root)
        assert len(store3.all_events()) == 2


class TestStepStoreResume:
    def test_step_store_for_session_persistent(self):
        """AgentStepStore.for_session with persist=True should persist events."""
        root = tempfile.mkdtemp()

        step_store = AgentStepStore.for_session("step-resume-1", persist=True, root=root)
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, action_name="read_file")
        step_store.update_step_after_tool(step, observation="contents")

        # Verify file exists
        event_path = os.path.join(root, ".aicoder", "events", "step-resume-1.jsonl")
        assert os.path.exists(event_path)

        # New step store reads events
        step_store2 = AgentStepStore.for_session("step-resume-1", persist=True, root=root)
        events = step_store2.event_store.all_events()
        assert len(events) >= 3

    def test_step_store_for_session_memory(self):
        """AgentStepStore.for_session without persist should use memory."""
        step_store = AgentStepStore.for_session("mem-session")
        assert isinstance(step_store.event_store.backend, FileEventBackend) is False


# ---------------------------------------------------------------------------
# Replay from persisted events
# ---------------------------------------------------------------------------


class TestReplayFromPersistedEvents:
    def _make_full_session(self, root, session_id="replay-persist", num_steps=3):
        """Create a session with full step lifecycle, return root."""
        step_store = AgentStepStore.for_session(session_id, persist=True, root=root)
        for i in range(num_steps):
            step = step_store.create_step(iteration=i, mode="act", runner_type="cot")
            step_store.update_step_after_parse(
                step, thought=f"Step {i}", action_name="read_file",
                action_input={"path": f"/tmp/f{i}.py"},
            )
            step_store.update_step_after_tool(
                step, observation=f"content {i}",
                tool_meta={"success": True},
            )
        return step_store

    def test_runtime_view_from_persisted(self):
        root = tempfile.mkdtemp()
        self._make_full_session(root)

        # Load events from file
        store = AgentEventStore.for_session("replay-persist", persist=True, root=root)
        events = store.all_events()
        assert len(events) > 0

        # Replay
        runtime = replay_runtime_view(events)
        assert len(runtime) == 3
        assert runtime[0]["status"] == "observed"
        assert runtime[0]["action"]["tool_name"] == "read_file"

    def test_llm_view_cot_from_persisted(self):
        root = tempfile.mkdtemp()
        self._make_full_session(root)

        store = AgentEventStore.for_session("replay-persist", persist=True, root=root)
        events = store.all_events()

        llm = replay_llm_view(events, [], runner_type="cot")
        # Should have assistant + user pairs for each step
        assert len(llm) > 0
        assert any(m["role"] == "assistant" for m in llm)

    def test_llm_view_fc_from_persisted(self):
        root = tempfile.mkdtemp()
        self._make_full_session(root)

        store = AgentEventStore.for_session("replay-persist", persist=True, root=root)
        events = store.all_events()

        llm = replay_llm_view(events, [], runner_type="function-calling")
        tool_msgs = [m for m in llm if m["role"] == "tool"]
        assert len(tool_msgs) >= 3  # One tool msg per step


# ---------------------------------------------------------------------------
# Graceful fallback on corrupted file
# ---------------------------------------------------------------------------


class TestCorruptedFileFallback:
    def test_corrupted_file_does_not_crash(self):
        """A corrupted JSONL file should not crash the store."""
        root = tempfile.mkdtemp()
        events_dir = os.path.join(root, ".aicoder", "events")
        os.makedirs(events_dir, exist_ok=True)

        # Write corrupted data
        with open(os.path.join(events_dir, "corrupt-test.jsonl"), "w") as f:
            f.write("not json\n")
            f.write("also not json\n")

        store = AgentEventStore.for_session("corrupt-test", persist=True, root=root)
        # Should not crash, return empty or partial
        events = store.all_events()
        assert isinstance(events, list)

    def test_partially_corrupted_file_keeps_valid(self):
        """Valid events before corruption should still be readable."""
        root = tempfile.mkdtemp()
        events_dir = os.path.join(root, ".aicoder", "events")
        os.makedirs(events_dir, exist_ok=True)

        # Write valid event, then corruption, then another valid event
        store1 = AgentEventStore.for_session("partial-corrupt", persist=True, root=root)
        store1.append(iteration=0, kind="step_started", payload={"mode": "act"})

        # Manually corrupt
        path = os.path.join(events_dir, "partial-corrupt.jsonl")
        with open(path, "a") as f:
            f.write("corrupted line\n")

        # Read back — should get the valid event
        store2 = AgentEventStore.for_session("partial-corrupt", persist=True, root=root)
        events = store2.all_events()
        assert len(events) >= 1
        assert events[0].kind == "step_started"


# ---------------------------------------------------------------------------
# Resume simulation: write → stop → resume → verify
# ---------------------------------------------------------------------------


class TestResumeSimulation:
    def test_full_resume_cycle(self):
        """Simulate: run session → stop → resume → verify events and replay."""
        root = tempfile.mkdtemp()

        # --- Session 1: run 2 steps ---
        step_store1 = AgentStepStore.for_session("cycle-1", persist=True, root=root)
        step = step_store1.create_step(iteration=0, mode="act", runner_type="cot")
        step_store1.update_step_after_parse(step, thought="Read config", action_name="read_file")
        step_store1.update_step_after_tool(step, observation="config contents",
                                           tool_meta={"success": True})

        step2 = step_store1.create_step(iteration=1, mode="act", runner_type="cot")
        step_store1.update_step_after_parse(step2, action_name="list_files")
        step_store1.update_step_after_tool(step2, observation="file1.py\nfile2.py")

        # --- Simulate process restart ---
        # step_store1 goes out of scope (simulating process exit)

        # --- Session 2: resume ---
        step_store2 = AgentStepStore.for_session("cycle-1", persist=True, root=root)

        # Verify events restored
        events = step_store2.event_store.all_events()
        assert len(events) >= 6  # 2 steps * (started + call + result)

        # Verify runtime replay works
        runtime = replay_runtime_view(events)
        assert len(runtime) == 2
        assert runtime[0]["thought"] == "Read config"
        assert runtime[1]["action"]["tool_name"] == "list_files"

        # Verify LLM replay works
        llm = replay_llm_view(events, [], runner_type="cot")
        assert len(llm) > 0

        # Can continue appending
        step3 = step_store2.create_step(iteration=2, mode="act", runner_type="cot")
        step_store2.update_step_after_parse(step3, action_name="search_files")
        step_store2.update_step_after_tool(step3, observation="found 3 files")

        # Third instance sees all events
        store3 = AgentEventStore.for_session("cycle-1", persist=True, root=root)
        all_events = store3.all_events()
        # At least original 6 + new 3
        assert len(all_events) >= 9


# ---------------------------------------------------------------------------
# Integration: resume → history views (Bug Fix validation)
# ---------------------------------------------------------------------------


class TestResumeHistoryViews:
    """Validate that all three history views work after session resume.

    Simulates: persist events in session 1 → process restart → create fresh
    runner with empty step store that loads events from file → call each
    build_*_history_view() and verify no AttributeError.
    """

    @staticmethod
    def _persist_session(root, session_id, num_steps=3):
        """Write steps to a persistent session, return (root, session_id)."""
        step_store = AgentStepStore.for_session(
            session_id, persist=True, root=root,
        )
        for i in range(num_steps):
            step = step_store.create_step(
                iteration=i, mode="act", runner_type="cot",
            )
            step_store.update_step_after_parse(
                step, thought=f"Step {i}", action_name="read_file",
                action_input={"path": f"/tmp/f{i}.py"},
            )
            step_store.update_step_after_tool(
                step, observation=f"contents of file {i}",
                tool_meta={"success": True, "tool_name": "read_file"},
            )
        return root, session_id

    @staticmethod
    def _make_resume_coder(root, session_id, runner_type="cot"):
        """Create a coder + runner with an empty step store that reads events from file."""
        from aicoder.tests.conftest import make_mock_coder
        from aicoder.tools.registry import ToolRegistry
        from aicoder.runners.cot_agent_runner import CotAgentRunner
        from aicoder.runners import register_runner

        coder = make_mock_coder(root=root)
        coder.session_id = session_id
        coder.done_messages = [
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "I'll help fix it."},
        ]

        # Create step store that reads events from file (empty steps in memory)
        step_store = AgentStepStore.for_session(
            session_id, persist=True, root=root,
        )
        # Verify: steps are empty (no in-memory objects) but events loaded from file
        assert step_store.load_steps() == []

        registry = ToolRegistry()
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry=registry, step_store=step_store,
        )
        register_runner(session_id, runner)
        return coder, runner

    @staticmethod
    def _cleanup(session_id):
        from aicoder.runners import unregister_runner
        unregister_runner(session_id)

    # -- UI view --

    def test_ui_view_resume_no_attribute_error(self):
        """build_ui_history_view must not raise AttributeError after resume."""
        import tempfile
        root = tempfile.mkdtemp()
        self._persist_session(root, "resume-ui-1", num_steps=3)

        coder, runner = self._make_resume_coder(root, "resume-ui-1")

        from aicoder.context.history_view import build_ui_history_view
        view = build_ui_history_view(coder, "act", "cot")

        assert isinstance(view, list)
        assert len(view) > 0

        # Should have done_messages entries + replay entries
        sources = [e.get("source") for e in view]
        assert "done_messages" in sources
        assert "step" in sources

        # Step entries should have expected keys (no attribute access errors)
        for entry in view:
            if entry.get("source") == "step":
                assert "iteration" in entry
                assert "status" in entry

        self._cleanup("resume-ui-1")

    def test_ui_view_resume_contains_step_data(self):
        """UI view after resume should contain thought and action data."""
        import tempfile
        root = tempfile.mkdtemp()
        self._persist_session(root, "resume-ui-2", num_steps=2)

        coder, runner = self._make_resume_coder(root, "resume-ui-2")

        from aicoder.context.history_view import build_ui_history_view
        view = build_ui_history_view(coder, "act", "cot")

        step_entries = [e for e in view if e.get("source") == "step"]
        assert len(step_entries) == 2

        # First step should have thought and action
        first = step_entries[0]
        assert first.get("thought") == "Step 0"
        assert first.get("action_name") == "read_file"

        self._cleanup("resume-ui-2")

    # -- Runtime view --

    def test_runtime_view_resume_no_attribute_error(self):
        """build_runtime_history_view must not raise AttributeError after resume."""
        import tempfile
        root = tempfile.mkdtemp()
        self._persist_session(root, "resume-rt-1", num_steps=3)

        coder, runner = self._make_resume_coder(root, "resume-rt-1")

        from aicoder.context.history_view import build_runtime_history_view
        view = build_runtime_history_view(coder, "act", "cot")

        assert isinstance(view, list)
        assert len(view) >= 3

        # Each entry should be a dict with expected keys
        for entry in view:
            assert isinstance(entry, dict)
            assert "iteration" in entry
            assert "status" in entry

        self._cleanup("resume-rt-1")

    def test_runtime_view_resume_has_action_observation(self):
        """Runtime view after resume should contain action and observation."""
        import tempfile
        root = tempfile.mkdtemp()
        self._persist_session(root, "resume-rt-2", num_steps=2)

        coder, runner = self._make_resume_coder(root, "resume-rt-2")

        from aicoder.context.history_view import build_runtime_history_view
        view = build_runtime_history_view(coder, "act", "cot")

        assert len(view) >= 2
        first = view[0]
        assert "action" in first
        assert first["action"]["tool_name"] == "read_file"
        assert "observation" in first
        assert "contents of file 0" in first["observation"]["output"]

        self._cleanup("resume-rt-2")

    # -- LLM view (via runner.build_history_messages) --

    def test_llm_view_resume_via_runner(self):
        """runner.build_history_messages() should replay from events after resume."""
        import tempfile
        root = tempfile.mkdtemp()
        self._persist_session(root, "resume-llm-1", num_steps=3)

        coder, runner = self._make_resume_coder(root, "resume-llm-1")

        # runner.build_history_messages() should use replay, not return bare done_messages
        messages = runner.build_history_messages()

        assert isinstance(messages, list)
        # Should have done_messages + replayed tool messages
        assert len(messages) > 2  # more than just done_messages

        # Should contain assistant messages from replayed steps
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        assert len(assistant_msgs) > 0

        self._cleanup("resume-llm-1")

    def test_llm_view_resume_cot_format(self):
        """CoT runner build_history_messages should produce user/assistant pairs."""
        import tempfile
        root = tempfile.mkdtemp()
        self._persist_session(root, "resume-llm-2", num_steps=2)

        coder, runner = self._make_resume_coder(root, "resume-llm-2")
        messages = runner.build_history_messages()

        # Should have done_messages + replayed pairs
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        assert len(user_msgs) > 0
        assert len(assistant_msgs) > 0

        self._cleanup("resume-llm-2")

    # -- LLM view via build_llm_history_view --

    def test_llm_view_build_function_resume(self):
        """build_llm_history_view should work through runner after resume."""
        import tempfile
        root = tempfile.mkdtemp()
        self._persist_session(root, "resume-llm-build-1", num_steps=2)

        coder, runner = self._make_resume_coder(root, "resume-llm-build-1")

        from aicoder.context.history_view import build_llm_history_view
        messages = build_llm_history_view(coder, "act", "cot")

        assert isinstance(messages, list)
        assert len(messages) > 0

        self._cleanup("resume-llm-build-1")

    # -- No events edge case --

    def test_views_with_no_events_no_crash(self):
        """Views should handle coder with no events gracefully."""
        import tempfile
        from aicoder.tests.conftest import make_mock_coder
        from aicoder.context.history_view import (
            build_ui_history_view,
            build_runtime_history_view,
            build_llm_history_view,
        )

        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        coder.session_id = "no-events-view"
        coder.done_messages = [{"role": "user", "content": "hi"}]

        ui = build_ui_history_view(coder, "act", "cot")
        rt = build_runtime_history_view(coder, "act", "cot")
        llm = build_llm_history_view(coder, "act", "cot")

        assert isinstance(ui, list)
        assert isinstance(rt, list)
        assert isinstance(llm, list)
        assert len(ui) >= 1  # at least done_messages
        assert len(rt) == 0  # no steps
        assert len(llm) >= 1  # done_messages fallback
