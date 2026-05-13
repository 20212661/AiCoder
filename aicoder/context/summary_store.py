"""Persistent summary store — save and load CondensationSnapshots.

Snapshots are stored as individual JSON files under:
    <root>/.aicoder/summaries/<session_id>/<snapshot_id>.json

This preserves history versions and keeps the store separate from the
event store (.aicoder/events/).

All I/O errors are caught and returned as graceful fallbacks (None / []).
The main chain must never crash due to summary store failures.
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from .summary_types import CondensationSnapshot


def _summaries_dir(root: str, session_id: str) -> str:
    return os.path.join(root, ".aicoder", "summaries", session_id)


def save_snapshot(
    snapshot: CondensationSnapshot,
    root: str,
) -> bool:
    """Persist a snapshot to disk.

    Returns True on success, False on any I/O error.
    Never raises — callers can ignore the return value if they don't care.
    """
    try:
        dest_dir = _summaries_dir(root, snapshot.session_id)
        os.makedirs(dest_dir, exist_ok=True)
        path = os.path.join(dest_dir, f"{snapshot.snapshot_id}.json")
        data = snapshot.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def load_snapshot(
    snapshot_id: str,
    session_id: str,
    root: str,
) -> CondensationSnapshot | None:
    """Load a specific snapshot by ID.

    Returns None if the file doesn't exist or is corrupted.
    """
    try:
        path = os.path.join(_summaries_dir(root, session_id), f"{snapshot_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return CondensationSnapshot.from_dict(data)
    except Exception:
        return None


def load_latest_snapshot(
    session_id: str,
    root: str,
) -> CondensationSnapshot | None:
    """Load the most recent snapshot for a session.

    "Most recent" is determined by created_at timestamp.
    Returns None if no snapshots exist or all are corrupted.
    """
    snapshots = list_snapshots(session_id, root)
    if not snapshots:
        return None
    # Sort by created_at descending
    snapshots.sort(key=lambda s: s.created_at, reverse=True)
    return snapshots[0]


def list_snapshots(
    session_id: str,
    root: str,
) -> list[CondensationSnapshot]:
    """List all snapshots for a session.

    Skips corrupted files silently.
    """
    dest_dir = _summaries_dir(root, session_id)
    if not os.path.isdir(dest_dir):
        return []

    results: list[CondensationSnapshot] = []
    for fname in os.listdir(dest_dir):
        if not fname.endswith(".json"):
            continue
        try:
            path = os.path.join(dest_dir, fname)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            snap = CondensationSnapshot.from_dict(data)
            results.append(snap)
        except Exception:
            continue

    return results
