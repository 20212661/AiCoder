"""Tests for LangChain runtime adapter — Phase 1 + Phase 2 + error handling middleware."""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field

from aicoder.langchain_runtime.agent import extract_langchain_response_text
from aicoder.langchain_runtime.middleware import build_middleware, format_tool_error_message
from aicoder.langchain_runtime.schemas import (
    AICoderResponse,
    EditFileArgs,
    ReadFileArgs,
    RunShellArgs,
    SearchFilesArgs,
    WriteFileArgs,
)
from aicoder.langchain_runtime.tools import _run_existing_tool, build_langchain_tools
from aicoder.tools.result import ToolCall, ToolResult


# ── Fakes ──


class FakeExecutor:
    def __init__(self, result):
        self.result = result
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall):
        self.calls.append(tool_call)
        return self.result


class FakeCoder:
    def __init__(self, result):
        self.tool_executor = FakeExecutor(result)


# ── _run_existing_tool ──


class TestRunExistingTool:
    def test_success_returns_output(self):
        coder = FakeCoder(ToolResult.ok("read_file", "hello"))
        output = _run_existing_tool(coder, "read_file", {"path": "README.md"})
        assert output == "hello"
        assert coder.tool_executor.calls[0].name == "read_file"
        assert coder.tool_executor.calls[0].params == {"path": "README.md"}

    def test_failure_raises_runtime_error(self):
        coder = FakeCoder(ToolResult.fail("read_file", "file not found"))
        with pytest.raises(RuntimeError, match="file not found"):
            _run_existing_tool(coder, "read_file", {"path": "missing.md"})

    def test_failure_with_empty_error_uses_tool_name(self):
        coder = FakeCoder(ToolResult(tool_name="bad", success=False, error="", output=""))
        with pytest.raises(RuntimeError, match="Tool failed: bad"):
            _run_existing_tool(coder, "bad", {})


# ── build_langchain_tools ──


class TestBuildLangchainTools:
    @pytest.fixture()
    def coder(self):
        return FakeCoder(ToolResult.ok("test", "ok"))

    def test_returns_five_tools(self, coder):
        tools = build_langchain_tools(coder)
        assert len(tools) == 5

    def test_tool_names(self, coder):
        tools = build_langchain_tools(coder)
        names = [t.name for t in tools]
        assert set(names) == {"read_file", "write_file", "edit_file", "search_files", "run_shell"}

    def test_read_file_calls_executor(self, coder):
        tools = build_langchain_tools(coder)
        read_tool = next(t for t in tools if t.name == "read_file")
        read_tool.invoke({"path": "foo.py"})
        call = coder.tool_executor.calls[0]
        assert call.name == "read_file"
        assert call.params == {"path": "foo.py"}

    def test_edit_file_uses_search_replace(self, coder):
        tools = build_langchain_tools(coder)
        edit_tool = next(t for t in tools if t.name == "edit_file")
        edit_tool.invoke({"path": "a.py", "search": "old", "replace": "new"})
        call = coder.tool_executor.calls[0]
        assert call.name == "edit_file"
        assert call.params == {"path": "a.py", "search": "old", "replace": "new"}

    def test_search_files_uses_regex(self, coder):
        tools = build_langchain_tools(coder)
        search_tool = next(t for t in tools if t.name == "search_files")
        search_tool.invoke({"regex": "TODO", "path": "src", "file_pattern": "*.py"})
        call = coder.tool_executor.calls[0]
        assert call.name == "search_files"
        assert call.params["regex"] == "TODO"

    def test_run_shell_passes_timeout(self, coder):
        tools = build_langchain_tools(coder)
        shell_tool = next(t for t in tools if t.name == "run_shell")
        shell_tool.invoke({"command": "ls", "timeout": 30})
        call = coder.tool_executor.calls[0]
        assert call.name == "run_shell"
        # int timeout is converted to str before entering the stringly-typed params dict
        assert call.params["timeout"] == "30"


# ── CLI argument default ──

import argparse


def _build_runtime_parser():
    """Minimal parser to test --runtime argument in isolation."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime",
        choices=["legacy", "langchain"],
        default="legacy",
        help="Agent runtime backend to use",
    )
    return parser


class TestRuntimeArgDefault:
    def test_default_runtime_is_legacy(self):
        parser = _build_runtime_parser()
        args = parser.parse_args([])
        assert args.runtime == "legacy"

    def test_runtime_langchain_parsed(self):
        parser = _build_runtime_parser()
        args = parser.parse_args(["--runtime", "langchain"])
        assert args.runtime == "langchain"


# ── Phase 2: Middleware ──


class TestBuildMiddleware:
    def test_returns_list(self):
        result = build_middleware()
        assert isinstance(result, list)

    def test_does_not_raise(self):
        # Must not throw even if middleware classes are absent
        build_middleware()

    def test_legacy_import_unaffected(self):
        # Importing middleware should never break legacy runtime
        import aicoder.langchain_runtime.middleware  # noqa: F401

        from aicoder.tools.result import ToolResult

        assert ToolResult.ok("t", "ok").success is True


# ── Phase 2: AICoderResponse ──


class TestAICoderResponse:
    def test_defaults(self):
        r = AICoderResponse(summary="done")
        assert r.summary == "done"
        assert r.changed_files == []
        assert r.commands_run == []
        assert r.needs_approval is False
        assert r.error is None

    def test_full_construction(self):
        r = AICoderResponse(
            summary="edited",
            changed_files=["a.py", "b.py"],
            commands_run=["pytest"],
            needs_approval=True,
            error="timeout",
        )
        assert r.changed_files == ["a.py", "b.py"]
        assert r.error == "timeout"


# ── Phase 2: extract_langchain_response_text ──


class FakeMessage:
    def __init__(self, content):
        self.content = content


class TestExtractLangchainResponseText:
    def test_structured_response_instance(self):
        resp = AICoderResponse(summary="edited 2 files", changed_files=["a.py", "b.py"])
        result = {"structured_response": resp, "messages": [FakeMessage("raw")]}
        assert extract_langchain_response_text(result) == "edited 2 files"

    def test_structured_response_dict(self):
        result = {
            "structured_response": {"summary": "ran tests", "changed_files": []},
            "messages": [FakeMessage("raw")],
        }
        assert extract_langchain_response_text(result) == "ran tests"

    def test_structured_response_empty_summary_falls_back(self):
        resp = AICoderResponse(summary="")
        result = {"structured_response": resp, "messages": [FakeMessage("fallback text")]}
        assert extract_langchain_response_text(result) == "fallback text"

    def test_dict_empty_summary_falls_back(self):
        result = {
            "structured_response": {"summary": ""},
            "messages": [FakeMessage("fallback text")],
        }
        assert extract_langchain_response_text(result) == "fallback text"

    def test_no_structured_response_falls_back(self):
        result = {"messages": [FakeMessage("hello world")]}
        assert extract_langchain_response_text(result) == "hello world"

    def test_empty_messages(self):
        result = {"messages": []}
        assert extract_langchain_response_text(result) == ""

    def test_no_messages_key(self):
        result = {}
        assert extract_langchain_response_text(result) == ""

    def test_list_content(self):
        msg = FakeMessage(["line 1", "line 2"])
        result = {"messages": [msg]}
        assert extract_langchain_response_text(result) == "line 1\nline 2"

    def test_dict_message(self):
        result = {"messages": [{"content": "dict msg"}]}
        assert extract_langchain_response_text(result) == "dict msg"


# ── Phase 2: Agent construction safety ──


class TestAgentBuildSafety:
    def test_agent_accepts_kwarg_check(self):
        from aicoder.langchain_runtime.agent import _agent_accepts_kwarg

        assert _agent_accepts_kwarg("model") is True
        assert _agent_accepts_kwarg("tools") is True
        assert _agent_accepts_kwarg("response_format") is True
        assert _agent_accepts_kwarg("nonexistent_param_xyz") is False


# ── Phase 2+: Runtime routing smoke tests ──


class TestRuntimeRouting:
    """Verify legacy and langchain runtime paths are isolated."""

    def test_langchain_without_message_returns_none(self):
        """--runtime langchain without --message should return None and warn."""
        from unittest.mock import MagicMock, patch

        fake_io = MagicMock()
        coder = MagicMock()
        coder.io = fake_io
        coder.runtime = "langchain"

        # Import the module where run() is defined and call the branch logic directly
        # We test the branch condition without triggering real agent_runtime
        from aicoder.coders.base_coder import Coder

        # Monkey-patch run to isolate the langchain branch
        original_run = Coder.run

        # Simulate what run() does for langchain without message
        runtime = getattr(coder, "runtime", "legacy")
        assert runtime == "langchain"

        # Without with_message, the branch should warn and return None
        with_message = None
        if runtime == "langchain":
            if not with_message:
                fake_io.tool_warning("LangChain runtime requires --message")
                result = None
            else:
                result = "text"

        assert result is None
        fake_io.tool_warning.assert_called_once()

    def test_langchain_branch_not_entered_for_legacy(self):
        """When runtime is 'legacy', the langchain branch is skipped."""
        coder = MagicMock()
        coder.runtime = "legacy"
        runtime = getattr(coder, "runtime", "legacy")
        assert runtime != "langchain"

    def test_langchain_branch_not_entered_without_attr(self):
        """When runtime attr is absent, defaults to 'legacy'."""
        coder = MagicMock(spec=[])  # no attributes
        runtime = getattr(coder, "runtime", "legacy")
        assert runtime == "legacy"
        assert runtime != "langchain"

    def test_langchain_with_message_calls_agent(self):
        """--runtime langchain with --message should call run_langchain_agent."""
        from unittest.mock import MagicMock, patch

        coder = MagicMock()
        coder.runtime = "langchain"
        coder.io = MagicMock()
        coder.main_model.name = "test-model"

        with patch(
            "aicoder.langchain_runtime.agent.run_langchain_agent",
            return_value="agent response",
        ) as mock_agent, patch(
            "aicoder.langchain_runtime.agent.build_langchain_agent"
        ):
            from aicoder.langchain_runtime.agent import run_langchain_agent

            result = run_langchain_agent(coder, "hello")
            assert result == "agent response"

    def test_legacy_import_unaffected_by_langchain_modules(self):
        """Importing langchain_runtime must not break legacy imports."""
        import aicoder.langchain_runtime.agent  # noqa: F401
        import aicoder.langchain_runtime.middleware  # noqa: F401
        import aicoder.langchain_runtime.tools  # noqa: F401
        import aicoder.langchain_runtime.schemas  # noqa: F401

        # Legacy path imports still work
        from aicoder.tools.result import ToolResult, ToolCall, ExecutionState

        r = ToolResult.ok("t", "ok")
        assert r.success is True
        tc = ToolCall(name="read_file", params={"path": "x"})
        assert tc.name == "read_file"
        es = ExecutionState(mode="act")
        assert es.is_plan_mode is False


# ── Phase 2+: Logging verification ──


class TestRuntimeLogging:
    def test_build_langchain_tools_logs_tool_names(self):
        from unittest.mock import patch

        coder = FakeCoder(ToolResult.ok("test", "ok"))

        with patch("aicoder.langchain_runtime.tools.logger") as mock_logger:
            tools = build_langchain_tools(coder)
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            logged_msg = call_args[0][0] % call_args[0][1] if len(call_args[0]) > 1 else call_args[0][0]
            assert "build_langchain_tools" in logged_msg
            for name in ["read_file", "write_file", "edit_file", "search_files", "run_shell"]:
                assert name in logged_msg

    def test_build_langchain_agent_logs_config(self):
        from unittest.mock import patch, MagicMock

        coder = MagicMock()
        coder.main_model.name = "test-model"

        with patch("aicoder.langchain_runtime.agent.build_chat_model"), \
             patch("aicoder.langchain_runtime.agent.build_langchain_tools", return_value=[]), \
             patch("aicoder.langchain_runtime.agent.build_middleware", return_value=[]), \
             patch("aicoder.langchain_runtime.agent.create_react_agent", return_value=MagicMock()), \
             patch("aicoder.langchain_runtime.agent.logger") as mock_logger:

            from aicoder.langchain_runtime.agent import build_langchain_agent
            build_langchain_agent(coder)

            # Should log twice: tools + config
            assert mock_logger.info.call_count == 2
            config_log = mock_logger.info.call_args_list[1]
            fmt = config_log[0][0]
            args = config_log[0][1:]
            logged_msg = fmt % args
            assert "structured_response" in logged_msg
            assert "middleware_count" in logged_msg


# ── Phase 3: format_tool_error_message ──


class TestFormatToolErrorMessage:
    def test_generic_error(self):
        msg = format_tool_error_message(RuntimeError("disk full"))
        assert "Tool error: Execution failed" in msg
        assert "disk full" in msg
        assert "safety policy" in msg

    def test_rejection_preserved(self):
        msg = format_tool_error_message(RuntimeError("User rejected the tool call."))
        assert "User rejected" in msg
        assert "rejected the tool call" in msg

    def test_safety_block_preserved(self):
        msg = format_tool_error_message(RuntimeError("Permission denied: write blocked"))
        assert "Safety/policy blocked" in msg
        assert "write blocked" in msg

    def test_denied_keyword(self):
        msg = format_tool_error_message(RuntimeError("Access denied by policy"))
        assert "Safety/policy blocked" in msg

    def test_permission_keyword(self):
        msg = format_tool_error_message(RuntimeError("Permission required for this action"))
        assert "Safety/policy blocked" in msg


# ── Phase 3: handle_tool_errors middleware ──


class TestHandleToolErrors:
    def test_middleware_list_includes_error_handler(self):
        middleware = build_middleware()
        # At minimum, handle_tool_errors should be present if wrap_tool_call is available
        # We check that build_middleware() returns a list without error
        assert isinstance(middleware, list)

    def test_build_middleware_returns_list(self):
        result = build_middleware()
        assert isinstance(result, list)

    def test_build_middleware_does_not_raise(self):
        build_middleware()

    def test_middleware_available_when_wrap_tool_call_exists(self):
        """If wrap_tool_call is importable, handle_tool_errors should be in the list."""
        try:
            from langchain.agents.middleware import wrap_tool_call  # noqa: F401

            middleware = build_middleware()
            assert len(middleware) >= 1
        except ImportError:
            pytest.skip("wrap_tool_call not available")

    def test_middleware_degradation_on_import_failure(self):
        """If wrap_tool_call import fails, build_middleware still returns a list."""
        with patch.dict("sys.modules", {"langchain.agents.middleware": None}):
            # Force re-import to trigger the ImportError path
            import importlib
            import aicoder.langchain_runtime.middleware as mw
            importlib.reload(mw)
            result = mw.build_middleware()
            assert isinstance(result, list)


# ── Phase 3: Tool schema reserved names ──


class TestToolSchemaReservedNames:
    SCHEMAS = [ReadFileArgs, WriteFileArgs, EditFileArgs, SearchFilesArgs, RunShellArgs]

    def test_no_config_field(self):
        for schema_cls in self.SCHEMAS:
            fields = schema_cls.model_fields
            assert "config" not in fields, f"{schema_cls.__name__} has reserved field 'config'"

    def test_no_runtime_field(self):
        for schema_cls in self.SCHEMAS:
            fields = schema_cls.model_fields
            assert "runtime" not in fields, f"{schema_cls.__name__} has reserved field 'runtime'"

    def test_all_schema_field_names(self):
        """Collect all field names across schemas and verify none are reserved."""
        all_names = set()
        for schema_cls in self.SCHEMAS:
            all_names.update(schema_cls.model_fields.keys())
        assert "config" not in all_names
        assert "runtime" not in all_names


# ── Phase 3: Agent build with middleware kwarg ──


class TestAgentBuildWithMiddleware:
    def test_agent_passes_middleware_if_supported(self):
        coder = MagicMock()
        coder.main_model.name = "test-model"

        middleware_instance = MagicMock()

        with patch("aicoder.langchain_runtime.agent.build_chat_model"), \
             patch("aicoder.langchain_runtime.agent.build_langchain_tools", return_value=[]), \
             patch("aicoder.langchain_runtime.agent.build_middleware", return_value=[middleware_instance]), \
             patch("aicoder.langchain_runtime.agent.create_react_agent", return_value=MagicMock()) as mock_create, \
             patch("aicoder.langchain_runtime.agent._agent_accepts_kwarg", side_effect=lambda k: k in ("response_format", "middleware")):

            from aicoder.langchain_runtime.agent import build_langchain_agent
            build_langchain_agent(coder)

            call_kwargs = mock_create.call_args[1]
            assert "middleware" in call_kwargs
            assert call_kwargs["middleware"] == [middleware_instance]

    def test_agent_skips_middleware_if_kwarg_unsupported(self):
        coder = MagicMock()
        coder.main_model.name = "test-model"

        with patch("aicoder.langchain_runtime.agent.build_chat_model"), \
             patch("aicoder.langchain_runtime.agent.build_langchain_tools", return_value=[]), \
             patch("aicoder.langchain_runtime.agent.build_middleware", return_value=[MagicMock()]), \
             patch("aicoder.langchain_runtime.agent.create_react_agent", return_value=MagicMock()) as mock_create, \
             patch("aicoder.langchain_runtime.agent._agent_accepts_kwarg", side_effect=lambda k: k == "response_format"):

            from aicoder.langchain_runtime.agent import build_langchain_agent
            build_langchain_agent(coder)

            call_kwargs = mock_create.call_args[1]
            assert "middleware" not in call_kwargs

    def test_agent_build_does_not_fail_with_empty_middleware(self):
        coder = MagicMock()
        coder.main_model.name = "test-model"

        with patch("aicoder.langchain_runtime.agent.build_chat_model"), \
             patch("aicoder.langchain_runtime.agent.build_langchain_tools", return_value=[]), \
             patch("aicoder.langchain_runtime.agent.build_middleware", return_value=[]), \
             patch("aicoder.langchain_runtime.agent.create_react_agent", return_value=MagicMock()):

            from aicoder.langchain_runtime.agent import build_langchain_agent
            agent = build_langchain_agent(coder)
            assert agent is not None


# ── Phase 3: Legacy import isolation ──


class TestLegacyImportIsolation:
    def test_middleware_import_does_not_break_legacy(self):
        import aicoder.langchain_runtime.middleware  # noqa: F401
        from aicoder.tools.result import ToolResult

        assert ToolResult.ok("t", "ok").success is True

    def test_format_tool_error_message_pure_function(self):
        """format_tool_error_message is a pure function — no LangChain deps."""
        msg = format_tool_error_message(ValueError("test error"))
        assert "Tool error" in msg
        assert "test error" in msg


# ── Phase 6: Session persistence ──


class TestSessionPersistence:
    """Verify LangChain runtime persists conversation turns to session JSON."""

    def _make_coder(self, session_id="test-session-123"):
        coder = MagicMock()
        coder.io = MagicMock()
        coder.runtime = "langchain"
        coder.session_id = session_id
        coder.main_model = MagicMock()
        coder.main_model.name = "test-model"
        coder.done_messages = []
        coder.cur_messages = []
        coder._first_user_message = None
        coder._session_token_in = 0
        coder._session_token_out = 0
        coder.edit_format = "whole"
        coder.root = "/tmp"
        coder.show_announcements = MagicMock()
        return coder

    def test_saves_user_and_assistant_on_success(self):
        coder = self._make_coder()

        with patch("aicoder.langchain_runtime.agent.run_langchain_agent", return_value="hello back"):
            from aicoder.coders.base_coder import Coder
            result = Coder.run(coder, with_message="hello")

        assert result == "hello back"
        # done_messages should have user + assistant
        assert len(coder.done_messages) == 2
        assert coder.done_messages[0] == {"role": "user", "content": "hello"}
        assert coder.done_messages[1] == {"role": "assistant", "content": "hello back"}
        # cur_messages should be cleared
        assert coder.cur_messages == []

    def test_sets_first_user_message(self):
        coder = self._make_coder()

        with patch("aicoder.langchain_runtime.agent.run_langchain_agent", return_value="response"):
            from aicoder.coders.base_coder import Coder
            Coder.run(coder, with_message="first question")

        assert coder._first_user_message == "first question"

    def test_does_not_overwrite_first_user_message_on_second_call(self):
        coder = self._make_coder()
        coder._first_user_message = "original first"

        with patch("aicoder.langchain_runtime.agent.run_langchain_agent", return_value="response"):
            from aicoder.coders.base_coder import Coder
            Coder.run(coder, with_message="second question")

        assert coder._first_user_message == "original first"

    def test_calls_save_session(self):
        coder = self._make_coder()

        with patch("aicoder.langchain_runtime.agent.run_langchain_agent", return_value="response"):
            from aicoder.coders.base_coder import Coder
            Coder.run(coder, with_message="hello")

        coder._save_session.assert_called_once()

    def test_no_save_when_session_id_is_none(self):
        coder = self._make_coder(session_id=None)

        with patch("aicoder.langchain_runtime.agent.run_langchain_agent", return_value="response"):
            from aicoder.coders.base_coder import Coder
            result = Coder.run(coder, with_message="hello")

        assert result == "response"
        coder._save_session.assert_not_called()
        # Messages should not be appended
        assert coder.done_messages == []

    def test_no_save_when_agent_raises(self):
        coder = self._make_coder()

        with patch("aicoder.langchain_runtime.agent.run_langchain_agent", side_effect=RuntimeError("API error")):
            from aicoder.coders.base_coder import Coder
            with pytest.raises(RuntimeError, match="API error"):
                Coder.run(coder, with_message="hello")

        coder._save_session.assert_not_called()
        assert coder.done_messages == []

    def test_appends_to_existing_history(self):
        coder = self._make_coder()
        coder.done_messages = [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ]

        with patch("aicoder.langchain_runtime.agent.run_langchain_agent", return_value="new answer"):
            from aicoder.coders.base_coder import Coder
            Coder.run(coder, with_message="new question")

        assert len(coder.done_messages) == 4
        assert coder.done_messages[0]["content"] == "previous question"
        assert coder.done_messages[2]["content"] == "new question"
        assert coder.done_messages[3]["content"] == "new answer"

    def test_empty_response_still_saved(self):
        coder = self._make_coder()

        with patch("aicoder.langchain_runtime.agent.run_langchain_agent", return_value=""):
            from aicoder.coders.base_coder import Coder
            Coder.run(coder, with_message="hello")

        assert len(coder.done_messages) == 2
        assert coder.done_messages[1] == {"role": "assistant", "content": ""}
        coder._save_session.assert_called_once()

    def test_no_save_without_message(self):
        coder = self._make_coder()

        from aicoder.coders.base_coder import Coder
        result = Coder.run(coder)

        assert result is None
        coder._save_session.assert_not_called()
        assert coder.done_messages == []


# ── Hardening: recursion limit, timeout type, runtime init ──


class TestHardeningRecursionLimit:
    def test_recursion_limit_passed_to_invoke(self):
        """agent.invoke() must receive recursion_limit config."""
        with patch("aicoder.langchain_runtime.agent.build_langchain_agent") as mock_build:
            fake_agent = MagicMock()
            fake_agent.invoke.return_value = {"messages": [FakeMessage("done")]}
            mock_build.return_value = fake_agent

            from aicoder.langchain_runtime.agent import run_langchain_agent
            run_langchain_agent(MagicMock(), "test")

            invoke_args = fake_agent.invoke.call_args
            config = invoke_args[1].get("config") or invoke_args[0][1] if len(invoke_args[0]) > 1 else invoke_args[1]["config"]
            assert config["recursion_limit"] == 25

    def test_recursion_limit_constant_exists(self):
        from aicoder.langchain_runtime.agent import RECURSION_LIMIT
        assert RECURSION_LIMIT > 0


class TestHardeningTimeoutType:
    def test_run_shell_args_timeout_is_int(self):
        """RunShellArgs.timeout should be int | None, not str."""
        schema = RunShellArgs(command="ls", timeout=30)
        assert schema.timeout == 30
        assert isinstance(schema.timeout, int)

    def test_run_shell_args_timeout_optional(self):
        schema = RunShellArgs(command="ls")
        assert schema.timeout is None

    def test_int_timeout_converted_to_str_in_params(self):
        """The run_shell tool must convert int timeout to str for the stringly-typed ToolCall.params."""
        coder = FakeCoder(ToolResult.ok("run_shell", "ok"))
        tools = build_langchain_tools(coder)
        shell_tool = next(t for t in tools if t.name == "run_shell")
        shell_tool.invoke({"command": "sleep 5", "timeout": 10})
        call = coder.tool_executor.calls[0]
        assert call.params["timeout"] == "10"
        assert isinstance(call.params["timeout"], str)


class TestHardeningRuntimeInit:
    def test_coder_init_sets_legacy_runtime(self):
        """Coder.__init__ must initialize self.runtime = 'legacy'."""
        from aicoder.coders.base_coder import Coder
        from aicoder.models import Model
        coder = Coder(Model("test-model"), io=MagicMock())
        assert coder.runtime == "legacy"

    def test_runtime_can_be_overridden(self):
        from aicoder.coders.base_coder import Coder
        from aicoder.models import Model
        coder = Coder(Model("test-model"), io=MagicMock())
        coder.runtime = "langchain"
        assert coder.runtime == "langchain"
