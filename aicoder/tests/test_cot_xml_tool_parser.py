"""Tests for CotXmlToolParser — verify equivalence with existing XML parser."""

import pytest

from aicoder.parsers.cot_xml_tool_parser import CotXmlToolParser
from aicoder.tools.registry import ToolRegistry
from aicoder.tools.spec import ParamSpec, ToolSpec


def _make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(ToolSpec(
        name="read_file",
        description="",
        parameters=[ParamSpec(name="path"), ParamSpec(name="offset", required=False)],
    ))
    reg.register(ToolSpec(
        name="write_file",
        description="",
        parameters=[ParamSpec(name="path"), ParamSpec(name="content")],
    ))
    return reg


class TestCotXmlToolParserParse:
    def test_plain_text(self):
        reg = _make_registry()
        parser = CotXmlToolParser()
        events = parser.parse("Hello world", reg)

        assert len(events) == 1
        assert events[0].kind == "final"
        assert events[0].text == "Hello world"

    def test_empty_content(self):
        reg = _make_registry()
        parser = CotXmlToolParser()
        events = parser.parse("", reg)
        assert len(events) == 0

    def test_single_tool_call(self):
        reg = _make_registry()
        content = "<read_file>\n<path>test.py</path>\n</read_file>"
        parser = CotXmlToolParser()
        events = parser.parse(content, reg)

        assert len(events) == 1
        assert events[0].kind == "action"
        assert events[0].action_name == "read_file"
        assert events[0].action_input == {"path": "test.py"}

    def test_tool_with_multiple_params(self):
        reg = _make_registry()
        content = "<write_file>\n<path>test.py</path>\n<content>hello</content>\n</write_file>"
        parser = CotXmlToolParser()
        events = parser.parse(content, reg)

        assert len(events) == 1
        assert events[0].kind == "action"
        assert events[0].action_input == {"path": "test.py", "content": "hello"}

    def test_text_and_tool_mixed(self):
        reg = _make_registry()
        content = "Some text\n<read_file>\n<path>test.py</path>\n</read_file>\nMore text"
        parser = CotXmlToolParser()
        events = parser.parse(content, reg)

        # "Some text" -> text, tool call -> action, "More text" -> text
        assert len(events) == 3
        assert events[0].kind == "text"
        assert events[1].kind == "action"
        assert events[1].action_name == "read_file"
        assert events[2].kind == "text"

    def test_unclosed_tool_becomes_text(self):
        reg = _make_registry()
        content = "<read_file>\n<path>test.py</path>\n"
        parser = CotXmlToolParser()
        events = parser.parse(content, reg)

        # Unclosed tool — all text (stripped, so may be fewer events)
        for e in events:
            assert e.kind in ("text", "final")
        assert not any(e.kind == "action" for e in events)

    def test_tool_with_optional_param_omitted(self):
        reg = _make_registry()
        content = "<read_file>\n<path>test.py</path>\n</read_file>"
        parser = CotXmlToolParser()
        events = parser.parse(content, reg)

        assert events[0].kind == "action"
        assert "offset" not in events[0].action_input

    def test_no_tools_produces_final(self):
        reg = _make_registry()
        parser = CotXmlToolParser()
        events = parser.parse("Just a plain response from the model.", reg)

        assert len(events) == 1
        assert events[0].kind == "final"

    def test_action_has_raw(self):
        reg = _make_registry()
        content = "<read_file>\n<path>test.py</path>\n</read_file>"
        parser = CotXmlToolParser()
        events = parser.parse(content, reg)

        assert events[0].raw.startswith("<read_file>")
        assert events[0].raw.endswith("</read_file>")


class TestCotXmlToolParserStreaming:
    def test_feed_buffers_then_finalize_parses(self):
        reg = _make_registry()
        parser = CotXmlToolParser()

        # Feed chunks
        assert parser.feed("Some text\n", reg) == []
        assert parser.feed("<read_file>\n", reg) == []
        assert parser.feed("<path>test.py</path>\n", reg) == []
        assert parser.feed("</read_file>", reg) == []

        events = parser.finalize_with_registry(reg)
        # Should get text + action
        assert len(events) >= 1
        assert any(e.kind == "action" for e in events)

    def test_finalize_empty(self):
        reg = _make_registry()
        parser = CotXmlToolParser()
        # finalize without registry returns raw text
        events = parser.finalize()
        assert events == []

    def test_feed_multiple_then_parse(self):
        reg = _make_registry()
        parser = CotXmlToolParser()

        # Feed some text
        parser.feed("Hello ", reg)
        parser.feed("world", reg)

        # Should not emit during feed (XML can't parse incrementally)
        events = parser.finalize_with_registry(reg)
        assert len(events) == 1
        assert events[0].kind == "final"
        assert "Hello" in events[0].text
