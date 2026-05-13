"""Tests for summary types: SummaryBlock and CondensationSnapshot structures."""
import pytest

from aicoder.context.summary_types import SummaryBlock, CondensationSnapshot


class TestSummaryBlock:
    def test_construction_minimal(self):
        block = SummaryBlock(summary_id="sb-1")
        assert block.summary_id == "sb-1"
        assert block.kind == "summary_block"
        assert block.covered_event_ids == []
        assert block.covered_iterations == []
        assert block.goal == ""
        assert block.findings == []
        assert block.actions_taken == []
        assert block.failures == []
        assert block.files_touched == []
        assert block.next_steps == []
        assert block.raw_text == ""

    def test_construction_full(self):
        block = SummaryBlock(
            summary_id="sb-2",
            kind="deterministic",
            covered_event_ids=["ev-1", "ev-2", "ev-3"],
            covered_iterations=[0, 1],
            goal="Fix the login bug",
            findings=["Bug is in auth.py line 42", "Token expiry is wrong"],
            actions_taken=["read_file(auth.py)", "search_files(token)"],
            failures=["Permission denied on config.yaml"],
            files_touched=["auth.py", "config.yaml"],
            next_steps=["Fix token expiry logic"],
            raw_text="Goal: Fix the login bug\n\nActions taken:\n  - read_file",
        )
        assert block.summary_id == "sb-2"
        assert block.kind == "deterministic"
        assert len(block.covered_event_ids) == 3
        assert block.covered_iterations == [0, 1]
        assert block.goal == "Fix the login bug"
        assert len(block.findings) == 2
        assert len(block.actions_taken) == 2
        assert len(block.failures) == 1
        assert block.files_touched == ["auth.py", "config.yaml"]
        assert len(block.next_steps) == 1
        assert "login bug" in block.raw_text

    def test_to_dict_roundtrip(self):
        block = SummaryBlock(
            summary_id="sb-rt",
            kind="test",
            covered_event_ids=["e1", "e2"],
            covered_iterations=[0],
            goal="test goal",
            findings=["found X"],
            actions_taken=["did Y"],
            failures=["failed Z"],
            files_touched=["a.py"],
            next_steps=["do W"],
            raw_text="raw",
        )
        d = block.to_dict()
        assert isinstance(d, dict)
        assert d["summary_id"] == "sb-rt"
        assert d["covered_event_ids"] == ["e1", "e2"]
        assert d["findings"] == ["found X"]

        restored = SummaryBlock.from_dict(d)
        assert restored.summary_id == block.summary_id
        assert restored.kind == block.kind
        assert restored.covered_event_ids == block.covered_event_ids
        assert restored.covered_iterations == block.covered_iterations
        assert restored.goal == block.goal
        assert restored.findings == block.findings
        assert restored.actions_taken == block.actions_taken
        assert restored.failures == block.failures
        assert restored.files_touched == block.files_touched
        assert restored.next_steps == block.next_steps
        assert restored.raw_text == block.raw_text

    def test_from_dict_missing_optional_fields(self):
        d = {"summary_id": "sb-min"}
        block = SummaryBlock.from_dict(d)
        assert block.summary_id == "sb-min"
        assert block.covered_event_ids == []
        assert block.findings == []
        assert block.goal == ""

    def test_format_text_with_goal(self):
        block = SummaryBlock(
            summary_id="sb-fmt",
            goal="Fix auth",
            actions_taken=["read_file(auth.py)"],
            findings=["Found bug at line 42"],
        )
        text = block.format_text()
        assert "Goal: Fix auth" in text
        assert "read_file(auth.py)" in text
        assert "Found bug at line 42" in text

    def test_format_text_empty_returns_raw(self):
        block = SummaryBlock(summary_id="sb-fmt2", raw_text="fallback text")
        text = block.format_text()
        assert text == "fallback text"

    def test_format_text_all_fields(self):
        block = SummaryBlock(
            summary_id="sb-fmt3",
            goal="Refactor module",
            actions_taken=["read_file(a.py)", "edit_file(a.py)"],
            findings=["Module has 3 functions"],
            failures=["Syntax error after edit"],
            next_steps=["Fix syntax error"],
            files_touched=["a.py"],
        )
        text = block.format_text()
        assert "Goal: Refactor module" in text
        assert "Actions taken:" in text
        assert "Findings:" in text
        assert "Failures:" in text
        assert "Next steps:" in text
        assert "Files touched:" in text

    def test_format_text_empty_block(self):
        block = SummaryBlock(summary_id="sb-empty")
        text = block.format_text()
        assert text == ""


class TestCondensationSnapshot:
    def test_construction_minimal(self):
        snap = CondensationSnapshot(
            snapshot_id="snap-1",
            session_id="sess-1",
            source_event_count=10,
            latest_event_id="ev-10",
        )
        assert snap.snapshot_id == "snap-1"
        assert snap.session_id == "sess-1"
        assert snap.source_event_count == 10
        assert snap.latest_event_id == "ev-10"
        assert snap.blocks == []
        assert snap.mode == ""
        assert snap.created_at != ""  # auto-filled

    def test_construction_with_blocks(self):
        block = SummaryBlock(
            summary_id="sb-1",
            covered_event_ids=["ev-1", "ev-2"],
            goal="Fix bug",
        )
        snap = CondensationSnapshot(
            snapshot_id="snap-2",
            session_id="sess-2",
            source_event_count=5,
            latest_event_id="ev-5",
            blocks=[block],
            mode="act",
        )
        assert len(snap.blocks) == 1
        assert snap.blocks[0].goal == "Fix bug"
        assert snap.mode == "act"

    def test_to_dict_roundtrip(self):
        block = SummaryBlock(
            summary_id="sb-rs",
            covered_event_ids=["e1"],
            covered_iterations=[0],
            goal="test",
        )
        snap = CondensationSnapshot(
            snapshot_id="snap-rs",
            session_id="sess-rs",
            source_event_count=3,
            latest_event_id="e3",
            blocks=[block],
            mode="act",
            created_at="2025-01-01T00:00:00+00:00",
        )
        d = snap.to_dict()
        assert d["snapshot_id"] == "snap-rs"
        assert len(d["blocks"]) == 1
        assert d["blocks"][0]["summary_id"] == "sb-rs"

        restored = CondensationSnapshot.from_dict(d)
        assert restored.snapshot_id == snap.snapshot_id
        assert restored.session_id == snap.session_id
        assert restored.source_event_count == snap.source_event_count
        assert restored.latest_event_id == snap.latest_event_id
        assert len(restored.blocks) == 1
        assert restored.blocks[0].goal == "test"
        assert restored.mode == "act"
        assert restored.created_at == "2025-01-01T00:00:00+00:00"

    def test_from_dict_missing_optional(self):
        d = {
            "snapshot_id": "snap-min",
            "session_id": "sess-min",
            "source_event_count": 0,
            "latest_event_id": "",
        }
        snap = CondensationSnapshot.from_dict(d)
        assert snap.snapshot_id == "snap-min"
        assert snap.blocks == []
        assert snap.mode == ""

    def test_covered_event_ids_aggregated(self):
        b1 = SummaryBlock(summary_id="sb-1", covered_event_ids=["e1", "e2"])
        b2 = SummaryBlock(summary_id="sb-2", covered_event_ids=["e3", "e4"])
        snap = CondensationSnapshot(
            snapshot_id="snap-agg",
            session_id="s1",
            source_event_count=4,
            latest_event_id="e4",
            blocks=[b1, b2],
        )
        assert snap.covered_event_ids == ["e1", "e2", "e3", "e4"]

    def test_covered_iterations_aggregated(self):
        b1 = SummaryBlock(summary_id="sb-1", covered_iterations=[0, 1])
        b2 = SummaryBlock(summary_id="sb-2", covered_iterations=[1, 2, 3])
        snap = CondensationSnapshot(
            snapshot_id="snap-iter",
            session_id="s1",
            source_event_count=6,
            latest_event_id="e6",
            blocks=[b1, b2],
        )
        assert snap.covered_iterations == [0, 1, 2, 3]

    def test_covered_properties_empty_snapshot(self):
        snap = CondensationSnapshot(
            snapshot_id="snap-empty",
            session_id="s1",
            source_event_count=0,
            latest_event_id="",
        )
        assert snap.covered_event_ids == []
        assert snap.covered_iterations == []
