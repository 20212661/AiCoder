"""Unit tests for tools/ — spec, registry, parser, result."""
import pytest

from aicoder.tools.spec import ToolSpec, ParamSpec
from aicoder.tools.registry import ToolRegistry
from aicoder.tools.parser import parse_xml_tools
from aicoder.tools.result import ToolCall, TextBlock, ToolResult, ExecutionState, build_unified_diff


# ---------------------------------------------------------------------------
# ToolSpec / ParamSpec
# ---------------------------------------------------------------------------

class TestParamSpec:
    def test_required_by_default(self):
        p = ParamSpec(name="path")
        assert p.required is True

    def test_prompt_line(self):
        p = ParamSpec(name="path", description="File path")
        line = p.prompt_line()
        assert "path" in line
        assert "(required)" in line

    def test_optional(self):
        p = ParamSpec(name="offset", required=False, description="Line offset")
        line = p.prompt_line()
        assert "(optional)" in line


class TestToolSpec:
    def test_basic(self):
        t = ToolSpec(name="read_file", description="Read a file")
        assert t.name == "read_file"

    def test_param_names(self):
        t = ToolSpec(
            name="read_file",
            description="Read a file",
            parameters=[
                ParamSpec(name="path"),
                ParamSpec(name="offset", required=False),
            ],
        )
        assert t.param_names == ["path", "offset"]

    def test_required_params(self):
        t = ToolSpec(
            name="read_file",
            description="Read a file",
            parameters=[
                ParamSpec(name="path"),
                ParamSpec(name="offset", required=False),
            ],
        )
        assert len(t.required_params()) == 1
        assert t.required_params()[0].name == "path"


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def _make_registry(self):
        reg = ToolRegistry()
        reg.register(ToolSpec(
            name="read_file",
            description="Read a file",
            parameters=[ParamSpec(name="path"), ParamSpec(name="offset", required=False)],
        ))
        reg.register(ToolSpec(
            name="write_file",
            description="Write a file",
            parameters=[ParamSpec(name="path"), ParamSpec(name="content")],
        ))
        return reg

    def test_register_and_get(self):
        reg = self._make_registry()
        assert reg.get("read_file") is not None
        assert reg.get("nonexistent") is None

    def test_get_all(self):
        reg = self._make_registry()
        all_tools = reg.get_all()
        assert len(all_tools) == 2

    def test_tool_names(self):
        reg = self._make_registry()
        assert "read_file" in reg.tool_names
        assert "write_file" in reg.tool_names

    def test_all_param_names(self):
        reg = self._make_registry()
        names = reg.all_param_names
        assert "path" in names
        assert "offset" in names
        assert "content" in names


# ---------------------------------------------------------------------------
# XML Parser
# ---------------------------------------------------------------------------

class TestParseXmlTools:
    def _make_registry(self):
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

    def test_plain_text(self):
        reg = self._make_registry()
        blocks = parse_xml_tools("Hello world", reg)
        assert len(blocks) == 1
        assert isinstance(blocks[0], TextBlock)
        assert blocks[0].content == "Hello world"

    def test_empty_content(self):
        reg = self._make_registry()
        blocks = parse_xml_tools("", reg)
        assert len(blocks) == 1
        assert blocks[0].content == ""

    def test_single_tool_call(self):
        reg = self._make_registry()
        content = '<read_file>\n<path>test.py</path>\n</read_file>'
        blocks = parse_xml_tools(content, reg)
        assert len(blocks) == 1
        assert isinstance(blocks[0], ToolCall)
        assert blocks[0].name == "read_file"
        assert blocks[0].params["path"] == "test.py"

    def test_tool_with_multiple_params(self):
        reg = self._make_registry()
        content = '<write_file>\n<path>test.py</path>\n<content>hello</content>\n</write_file>'
        blocks = parse_xml_tools(content, reg)
        assert len(blocks) == 1
        tc = blocks[0]
        assert isinstance(tc, ToolCall)
        assert tc.params["path"] == "test.py"
        assert tc.params["content"] == "hello"

    def test_text_and_tool_mixed(self):
        reg = self._make_registry()
        content = 'Some text\n<read_file>\n<path>test.py</path>\n</read_file>\nMore text'
        blocks = parse_xml_tools(content, reg)
        assert len(blocks) == 3
        assert isinstance(blocks[0], TextBlock)
        assert isinstance(blocks[1], ToolCall)
        assert isinstance(blocks[2], TextBlock)

    def test_unclosed_tool_becomes_text(self):
        reg = self._make_registry()
        content = '<read_file>\n<path>test.py</path>\n'
        blocks = parse_xml_tools(content, reg)
        # unclosed tool should become text
        assert all(isinstance(b, TextBlock) for b in blocks)

    def test_tool_with_optional_param_omitted(self):
        reg = self._make_registry()
        content = '<read_file>\n<path>test.py</path>\n</read_file>'
        blocks = parse_xml_tools(content, reg)
        tc = blocks[0]
        assert isinstance(tc, ToolCall)
        assert "offset" not in tc.params


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------

class TestToolResult:
    def test_ok(self):
        r = ToolResult.ok("read_file", "file contents")
        assert r.success is True
        assert r.tool_name == "read_file"
        assert r.output == "file contents"

    def test_fail(self):
        r = ToolResult.fail("read_file", "file not found")
        assert r.success is False
        assert r.error == "file not found"

    def test_rejected(self):
        r = ToolResult.create_rejected("run_shell")
        assert r.rejected is True
        assert r.success is False

    def test_blocked(self):
        r = ToolResult.blocked("run_shell", "dangerous command")
        assert r.success is False
        assert r.error == "dangerous command"

    def test_to_message_success(self):
        r = ToolResult.ok("read_file", "contents")
        msg = r.to_message()
        assert msg["role"] == "user"
        assert "read_file" in msg["content"]
        assert "contents" in msg["content"]

    def test_to_message_failure(self):
        r = ToolResult.fail("read_file", "not found")
        msg = r.to_message()
        assert "FAILED" in msg["content"]

    def test_to_message_rejected(self):
        r = ToolResult.create_rejected("run_shell")
        msg = r.to_message()
        assert "REJECTED" in msg["content"]

    def test_to_message_ok_empty_output(self):
        r = ToolResult.ok("read_file", "")
        msg = r.to_message()
        assert "OK (no output)" in msg["content"]


class TestBuildUnifiedDiff:
    def test_basic_diff(self):
        old = "line1\nline2\nline3\n"
        new = "line1\nmodified\nline3\n"
        diff = build_unified_diff(old, new, "test.py")
        assert "-line2" in diff
        assert "+modified" in diff

    def test_no_changes(self):
        content = "same\n"
        diff = build_unified_diff(content, content, "test.py")
        assert diff == ""

    def test_new_file(self):
        diff = build_unified_diff("", "new content\n", "new.py")
        assert "+new content" in diff


# ---------------------------------------------------------------------------
# ExecutionState
# ---------------------------------------------------------------------------

class TestExecutionState:
    def test_defaults(self):
        s = ExecutionState()
        assert s.consecutive_mistake_count == 0
        assert s.mode == "act"

    def test_on_success_resets_errors(self):
        s = ExecutionState(consecutive_mistake_count=3)
        s.on_success("read_file", {"path": "x"})
        assert s.consecutive_mistake_count == 0

    def test_on_failure_increments(self):
        s = ExecutionState()
        s.on_failure("read_file", {"path": "x"})
        assert s.consecutive_mistake_count == 1

    def test_loop_detection(self):
        s = ExecutionState(max_repeated_calls=3)
        # Need to call 4 times: first call sets last_tool_name, then 3 repeated calls
        for _ in range(4):
            s.on_success("read_file", {"path": "x"})
        assert s.is_looping is True

    def test_too_many_errors(self):
        s = ExecutionState(max_consecutive_mistakes=5)
        for _ in range(5):
            s.on_failure("tool", {})
        assert s.too_many_errors is True

    def test_should_require_approval(self):
        s = ExecutionState()
        for _ in range(3):
            s.on_failure("tool", {})
        assert s.should_require_approval is True

    def test_plan_mode(self):
        s = ExecutionState(mode="plan")
        assert s.is_plan_mode is True

    def test_act_mode(self):
        s = ExecutionState(mode="act")
        assert s.is_plan_mode is False

    def test_reset(self):
        s = ExecutionState(consecutive_mistake_count=5)
        s.last_tool_name = "test"
        s.reset()
        assert s.consecutive_mistake_count == 0
        assert s.last_tool_name == ""

    def test_different_tool_resets_loop_counter(self):
        s = ExecutionState()
        s.on_success("tool_a", {})
        s.on_success("tool_b", {})
        assert s.repeated_call_count == 0

    def test_tool_call_get(self):
        tc = ToolCall(name="test", params={"path": "x.py"})
        assert tc.get("path") == "x.py"
        assert tc.get("missing", "default") == "default"
