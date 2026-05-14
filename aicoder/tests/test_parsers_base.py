"""Tests for the parser base types."""

import pytest

from aicoder.parsers.base import BaseParser, ParserEvent


class TestParserEvent:
    def test_default_fields(self):
        e = ParserEvent(kind="text")
        assert e.kind == "text"
        assert e.text == ""
        assert e.action_name is None
        assert e.action_input is None
        assert e.raw == ""

    def test_action_event(self):
        e = ParserEvent(
            kind="action",
            action_name="read_file",
            action_input={"path": "/tmp/a.py"},
            raw="<read_file>...</read_file>",
        )
        assert e.kind == "action"
        assert e.action_name == "read_file"
        assert e.action_input == {"path": "/tmp/a.py"}

    def test_final_event(self):
        e = ParserEvent(kind="final", text="The answer is 42.")
        assert e.kind == "final"

    @pytest.mark.parametrize("kind", ["text", "thought", "action", "final", "error"])
    def test_all_kinds(self, kind):
        e = ParserEvent(kind=kind)
        assert e.kind == kind


class TestBaseParserAbstract:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseParser()
