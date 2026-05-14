"""Event store — composes a backend to store and query AgentEventRecords.

v1.4: Refactored to compose an EventBackend instead of holding _events directly.
Default backend is InMemoryEventBackend — zero behavioral change for existing callers.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from aicoder.events.types import AgentEventRecord, EventKind

if TYPE_CHECKING:
    from .backend import EventBackend


class AgentEventStore:
    """Lightweight event store backed by a pluggable EventBackend.

    Designed as a drop-in companion to AgentStepStore, recording fine-grained
    structured events at every step lifecycle point.

    The backend parameter defaults to InMemoryEventBackend, preserving
    the original behavior for all existing callers.
    """

    def __init__(
        self,
        session_id: str,
        *,
        backend: "EventBackend | None" = None,
    ) -> None:
        self._session_id = session_id
        if backend is not None:
            self._backend = backend
        else:
            from .backend import InMemoryEventBackend
            self._backend = InMemoryEventBackend()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def backend(self) -> "EventBackend":
        return self._backend

    # -- Mutation -----------------------------------------------------------

    def append(
        self,
        *,
        iteration: int,
        kind: EventKind,
        payload: dict | None = None,
    ) -> AgentEventRecord:
        record = AgentEventRecord(
            event_id=str(uuid.uuid4()),
            session_id=self._session_id,
            iteration=iteration,
            kind=kind,
            payload=payload or {},
        )
        self._backend.append(record)
        return record

    def append_many(
        self,
        records: list[AgentEventRecord],
    ) -> None:
        self._backend.append_many(records)

    # -- Queries ------------------------------------------------------------

    def list_events(
        self,
        *,
        kind: EventKind | None = None,
        iteration: int | None = None,
        limit: int | None = None,
    ) -> list[AgentEventRecord]:
        return self._backend.list_events(kind=kind, iteration=iteration, limit=limit)

    def events_for_iteration(self, iteration: int) -> list[AgentEventRecord]:
        return self._backend.list_events(iteration=iteration)

    def last_event(
        self,
        kind: EventKind | None = None,
    ) -> AgentEventRecord | None:
        return self._backend.last_event(kind=kind)

    def all_events(self) -> list[AgentEventRecord]:
        return self._backend.all_events()

    # -- Factory --------------------------------------------------------------

    @classmethod
    def for_session(
        cls,
        session_id: str,
        *,
        persist: bool = False,
        root: str = "",
    ) -> "AgentEventStore":
        """Create an AgentEventStore, optionally with file persistence.

        Args:
            session_id: Session identifier.
            persist: If True, use FileEventBackend for JSONL persistence.
            root: Project root directory (required for persist=True).
        """
        if persist and root:
            from .file_store import FileEventBackend
            backend = FileEventBackend(session_id=session_id, root=root)
            return cls(session_id, backend=backend)
        return cls(session_id)
