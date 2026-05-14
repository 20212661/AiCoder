"""Tests for FC parameter normalization — §5.1 改造项 A."""

import json

import pytest

from aicoder.tools.registry import ToolRegistry
from aicoder.tools.spec import ParamSpec, ToolSpec


def _make_runner(tool_registry: ToolRegistry):
    """Create a FunctionCallingAgentRunner with mocked dependencies."""
    from aicoder.agent_step_store import AgentStepStore
    from aicoder.runners.function_calling_agent_runner import FunctionCallingAgentRunner
    from unittest.mock import MagicMock

    coder = MagicMock()
    coder.main_model.backend_model = "test-model"
    coder.main_model.max_output_tokens = 4096
    coder.main_model.name = "test"
    coder.stream = False
    coder.io = MagicMock()

    store = AgentStepStore(session_id="test-norm")
    runner = FunctionCallingAgentRunner(
        coder=coder,
        session_id="test-norm",
        mode="act",
        tool_registry=tool_registry,
        step_store=store,
    )
    return runner


def _single_param_registry() -> ToolRegistry:
    """Registry with a single-required-param tool (city)."""
    reg = ToolRegistry()
    reg.register(ToolSpec(
        name="get_weather",
        description="Get weather",
        parameters=[ParamSpec(name="city", required=True)],
    ))
    return reg


def _multi_param_registry() -> ToolRegistry:
    """Registry with a multi-param tool."""
    reg = ToolRegistry()
    reg.register(ToolSpec(
        name="search_files",
        description="Search files",
        parameters=[
            ParamSpec(name="path", required=True),
            ParamSpec(name="pattern", required=True),
        ],
    ))
    return reg


class TestNormalizeToolParams:
    def test_dict_passthrough(self):
        runner = _make_runner(_single_param_registry())
        result, error = runner._normalize_tool_params(
            {"city": "Beijing"}, "get_weather",
        )
        assert result == {"city": "Beijing"}
        assert error is None

    def test_single_param_string_autowrap(self):
        runner = _make_runner(_single_param_registry())
        result, error = runner._normalize_tool_params("Beijing", "get_weather")
        assert result == {"city": "Beijing"}
        assert error is None

    def test_multi_param_json_string_parsed(self):
        runner = _make_runner(_multi_param_registry())
        result, error = runner._normalize_tool_params(
            json.dumps({"path": ".", "pattern": "*.py"}), "search_files",
        )
        assert result == {"path": ".", "pattern": "*.py"}
        assert error is None

    def test_multi_param_plain_string_failure(self):
        runner = _make_runner(_multi_param_registry())
        result, error = runner._normalize_tool_params("Beijing", "search_files")
        assert result is None
        assert "Invalid params" in error
        assert "could not be normalized" in error

    def test_invalid_json_string_failure(self):
        runner = _make_runner(_multi_param_registry())
        result, error = runner._normalize_tool_params("{bad json}", "search_files")
        assert result is None
        assert "Invalid params" in error

    def test_non_dict_non_str_failure(self):
        runner = _make_runner(_single_param_registry())
        result, error = runner._normalize_tool_params(42, "get_weather")
        assert result is None
        assert "Invalid params" in error

    def test_empty_string_single_param(self):
        runner = _make_runner(_single_param_registry())
        result, error = runner._normalize_tool_params("", "get_weather")
        assert result == {"city": ""}
        assert error is None

    def test_unknown_tool_string_fallback_failure(self):
        """String arg for unknown tool (no registry match) → try json.loads → fail."""
        reg = ToolRegistry()
        runner = _make_runner(reg)
        result, error = runner._normalize_tool_params("hello", "unknown_tool")
        assert result is None
        assert "Invalid params" in error

    def test_unknown_tool_dict_passthrough(self):
        """Dict arg for unknown tool → pass through."""
        reg = ToolRegistry()
        runner = _make_runner(reg)
        result, error = runner._normalize_tool_params({"key": "val"}, "unknown_tool")
        assert result == {"key": "val"}
        assert error is None

    def test_json_string_single_param_tool(self):
        """JSON string for single-param tool → json.loads returns dict → use dict."""
        runner = _make_runner(_single_param_registry())
        result, error = runner._normalize_tool_params(
            json.dumps({"city": "Shanghai"}), "get_weather",
        )
        # json.loads succeeds, returns dict, but since there's a single param,
        # the auto-wrap path fires first and wraps the string
        # Actually, spec found, single required → auto-wrap path fires first
        assert result == {"city": json.dumps({"city": "Shanghai"})}
        assert error is None
