"""Tests for event persistence infrastructure (v1.4).

Phase 1: EventBackend abstraction and AgentEventStore composition.
Phase 2: Serializer and FileEventBackend.
"""
import json
import os
import tempfile

import pytest

from aicoder.events.backend import EventBackend, InMemoryEventBackend
from aicoder.events.file_store import FileEventBackend
from aicoder.events.serializer import event_to_dict, event_from_dict
from aicoder.events.store import AgentEventStore
from aicoder.events.types import AgentEventRecord, EventKind


# ---------------------------------------------------------------------------
# InMemoryEventBackend
# ---------------------------------------------------------------------------


class TestInMemoryEventBackend:
    def test_append_and_all_events(self):
        backend = InMemoryEventBackend()
        ev = AgentEventRecord(
            event_id="e1", session_id="s1", iteration=0,
            kind="step_started", payload={"mode": "act"},
        )
        backend.append(ev)
        assert len(backend.all_events()) == 1
        assert backend.all_events()[0].event_id == "e1"

    def test_append_many(self):
        backend = InMemoryEventBackend()
        events = [
            AgentEventRecord(event_id=f"e{i}", session_id="s1", iteration=i, kind="tool_call")
            for i in range(3)
        ]
        backend.append_many(events)
        assert len(backend.all_events()) == 3

    def test_list_events_filter_by_kind(self):
        backend = InMemoryEventBackend()
        backend.append(AgentEventRecord(event_id="e1", session_id="s1", iteration=0, kind="step_started"))
        backend.append(AgentEventRecord(event_id="e2", session_id="s1", iteration=0, kind="tool_call"))
        backend.append(AgentEventRecord(event_id="e3", session_id="s1", iteration=0, kind="tool_result"))

        result = backend.list_events(kind="tool_call")
        assert len(result) == 1
        assert result[0].event_id == "e2"

    def test_list_events_filter_by_iteration(self):
        backend = InMemoryEventBackend()
        for i in range(3):
            backend.append(AgentEventRecord(event_id=f"e{i}", session_id="s1", iteration=i, kind="step_started"))

        result = backend.list_events(iteration=1)
        assert len(result) == 1
        assert result[0].iteration == 1

    def test_list_events_limit(self):
        backend = InMemoryEventBackend()
        for i in range(5):
            backend.append(AgentEventRecord(event_id=f"e{i}", session_id="s1", iteration=i, kind="step_started"))

        result = backend.list_events(limit=2)
        assert len(result) == 2
        # Returns last N
        assert result[0].iteration == 3
        assert result[1].iteration == 4

    def test_last_event_no_filter(self):
        backend = InMemoryEventBackend()
        backend.append(AgentEventRecord(event_id="e1", session_id="s1", iteration=0, kind="step_started"))
        backend.append(AgentEventRecord(event_id="e2", session_id="s1", iteration=1, kind="step_started"))

        last = backend.last_event()
        assert last.event_id == "e2"

    def test_last_event_with_kind(self):
        backend = InMemoryEventBackend()
        backend.append(AgentEventRecord(event_id="e1", session_id="s1", iteration=0, kind="step_started"))
        backend.append(AgentEventRecord(event_id="e2", session_id="s1", iteration=0, kind="tool_call"))
        backend.append(AgentEventRecord(event_id="e3", session_id="s1", iteration=1, kind="step_started"))

        last = backend.last_event(kind="tool_call")
        assert last.event_id == "e2"

    def test_last_event_empty(self):
        backend = InMemoryEventBackend()
        assert backend.last_event() is None

    def test_empty_backend(self):
        backend = InMemoryEventBackend()
        assert backend.all_events() == []
        assert backend.list_events() == []


# ---------------------------------------------------------------------------
# EventBackend protocol compliance
# ---------------------------------------------------------------------------


class TestEventBackendProtocol:
    def test_in_memory_satisfies_protocol(self):
        backend = InMemoryEventBackend()
        assert isinstance(backend, EventBackend)


# ---------------------------------------------------------------------------
# AgentEventStore with backend composition (Phase 1)
# ---------------------------------------------------------------------------


class TestAgentEventStoreBackendComposition:
    def test_default_backend_is_in_memory(self):
        store = AgentEventStore(session_id="s1")
        assert isinstance(store.backend, InMemoryEventBackend)

    def test_custom_backend(self):
        backend = InMemoryEventBackend()
        store = AgentEventStore(session_id="s1", backend=backend)
        assert store.backend is backend

    def test_append_goes_to_backend(self):
        store = AgentEventStore(session_id="s1")
        record = store.append(iteration=0, kind="step_started", payload={"mode": "act"})
        assert len(store.backend.all_events()) == 1
        assert record.kind == "step_started"

    def test_append_many_goes_to_backend(self):
        store = AgentEventStore(session_id="s1")
        events = [
            AgentEventRecord(event_id=f"e{i}", session_id="s1", iteration=i, kind="tool_call")
            for i in range(3)
        ]
        store.append_many(events)
        assert len(store.backend.all_events()) == 3

    def test_list_events_delegates_to_backend(self):
        store = AgentEventStore(session_id="s1")
        store.append(iteration=0, kind="step_started")
        store.append(iteration=0, kind="tool_call")
        store.append(iteration=1, kind="step_started")

        assert len(store.list_events(kind="step_started")) == 2
        assert len(store.list_events(iteration=0)) == 2
        assert len(store.list_events(limit=1)) == 1

    def test_last_event_delegates_to_backend(self):
        store = AgentEventStore(session_id="s1")
        store.append(iteration=0, kind="step_started")
        store.append(iteration=0, kind="tool_result")

        last = store.last_event()
        assert last.kind == "tool_result"

        last_tool = store.last_event(kind="step_started")
        assert last_tool.kind == "step_started"

    def test_all_events_delegates_to_backend(self):
        store = AgentEventStore(session_id="s1")
        store.append(iteration=0, kind="step_started")
        store.append(iteration=1, kind="step_started")
        assert len(store.all_events()) == 2

    def test_events_for_iteration(self):
        store = AgentEventStore(session_id="s1")
        store.append(iteration=0, kind="step_started")
        store.append(iteration=0, kind="tool_call")
        store.append(iteration=1, kind="step_started")

        result = store.events_for_iteration(0)
        assert len(result) == 2

    def test_session_id_preserved(self):
        store = AgentEventStore(session_id="my-session")
        assert store.session_id == "my-session"

    def test_generated_event_id_unique(self):
        store = AgentEventStore(session_id="s1")
        r1 = store.append(iteration=0, kind="step_started")
        r2 = store.append(iteration=1, kind="step_started")
        assert r1.event_id != r2.event_id

    def test_payload_default_empty_dict(self):
        store = AgentEventStore(session_id="s1")
        record = store.append(iteration=0, kind="step_started")
        assert record.payload == {}

    def test_payload_preserved(self):
        store = AgentEventStore(session_id="s1")
        record = store.append(iteration=0, kind="tool_call", payload={"tool": "read_file"})
        assert record.payload["tool"] == "read_file"


# ---------------------------------------------------------------------------
# Backward compatibility — old API still works
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_old_construction_still_works(self):
        """AgentEventStore(session_id) without backend should still work."""
        store = AgentEventStore(session_id="compat-test")
        store.append(iteration=0, kind="step_started")
        assert len(store.all_events()) == 1

    def test_agent_step_store_unchanged(self):
        """AgentStepStore should still create AgentEventStore normally."""
        from aicoder.agent_step_store import AgentStepStore
        step_store = AgentStepStore(session_id="compat-step")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, action_name="read_file")
        step_store.update_step_after_tool(step, observation="ok")

        events = step_store.event_store.all_events()
        assert len(events) >= 3  # step_started, tool_call, tool_result


# ---------------------------------------------------------------------------
# Serializer round-trip (Phase 2)
# ---------------------------------------------------------------------------


class TestSerializer:
    def test_round_trip_basic(self):
        ev = AgentEventRecord(
            event_id="e1", session_id="s1", iteration=0,
            kind="tool_call", payload={"tool": "read_file", "path": "/tmp/a.py"},
            created_at=1234567890.0,
        )
        d = event_to_dict(ev)
        restored = event_from_dict(d)

        assert restored.event_id == "e1"
        assert restored.session_id == "s1"
        assert restored.iteration == 0
        assert restored.kind == "tool_call"
        assert restored.payload["tool"] == "read_file"
        assert restored.created_at == 1234567890.0

    def test_round_trip_minimal(self):
        ev = AgentEventRecord(
            event_id="e2", session_id="s2", iteration=3, kind="step_started",
        )
        d = event_to_dict(ev)
        restored = event_from_dict(d)
        assert restored.payload == {}

    def test_dict_is_json_serializable(self):
        ev = AgentEventRecord(
            event_id="e3", session_id="s3", iteration=1,
            kind="tool_result", payload={"obs": "result", "count": 42},
        )
        d = event_to_dict(ev)
        text = json.dumps(d)
        parsed = json.loads(text)
        assert parsed["payload"]["count"] == 42

    def test_from_dict_missing_payload_defaults_empty(self):
        d = {"event_id": "e4", "session_id": "s4", "iteration": 0, "kind": "step_started"}
        ev = event_from_dict(d)
        assert ev.payload == {}

    def test_from_dict_missing_created_at_defaults_zero(self):
        d = {"event_id": "e5", "session_id": "s5", "iteration": 0, "kind": "step_started"}
        ev = event_from_dict(d)
        assert ev.created_at == 0.0

    def test_from_dict_missing_required_raises(self):
        with pytest.raises(KeyError):
            event_from_dict({"session_id": "s1"})


# ---------------------------------------------------------------------------
# FileEventBackend (Phase 2)
# ---------------------------------------------------------------------------


class TestFileEventBackend:
    def _make_backend(self, session_id="test-file-session", root=None):
        root = root or tempfile.mkdtemp()
        return FileEventBackend(session_id=session_id, root=root), root

    def test_append_creates_file(self):
        backend, root = self._make_backend()
        ev = AgentEventRecord(
            event_id="e1", session_id="test-file-session", iteration=0,
            kind="step_started", payload={"mode": "act"},
        )
        backend.append(ev)
        assert os.path.exists(backend.path)

    def test_append_and_all_events(self):
        backend, root = self._make_backend()
        ev = AgentEventRecord(
            event_id="e1", session_id="test-file-session", iteration=0,
            kind="step_started",
        )
        backend.append(ev)
        events = backend.all_events()
        assert len(events) == 1
        assert events[0].event_id == "e1"

    def test_append_many(self):
        backend, root = self._make_backend()
        events = [
            AgentEventRecord(event_id=f"e{i}", session_id="test-file-session",
                             iteration=i, kind="step_started")
            for i in range(3)
        ]
        backend.append_many(events)
        assert len(backend.all_events()) == 3

    def test_cross_instance_read(self):
        """Events written by one instance should be readable by a new instance."""
        backend1, root = self._make_backend(session_id="cross-inst")
        ev = AgentEventRecord(
            event_id="e1", session_id="cross-inst", iteration=0,
            kind="tool_call", payload={"tool": "read_file"},
        )
        backend1.append(ev)

        # New instance pointing to same file
        backend2 = FileEventBackend(session_id="cross-inst", root=root)
        events = backend2.all_events()
        assert len(events) == 1
        assert events[0].payload["tool"] == "read_file"

    def test_list_events_filter(self):
        backend, root = self._make_backend()
        backend.append(AgentEventRecord(event_id="e1", session_id="test-file-session",
                                        iteration=0, kind="step_started"))
        backend.append(AgentEventRecord(event_id="e2", session_id="test-file-session",
                                        iteration=0, kind="tool_call"))
        backend.append(AgentEventRecord(event_id="e3", session_id="test-file-session",
                                        iteration=1, kind="step_started"))

        assert len(backend.list_events(kind="step_started")) == 2
        assert len(backend.list_events(iteration=0)) == 2
        assert len(backend.list_events(limit=1)) == 1

    def test_last_event(self):
        backend, root = self._make_backend()
        backend.append(AgentEventRecord(event_id="e1", session_id="test-file-session",
                                        iteration=0, kind="step_started"))
        backend.append(AgentEventRecord(event_id="e2", session_id="test-file-session",
                                        iteration=0, kind="tool_result"))

        assert backend.last_event().kind == "tool_result"
        assert backend.last_event(kind="step_started").event_id == "e1"
        assert backend.last_event(kind="tool_error") is None

    def test_empty_backend(self):
        backend, root = self._make_backend()
        assert backend.all_events() == []
        assert backend.last_event() is None

    def test_payload_fidelity(self):
        """Complex payloads survive serialization round-trip."""
        backend, root = self._make_backend()
        ev = AgentEventRecord(
            event_id="e1", session_id="test-file-session", iteration=0,
            kind="tool_result",
            payload={
                "observation": "file content",
                "files": ["/tmp/a.py", "/tmp/b.py"],
                "tool_meta": {
                    "success": True,
                    "duration_ms": 150,
                    "nested": {"key": "value"},
                },
            },
        )
        backend.append(ev)

        # Read back via new instance to force file round-trip
        backend2 = FileEventBackend(session_id="test-file-session", root=root)
        events = backend2.all_events()
        assert len(events) == 1
        assert events[0].payload["files"] == ["/tmp/a.py", "/tmp/b.py"]
        assert events[0].payload["tool_meta"]["nested"]["key"] == "value"

    def test_corrupted_line_skipped(self):
        """Corrupted lines in JSONL should be silently skipped."""
        backend, root = self._make_backend(session_id="corrupt-test")

        # Write valid event
        backend.append(AgentEventRecord(
            event_id="e1", session_id="corrupt-test", iteration=0, kind="step_started",
        ))

        # Manually append a corrupted line
        backend._cache = None  # clear cache
        with open(backend.path, "a", encoding="utf-8") as f:
            f.write("this is not json\n")

        # Read back — corrupted line should be skipped
        backend2 = FileEventBackend(session_id="corrupt-test", root=root)
        events = backend2.all_events()
        assert len(events) == 1

    def test_missing_file_returns_empty(self):
        """Non-existent file should return empty list."""
        backend = FileEventBackend(session_id="nonexistent", root=tempfile.mkdtemp())
        assert backend.all_events() == []

    def test_satisfies_protocol(self):
        backend, _ = self._make_backend()
        assert isinstance(backend, EventBackend)

    def test_jsonl_format(self):
        """Verify the file is valid JSONL."""
        backend, root = self._make_backend(session_id="jsonl-format")
        backend.append(AgentEventRecord(
            event_id="e1", session_id="jsonl-format", iteration=0, kind="step_started",
        ))
        backend.append(AgentEventRecord(
            event_id="e2", session_id="jsonl-format", iteration=0, kind="tool_call",
        ))

        with open(backend.path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        assert len(lines) == 2
        # Each line is valid JSON
        for line in lines:
            parsed = json.loads(line)
            assert "event_id" in parsed
            assert "kind" in parsed


# ---------------------------------------------------------------------------
# AgentEventStore with FileEventBackend integration
# ---------------------------------------------------------------------------


class TestAgentEventStoreWithFileBackend:
    def test_store_with_file_backend(self):
        root = tempfile.mkdtemp()
        backend = FileEventBackend(session_id="file-store-1", root=root)
        store = AgentEventStore(session_id="file-store-1", backend=backend)

        store.append(iteration=0, kind="step_started", payload={"mode": "act"})
        store.append(iteration=0, kind="tool_call", payload={"tool": "read_file"})

        # Read via new store instance
        backend2 = FileEventBackend(session_id="file-store-1", root=root)
        store2 = AgentEventStore(session_id="file-store-1", backend=backend2)
        assert len(store2.all_events()) == 2

    def test_step_store_with_file_backend(self):
        """AgentStepStore with file backend should persist lifecycle events."""
        from aicoder.agent_step_store import AgentStepStore

        root = tempfile.mkdtemp()
        backend = FileEventBackend(session_id="step-file-1", root=root)
        event_store = AgentEventStore(session_id="step-file-1", backend=backend)

        step_store = AgentStepStore(session_id="step-file-1", event_store=event_store)
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, action_name="read_file")
        step_store.update_step_after_tool(step, observation="ok")

        # Rebuild from file
        backend2 = FileEventBackend(session_id="step-file-1", root=root)
        store2 = AgentEventStore(session_id="step-file-1", backend=backend2)
        events = store2.all_events()
        assert len(events) >= 3  # step_started, tool_call, tool_result


# ---------------------------------------------------------------------------
# Phase 3: for_session factory and StepStore integration
# ---------------------------------------------------------------------------


class TestForSessionFactory:
    def test_default_is_in_memory(self):
        store = AgentEventStore.for_session("factory-1")
        assert isinstance(store.backend, InMemoryEventBackend)

    def test_persist_false_is_in_memory(self):
        store = AgentEventStore.for_session("factory-2", persist=False)
        assert isinstance(store.backend, InMemoryEventBackend)

    def test_persist_true_creates_file_backend(self):
        root = tempfile.mkdtemp()
        store = AgentEventStore.for_session("factory-3", persist=True, root=root)
        assert isinstance(store.backend, FileEventBackend)

    def test_persist_true_no_root_falls_back_to_memory(self):
        """If persist=True but no root, should fall back to in-memory."""
        store = AgentEventStore.for_session("factory-4", persist=True, root="")
        assert isinstance(store.backend, InMemoryEventBackend)

    def test_persist_true_writes_and_reads(self):
        root = tempfile.mkdtemp()
        store1 = AgentEventStore.for_session("factory-5", persist=True, root=root)
        store1.append(iteration=0, kind="step_started", payload={"mode": "act"})
        store1.append(iteration=0, kind="tool_call", payload={"tool": "read_file"})

        # New instance reads from file
        store2 = AgentEventStore.for_session("factory-5", persist=True, root=root)
        events = store2.all_events()
        assert len(events) == 2
        assert events[0].kind == "step_started"
        assert events[1].kind == "tool_call"


class TestStepStoreWithPersistence:
    def test_step_lifecycle_persists_to_file(self):
        """Full step lifecycle events should be persisted to JSONL."""
        from aicoder.agent_step_store import AgentStepStore

        root = tempfile.mkdtemp()
        event_store = AgentEventStore.for_session("persist-step-1", persist=True, root=root)
        step_store = AgentStepStore(session_id="persist-step-1", event_store=event_store)

        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, thought="Read file", action_name="read_file")
        step_store.update_step_after_tool(step, observation="contents", tool_meta={"success": True})

        # Rebuild from file
        store2 = AgentEventStore.for_session("persist-step-1", persist=True, root=root)
        events = store2.all_events()

        kinds = [e.kind for e in events]
        assert "step_started" in kinds
        assert "assistant_thought" in kinds
        assert "tool_call" in kinds
        assert "tool_result" in kinds

    def test_multi_iteration_persistence(self):
        """Multiple iterations should all persist."""
        from aicoder.agent_step_store import AgentStepStore

        root = tempfile.mkdtemp()
        event_store = AgentEventStore.for_session("persist-multi", persist=True, root=root)
        step_store = AgentStepStore(session_id="persist-multi", event_store=event_store)

        for i in range(3):
            step = step_store.create_step(iteration=i, mode="act", runner_type="cot")
            step_store.update_step_after_parse(step, action_name="read_file")
            step_store.update_step_after_tool(step, observation=f"content {i}")

        # Rebuild
        store2 = AgentEventStore.for_session("persist-multi", persist=True, root=root)
        events = store2.all_events()
        assert len(events) >= 9  # 3 iterations * (step_started + tool_call + tool_result)

    def test_memory_step_store_unchanged(self):
        """Non-persistent step store should still work identically."""
        from aicoder.agent_step_store import AgentStepStore

        step_store = AgentStepStore(session_id="mem-only")
        step = step_store.create_step(iteration=0, mode="act", runner_type="cot")
        step_store.update_step_after_parse(step, action_name="read_file")
        step_store.update_step_after_tool(step, observation="ok")

        assert isinstance(step_store.event_store.backend, InMemoryEventBackend)
        assert len(step_store.event_store.all_events()) >= 3
