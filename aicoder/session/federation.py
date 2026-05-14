"""Session Federation metadata layer.

Manages TaskThread and SessionLink relationships for cross-session continuity.
Persisted to ``.aicoder/session_federation/<task_thread_id>/`` as JSON files.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FederationPolicy:
    """Controls federation behavior: how many sessions to link and restore."""

    max_linked_sessions: int = 20
    max_restore_sessions: int = 5
    federation_tokens: int = 4096


@dataclass
class SessionLink:
    """A link between a task thread and a session."""

    session_id: str
    role: str  # "parent" | "child" | "continuation"
    linked_at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskThread:
    """A thread of related sessions forming a task cluster."""

    task_thread_id: str
    created_at: float = field(default_factory=time.time)
    links: list[SessionLink] = field(default_factory=list)


def _fed_dir(root: str) -> Path:
    return Path(root) / ".aicoder" / "session_federation"


def _thread_dir(root: str, task_thread_id: str) -> Path:
    return _fed_dir(root) / task_thread_id


def _thread_meta_path(root: str, task_thread_id: str) -> Path:
    return _thread_dir(root, task_thread_id) / "thread_meta.json"


def _links_path(root: str, task_thread_id: str) -> Path:
    return _thread_dir(root, task_thread_id) / "links.json"


def create_task_thread(root: str = "") -> TaskThread:
    """Create a new TaskThread and persist it to disk."""
    tt_id = f"tt-{uuid.uuid4().hex[:16]}"
    tt = TaskThread(task_thread_id=tt_id)

    if root:
        d = _thread_dir(root, tt_id)
        d.mkdir(parents=True, exist_ok=True)
        meta = {
            "task_thread_id": tt.task_thread_id,
            "created_at": tt.created_at,
        }
        _thread_meta_path(root, tt_id).write_text(
            json.dumps(meta, indent=2), encoding="utf-8",
        )
        _links_path(root, tt_id).write_text("[]", encoding="utf-8")

    return tt


def load_task_thread(task_thread_id: str, root: str = "") -> TaskThread | None:
    """Load a TaskThread from disk. Returns None if not found."""
    if not root:
        return None

    meta_path = _thread_meta_path(root, task_thread_id)
    if not meta_path.exists():
        return None

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    links = _load_links(root, task_thread_id)

    return TaskThread(
        task_thread_id=meta["task_thread_id"],
        created_at=meta["created_at"],
        links=links,
    )


def _load_links(root: str, task_thread_id: str) -> list[SessionLink]:
    links_path = _links_path(root, task_thread_id)
    if not links_path.exists():
        return []
    raw = json.loads(links_path.read_text(encoding="utf-8"))
    return [
        SessionLink(
            session_id=entry["session_id"],
            role=entry["role"],
            linked_at=entry.get("linked_at", 0),
            meta=entry.get("meta", {}),
        )
        for entry in raw
    ]


def _save_links(root: str, task_thread_id: str, links: list[SessionLink]) -> None:
    links_path = _links_path(root, task_thread_id)
    data = [
        {
            "session_id": link.session_id,
            "role": link.role,
            "linked_at": link.linked_at,
            "meta": link.meta,
        }
        for link in links
    ]
    links_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def link_session(
    task_thread_id: str,
    session_id: str,
    role: str = "child",
    meta: dict[str, Any] | None = None,
    root: str = "",
) -> SessionLink:
    """Link a session to a task thread. Raises ValueError if thread not found."""
    if root:
        tt = load_task_thread(task_thread_id, root=root)
        if tt is None:
            raise ValueError(f"TaskThread {task_thread_id!r} not found")

        existing = [l for l in tt.links if l.session_id == session_id]
        if existing:
            return existing[0]

        link = SessionLink(
            session_id=session_id,
            role=role,
            meta=meta or {},
        )
        tt.links.append(link)
        _save_links(root, task_thread_id, tt.links)
        return link
    else:
        return SessionLink(session_id=session_id, role=role, meta=meta or {})


def list_linked_sessions(
    task_thread_id: str,
    root: str = "",
) -> list[SessionLink]:
    """List all sessions linked to a task thread, ordered by linked_at."""
    if root:
        tt = load_task_thread(task_thread_id, root=root)
        if tt is None:
            return []
        return sorted(tt.links, key=lambda l: l.linked_at)
    return []
