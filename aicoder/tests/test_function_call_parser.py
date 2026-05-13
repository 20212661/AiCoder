"""Tests for FunctionCallParser — native tool_calls extraction."""

import json

import pytest

from aicoder.parsers.function_call_parser import FunctionCallParser
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


class TestFunctionCallParserParse:
    def test_text_only(self):
        reg = _make_registry()
        parser = FunctionCallParser()
        events = parser.parse("Here is the answer.", reg)

        assert len(events) == 1
        assert events[0].kind == "final"

    def test_empty_content(self):
        reg = _make_registry()
        parser = FunctionCallParser()
        events = parser.parse("", reg)
        assert events == []

    def test_feed_returns_empty(self):
        reg = _make_registry()
        parser = FunctionCallParser()
        assert parser.feed("chunk", reg) == []

    def test_finalize_returns_empty(self):
        parser = FunctionCallParser()
        assert parser.finalize() == []


class TestParseToolCalls:
    def test_single_tool_call(self):
        parser = FunctionCallParser()
        tool_calls = [
            {
                "function": {
                    "name": "read_file",
                    "arguments": json.dumps({"path": "/tmp/a.py"}),
                }
            }
        ]
        events = parser.parse_tool_calls(tool_calls)

        assert len(events) == 1
        assert events[0].kind == "action"
        assert events[0].action_name == "read_file"
        assert events[0].action_input == {"path": "/tmp/a.py"}

    def test_multiple_tool_calls(self):
        parser = FunctionCallParser()
        tool_calls = [
            {
                "function": {
                    "name": "read_file",
                    "arguments": json.dumps({"path": "a.py"}),
                }
            },
            {
                "function": {
                    "name": "read_file",
                    "arguments": json.dumps({"path": "b.py"}),
                }
            },
        ]
        events = parser.parse_tool_calls(tool_calls)
        assert len(events) == 2
        assert all(e.kind == "action" for e in events)

    def test_empty_tool_calls(self):
        parser = FunctionCallParser()
        assert parser.parse_tool_calls([]) == []
        assert parser.parse_tool_calls(None) == []

    def test_missing_name_skipped(self):
        parser = FunctionCallParser()
        tool_calls = [{"function": {"arguments": "{}"}}]
        events = parser.parse_tool_calls(tool_calls)
        assert events == []

    def test_dict_arguments(self):
        parser = FunctionCallParser()
        tool_calls = [
            {
                "function": {
                    "name": "read_file",
                    "arguments": {"path": "test.py"},
                }
            }
        ]
        events = parser.parse_tool_calls(tool_calls)
        assert len(events) == 1
        assert events[0].action_input == {"path": "test.py"}

    def test_invalid_json_arguments(self):
        parser = FunctionCallParser()
        tool_calls = [
            {
                "function": {
                    "name": "read_file",
                    "arguments": "{invalid",
                }
            }
        ]
        events = parser.parse_tool_calls(tool_calls)
        assert len(events) == 1
        # Arguments should be passed through as string
        assert events[0].action_input == "{invalid"

    def test_raw_preserved(self):
        parser = FunctionCallParser()
        args_json = json.dumps({"path": "test.py"})
        tool_calls = [
            {"function": {"name": "read_file", "arguments": args_json}}
        ]
        events = parser.parse_tool_calls(tool_calls)
        assert events[0].raw == args_json


class TestParseResponse:
    def test_tool_calls_only(self):
        parser = FunctionCallParser()
        tool_calls = [
            {"function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}
        ]
        events = parser.parse_response(None, tool_calls)
        assert len(events) == 1
        assert events[0].kind == "action"

    def test_text_only(self):
        parser = FunctionCallParser()
        events = parser.parse_response("The answer is 42.", None)
        assert len(events) == 1
        assert events[0].kind == "final"

    def test_text_and_tool_calls(self):
        parser = FunctionCallParser()
        tool_calls = [
            {"function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}
        ]
        events = parser.parse_response("I'll read the file.", tool_calls)

        kinds = [e.kind for e in events]
        assert "action" in kinds
        assert "text" in kinds

    def test_empty_both(self):
        parser = FunctionCallParser()
        events = parser.parse_response(None, None)
        assert events == []

    def test_empty_text_and_no_tool_calls(self):
        parser = FunctionCallParser()
        events = parser.parse_response("", None)
        assert events == []
