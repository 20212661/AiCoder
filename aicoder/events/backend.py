"""Event backend protocol and default in-memory implementation.

Defines the unified interface that all event storage backends must satisfy.
The default InMemoryEventBackend preserves the original list-based storage.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import AgentEventRecord, EventKind


@runtime_checkable
class EventBackend(Protocol):
    """Protocol for event storage backends.

    All backends (memory, file, future DB) must implement this interface.
    """

    def append(self, event: AgentEventRecord) -> None:
        """Append a single event record."""
        ...

    def append_many(self, events: list[AgentEventRecord]) -> None:
        """Append multiple event records."""
        ...

    def all_events(self) -> list[AgentEventRecord]:
        """Return all stored events in insertion order."""
        ...

    def list_events(
        self,
        *,
        kind: EventKind | None = None,
        iteration: int | None = None,
        limit: int | None = None,
    ) -> list[AgentEventRecord]:
        """Return events matching optional filters, most recent last."""
        ...

    def last_event(self, kind: EventKind | None = None) -> AgentEventRecord | None:
        """Return the most recent event, optionally filtered by kind."""
        ...


class InMemoryEventBackend:
    """Default in-memory event storage — a simple list."""

    def __init__(self) -> None:
        self._events: list[AgentEventRecord] = []

    def append(self, event: AgentEventRecord) -> None:
        self._events.append(event)

    def append_many(self, events: list[AgentEventRecord]) -> None:
        self._events.extend(events)

    def all_events(self) -> list[AgentEventRecord]:
        return list(self._events)

    def list_events(
        self,
        *,
        kind: EventKind | None = None,
        iteration: int | None = None,
        limit: int | None = None,
    ) -> list[AgentEventRecord]:
        result = self._events
        if kind is not None:
            result = [e for e in result if e.kind == kind]
        if iteration is not None:
            result = [e for e in result if e.iteration == iteration]
        if limit is not None:
            result = result[-limit:]
        return list(result)

    def last_event(self, kind: EventKind | None = None) -> AgentEventRecord | None:
        if not self._events:
            return None
        if kind is None:
            return self._events[-1]
        for e in reversed(self._events):
            if e.kind == kind:
                return e
        return None
