"""
Session persistence — save, load, resume, and list conversation sessions.

Modeled after Cline's ~/.cline/tasks/<taskId>/ storage layout.
Each session is stored in ~/.aicoder/sessions/<session_id>/ with:
  - api_conversation_history.json  — raw user/assistant/tool messages
  - session_meta.json              — metadata (model, timestamps, counts)

A global index.json at ~/.aicoder/sessions/ tracks all past sessions.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SessionMeta:
    session_id: str
    created_at: float          # unix timestamp
    updated_at: float
    first_message: str         # user's first message
    model_name: str
    edit_format: str
    token_in: int = 0
    token_out: int = 0
    message_count: int = 0
    root: str = ""             # workspace root

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SessionMeta":
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sessions_dir() -> Path:
    return Path.home() / ".aicoder" / "sessions"


def _index_path() -> Path:
    return _sessions_dir() / "index.json"


def _session_dir(session_id: str) -> Path:
    return _sessions_dir() / session_id


def _read_json(path: Path) -> dict | list | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Index operations
# ---------------------------------------------------------------------------

def load_index() -> list[dict]:
    """Return the session index list, newest first."""
    data = _read_json(_index_path())
    if isinstance(data, list):
        data.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        return data
    return []


def upsert_index(meta: SessionMeta) -> None:
    """Insert or update a session entry in the index."""
    entries = load_index()
    entry = meta.to_dict()
    found = False
    for i, e in enumerate(entries):
        if e.get("session_id") == meta.session_id:
            entries[i] = entry
            found = True
            break
    if not found:
        entries.insert(0, entry)
    _write_json(_index_path(), entries)


def remove_index(session_id: str) -> None:
    entries = [e for e in load_index() if e.get("session_id") != session_id]
    _write_json(_index_path(), entries)


# ---------------------------------------------------------------------------
# Session save / load
# ---------------------------------------------------------------------------

def save_session(
    session_id: str,
    done_messages: list[dict],
    cur_messages: list[dict],
    meta: SessionMeta,
) -> None:
    """Persist an in-progress session to disk."""
    meta.updated_at = time.time()
    meta.message_count = len(done_messages) + len(cur_messages)
    sdir = _session_dir(session_id)
    sdir.mkdir(parents=True, exist_ok=True)

    _write_json(sdir / "session_meta.json", meta.to_dict())
    _write_json(sdir / "api_conversation_history.json", {
        "done_messages": done_messages,
        "cur_messages": cur_messages,
    })
    upsert_index(meta)


def load_session(session_id: str) -> tuple[SessionMeta, list[dict], list[dict]] | None:
    """Load a session from disk.  Returns (meta, done_messages, cur_messages)."""
    sdir = _session_dir(session_id)
    meta_dict = _read_json(sdir / "session_meta.json")
    history = _read_json(sdir / "api_conversation_history.json")

    if not meta_dict or not history:
        return None

    meta = SessionMeta.from_dict(meta_dict)
    done = history.get("done_messages", [])
    cur = history.get("cur_messages", [])
    return meta, done, cur


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def list_sessions() -> list[dict]:
    """Return all sessions from the index, newest first."""
    return load_index()


def delete_session(session_id: str) -> None:
    """Remove a session from disk and index."""
    import shutil

    sdir = _session_dir(session_id)
    if sdir.exists():
        shutil.rmtree(sdir, ignore_errors=True)
    remove_index(session_id)


def session_count() -> int:
    return len(load_index())
