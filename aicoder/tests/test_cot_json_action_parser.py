"""Tests for CotJsonActionParser — streaming JSON action extraction."""

import json

import pytest

from aicoder.parsers.cot_json_action_parser import CotJsonActionParser, _try_parse_json_action
from aicoder.parsers.base import ParserEvent
from aicoder.tools.registry import ToolRegistry
from aicoder.tools.spec import ParamSpec, ToolSpec


def _make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(ToolSpec(
        name="read_file",
        description="",
        parameters=[ParamSpec(name="path")],
    ))
    return reg


class TestTryParseJsonAction:
    def test_valid_action(self):
        text = json.dumps({"name": "read_file", "arguments": {"path": "/tmp/a.py"}})
        result = _try_parse_json_action(text)
        assert result is not None
        assert result.kind == "action"
        assert result.action_name == "read_file"
        assert result.action_input == {"path": "/tmp/a.py"}

    def test_valid_action_with_args_key(self):
        text = json.dumps({"name": "read_file", "args": {"path": "/tmp/a.py"}})
        result = _try_parse_json_action(text)
        assert result is not None
        assert result.action_name == "read_file"

    def test_no_name_returns_none(self):
        text = json.dumps({"arguments": {"path": "/tmp/a.py"}})
        assert _try_parse_json_action(text) is None

    def test_invalid_json_returns_none(self):
        assert _try_parse_json_action("{not json") is None

    def test_non_dict_returns_none(self):
        assert _try_parse_json_action("42") is None

    def test_string_arguments(self):
        text = json.dumps({"name": "read_file", "arguments": '{"path": "/tmp/a.py"}'})
        result = _try_parse_json_action(text)
        assert result is not None
        assert result.action_input == {"path": "/tmp/a.py"}


class TestCotJsonActionParserParse:
    def test_plain_text(self):
        reg = _make_registry()
        parser = CotJsonActionParser()
        events = parser.parse("Hello world", reg)

        assert len(events) >= 1
        assert events[-1].kind == "final"
        assert "Hello" in events[-1].text

    def test_single_json_action(self):
        reg = _make_registry()
        action = json.dumps({"name": "read_file", "arguments": {"path": "test.py"}})
        parser = CotJsonActionParser()
        events = parser.parse(action, reg)

        assert any(e.kind == "action" for e in events)
        action_events = [e for e in events if e.kind == "action"]
        assert action_events[0].action_name == "read_file"
        assert action_events[0].action_input == {"path": "test.py"}

    def test_text_then_action(self):
        reg = _make_registry()
        text_part = "I will read the file."
        action_part = json.dumps({"name": "read_file", "arguments": {"path": "test.py"}})
        content = text_part + "\n" + action_part

        parser = CotJsonActionParser()
        events = parser.parse(content, reg)

        has_text = any(e.kind == "text" for e in events)
        has_action = any(e.kind == "action" for e in events)
        assert has_text
        assert has_action

    def test_code_block_json(self):
        reg = _make_registry()
        action = json.dumps({"name": "read_file", "arguments": {"path": "test.py"}})
        content = f"```json\n{action}\n```"

        parser = CotJsonActionParser()
        events = parser.parse(content, reg)

        assert any(e.kind == "action" for e in events)

    def test_code_block_plain(self):
        reg = _make_registry()
        content = "```\nplain text\n```"

        parser = CotJsonActionParser()
        events = parser.parse(content, reg)

        # Not valid JSON action, should be text/final
        assert all(e.kind in ("text", "final") for e in events)

    def test_empty_input(self):
        reg = _make_registry()
        parser = CotJsonActionParser()
        events = parser.parse("", reg)
        assert events == []


class TestCotJsonActionParserStreaming:
    def test_feed_then_finalize(self):
        reg = _make_registry()
        parser = CotJsonActionParser()

        action = json.dumps({"name": "read_file", "arguments": {"path": "test.py"}})
        # Feed character by character — action may be emitted during feed
        # when the final closing brace is processed
        events = []
        for ch in action:
            events.extend(parser.feed(ch, reg))
        events.extend(parser.finalize())

        assert any(e.kind == "action" for e in events)

    def test_feed_text_then_json(self):
        reg = _make_registry()
        parser = CotJsonActionParser()

        events_batch = []
        text = "Let me check.\n"
        for ch in text:
            events_batch.extend(parser.feed(ch, reg))

        action = json.dumps({"name": "read_file", "arguments": {"path": "a.py"}})
        for ch in action:
            events_batch.extend(parser.feed(ch, reg))

        events_batch.extend(parser.finalize())

        has_text = any(e.kind == "text" for e in events_batch)
        has_action = any(e.kind == "action" for e in events_batch)
        assert has_text
        assert has_action

    def test_feed_code_block(self):
        reg = _make_registry()
        parser = CotJsonActionParser()

        action = json.dumps({"name": "read_file", "arguments": {"path": "x.py"}})
        content = f"```json\n{action}\n```"
        events = []
        for ch in content:
            events.extend(parser.feed(ch, reg))
        events.extend(parser.finalize())

        assert any(e.kind == "action" for e in events)

    def test_multiple_feeds_without_finalize_accumulate(self):
        reg = _make_registry()
        parser = CotJsonActionParser()

        # Feed partial JSON
        parser.feed('{"name":', reg)
        events1 = parser.finalize()

        # The partial JSON may be treated as text (brace not closed)
        assert len(events1) >= 1
