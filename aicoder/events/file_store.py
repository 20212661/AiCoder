"""File-backed event storage — JSONL persistence for AgentEventRecords.

Each session gets one file at ``<root>/.aicoder/events/<session_id>.jsonl``.
Append-only writes; full scan on read. Graceful fallback on any I/O error.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .backend import EventBackend
from .serializer import event_to_dict, event_from_dict
from .types import AgentEventRecord, EventKind


def _default_events_dir(root: str) -> str:
    return os.path.join(root, ".aicoder", "events")


class FileEventBackend:
    """Append-only JSONL event backend.

    Writes each event as one JSON line. Reads by scanning the full file.
    Thread safety is NOT guaranteed — caller must serialize if needed.
    """

    def __init__(self, session_id: str, *, root: str) -> None:
        self._session_id = session_id
        self._path = os.path.join(_default_events_dir(root), f"{session_id}.jsonl")
        self._cache: list[AgentEventRecord] | None = None

    @property
    def path(self) -> str:
        return self._path

    def append(self, event: AgentEventRecord) -> None:
        self._ensure_dir()
        line = json.dumps(event_to_dict(event), ensure_ascii=False)
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass  # graceful fallback — write failure must not crash main chain
        if self._cache is not None:
            self._cache.append(event)

    def append_many(self, events: list[AgentEventRecord]) -> None:
        if not events:
            return
        self._ensure_dir()
        lines = [json.dumps(event_to_dict(e), ensure_ascii=False) for e in events]
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass
        if self._cache is not None:
            self._cache.extend(events)

    def all_events(self) -> list[AgentEventRecord]:
        return self._load()

    def list_events(
        self,
        *,
        kind: EventKind | None = None,
        iteration: int | None = None,
        limit: int | None = None,
    ) -> list[AgentEventRecord]:
        result = self._load()
        if kind is not None:
            result = [e for e in result if e.kind == kind]
        if iteration is not None:
            result = [e for e in result if e.iteration == iteration]
        if limit is not None:
            result = result[-limit:]
        return result

    def last_event(self, kind: EventKind | None = None) -> AgentEventRecord | None:
        events = self._load()
        if not events:
            return None
        if kind is None:
            return events[-1]
        for e in reversed(events):
            if e.kind == kind:
                return e
        return None

    def _load(self) -> list[AgentEventRecord]:
        if self._cache is not None:
            return list(self._cache)

        if not os.path.exists(self._path):
            self._cache = []
            return []

        events: list[AgentEventRecord] = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(event_from_dict(json.loads(line)))
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue  # skip corrupted lines
        except OSError:
            pass  # graceful fallback

        self._cache = events
        return list(events)

    def _ensure_dir(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
