"""Tests for persistent summary store."""
import json
import os
import tempfile

import pytest

from aicoder.context.summary_types import SummaryBlock, CondensationSnapshot
from aicoder.context.summary_store import (
    save_snapshot,
    load_snapshot,
    load_latest_snapshot,
    list_snapshots,
)


def _make_snapshot(session_id="s1", event_count=10, snapshot_id=None):
    return CondensationSnapshot(
        snapshot_id=snapshot_id or "snap-1",
        session_id=session_id,
        source_event_count=event_count,
        latest_event_id=f"ev-{event_count}",
        blocks=[
            SummaryBlock(
                summary_id="sb-1",
                covered_event_ids=[f"ev-{i}" for i in range(event_count)],
                covered_iterations=list(range(event_count // 3)),
                goal="Fix bug",
                findings=["Found X"],
                actions_taken=["read_file(a.py)"],
            ),
        ],
        mode="act",
    )


class TestSaveAndLoad:
    def test_save_and_load_roundtrip(self):
        root = tempfile.mkdtemp()
        snap = _make_snapshot(session_id="round-1")

        assert save_snapshot(snap, root) is True
        loaded = load_snapshot("snap-1", "round-1", root)

        assert loaded is not None
        assert loaded.snapshot_id == "snap-1"
        assert loaded.session_id == "round-1"
        assert loaded.source_event_count == 10
        assert len(loaded.blocks) == 1
        assert loaded.blocks[0].goal == "Fix bug"

    def test_save_creates_directory(self):
        root = tempfile.mkdtemp()
        snap = _make_snapshot(session_id="auto-dir")
        assert save_snapshot(snap, root) is True

        dest = os.path.join(root, ".aicoder", "summaries", "auto-dir")
        assert os.path.isdir(dest)
        assert os.path.exists(os.path.join(dest, "snap-1.json"))

    def test_load_nonexistent_returns_none(self):
        root = tempfile.mkdtemp()
        result = load_snapshot("no-snap", "no-session", root)
        assert result is None


class TestMultipleSnapshots:
    def test_list_snapshots_empty(self):
        root = tempfile.mkdtemp()
        result = list_snapshots("no-session", root)
        assert result == []

    def test_list_multiple_snapshots(self):
        root = tempfile.mkdtemp()
        s1 = _make_snapshot(session_id="multi-1", snapshot_id="snap-a")
        s2 = CondensationSnapshot(
            snapshot_id="snap-b",
            session_id="multi-1",
            source_event_count=5,
            latest_event_id="ev-5",
        )
        save_snapshot(s1, root)
        save_snapshot(s2, root)

        snaps = list_snapshots("multi-1", root)
        assert len(snaps) == 2
        ids = {s.snapshot_id for s in snaps}
        assert ids == {"snap-a", "snap-b"}

    def test_load_latest_snapshot(self):
        root = tempfile.mkdtemp()
        s1 = CondensationSnapshot(
            snapshot_id="snap-old",
            session_id="latest-1",
            source_event_count=3,
            latest_event_id="ev-3",
            created_at="2025-01-01T00:00:00+00:00",
        )
        s2 = CondensationSnapshot(
            snapshot_id="snap-new",
            session_id="latest-1",
            source_event_count=8,
            latest_event_id="ev-8",
            created_at="2025-06-01T00:00:00+00:00",
        )
        save_snapshot(s1, root)
        save_snapshot(s2, root)

        latest = load_latest_snapshot("latest-1", root)
        assert latest is not None
        assert latest.snapshot_id == "snap-new"
        assert latest.source_event_count == 8

    def test_different_sessions_isolated(self):
        root = tempfile.mkdtemp()
        sa = _make_snapshot(session_id="sess-a", snapshot_id="snap-a")
        sb = _make_snapshot(session_id="sess-b", snapshot_id="snap-b")
        save_snapshot(sa, root)
        save_snapshot(sb, root)

        assert len(list_snapshots("sess-a", root)) == 1
        assert len(list_snapshots("sess-b", root)) == 1
        assert list_snapshots("sess-a", root)[0].session_id == "sess-a"

    def test_overwrite_existing_snapshot(self):
        root = tempfile.mkdtemp()
        s1 = _make_snapshot(session_id="ow-1", event_count=5, snapshot_id="snap-ow")
        save_snapshot(s1, root)

        s2 = CondensationSnapshot(
            snapshot_id="snap-ow",
            session_id="ow-1",
            source_event_count=15,
            latest_event_id="ev-15",
        )
        save_snapshot(s2, root)

        loaded = load_snapshot("snap-ow", "ow-1", root)
        assert loaded.source_event_count == 15


class TestCorruptedFileFallback:
    def test_corrupted_file_returns_none(self):
        root = tempfile.mkdtemp()
        dest = os.path.join(root, ".aicoder", "summaries", "corrupt-1")
        os.makedirs(dest, exist_ok=True)

        with open(os.path.join(dest, "snap-bad.json"), "w") as f:
            f.write("not json at all")

        result = load_snapshot("snap-bad", "corrupt-1", root)
        assert result is None

    def test_corrupted_file_skipped_in_list(self):
        root = tempfile.mkdtemp()
        dest = os.path.join(root, ".aicoder", "summaries", "corrupt-2")
        os.makedirs(dest, exist_ok=True)

        # Write one valid and one corrupted
        s1 = _make_snapshot(session_id="corrupt-2", snapshot_id="snap-ok")
        save_snapshot(s1, root)

        with open(os.path.join(dest, "snap-bad.json"), "w") as f:
            f.write("broken{")

        snaps = list_snapshots("corrupt-2", root)
        assert len(snaps) == 1
        assert snaps[0].snapshot_id == "snap-ok"

    def test_latest_snapshot_all_corrupted(self):
        root = tempfile.mkdtemp()
        dest = os.path.join(root, ".aicoder", "summaries", "corrupt-3")
        os.makedirs(dest, exist_ok=True)

        with open(os.path.join(dest, "snap-a.json"), "w") as f:
            f.write("bad")
        with open(os.path.join(dest, "snap-b.json"), "w") as f:
            f.write("also bad")

        result = load_latest_snapshot("corrupt-3", root)
        assert result is None

    def test_non_json_file_ignored(self):
        root = tempfile.mkdtemp()
        dest = os.path.join(root, ".aicoder", "summaries", "mixed-1")
        os.makedirs(dest, exist_ok=True)

        s1 = _make_snapshot(session_id="mixed-1", snapshot_id="snap-ok")
        save_snapshot(s1, root)

        # Write a non-JSON file
        with open(os.path.join(dest, "notes.txt"), "w") as f:
            f.write("these are notes")

        snaps = list_snapshots("mixed-1", root)
        assert len(snaps) == 1
        assert snaps[0].snapshot_id == "snap-ok"


class TestSaveFailureGraceful:
    def test_save_to_invalid_root_returns_false(self):
        snap = _make_snapshot(session_id="bad-root")
        # Use a path with null byte which always fails on both OS
        result = save_snapshot(snap, "/tmp\x00bad")
        assert result is False

    def test_save_does_not_raise(self):
        snap = _make_snapshot(session_id="no-raise")
        # Should not raise even with invalid root
        try:
            save_snapshot(snap, "")
        except Exception:
            pytest.fail("save_snapshot raised an exception")
