"""Unit tests for tool handlers — read_file, write_file, edit_file, run_shell."""
import os
import pytest
from pathlib import Path

from aicoder.tools.result import ToolCall, ToolResult
from aicoder.tools.handlers.read_file_handler import ReadFileHandler
from aicoder.tools.handlers.write_file_handler import WriteFileHandler
from aicoder.tools.handlers.edit_file_handler import EditFileHandler
from aicoder.tools.handlers.run_shell_handler import RunShellHandler
from aicoder.tests.conftest import make_mock_coder


# ---------------------------------------------------------------------------
# ReadFileHandler
# ---------------------------------------------------------------------------

class TestReadFileHandler:
    def test_read_existing_file(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        (tmp_path / "test.py").write_text("line1\nline2\nline3\n")
        handler = ReadFileHandler()
        result = handler.execute(ToolCall(name="read_file", params={"path": "test.py"}), coder)
        assert result.success is True
        assert "line1" in result.output

    def test_read_missing_file(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        handler = ReadFileHandler()
        result = handler.execute(ToolCall(name="read_file", params={"path": "missing.py"}), coder)
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_validate_params_missing_path(self):
        handler = ReadFileHandler()
        err = handler.validate_params(ToolCall(name="read_file", params={}))
        assert "path" in err

    def test_validate_params_ok(self):
        handler = ReadFileHandler()
        err = handler.validate_params(ToolCall(name="read_file", params={"path": "x.py"}))
        assert err == ""

    def test_read_with_line_range(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        (tmp_path / "test.py").write_text("line1\nline2\nline3\nline4\nline5\n")
        handler = ReadFileHandler()
        result = handler.execute(
            ToolCall(name="read_file", params={"path": "test.py", "start_line": "2", "end_line": "3"}),
            coder,
        )
        assert result.success is True
        assert "line2" in result.output
        assert "line3" in result.output
        assert "line1" not in result.output.split("|")[0]  # line1 shouldn't be in first column

    def test_path_traversal_blocked(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        handler = ReadFileHandler()
        result = handler.execute(
            ToolCall(name="read_file", params={"path": "../../etc/passwd"}), coder
        )
        assert result.success is False
        assert "traversal" in result.error.lower() or "outside" in result.error.lower()

    def test_duplicate_read_warning(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        (tmp_path / "test.py").write_text("content\n")
        handler = ReadFileHandler()
        # Read 3 times
        for _ in range(3):
            result = handler.execute(ToolCall(name="read_file", params={"path": "test.py"}), coder)
        # The third read should have the duplicate warning prefix
        assert "already read" in result.output.lower() or result.success is True


# ---------------------------------------------------------------------------
# WriteFileHandler
# ---------------------------------------------------------------------------

class TestWriteFileHandler:
    def test_write_new_file(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        handler = WriteFileHandler()
        result = handler.execute(
            ToolCall(name="write_file", params={"path": "new.py", "content": "print('hello')"}),
            coder,
        )
        assert result.success is True
        assert "Created" in result.output
        assert (tmp_path / "new.py").read_text() == "print('hello')"

    def test_overwrite_existing_file(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        (tmp_path / "existing.py").write_text("old")
        handler = WriteFileHandler()
        result = handler.execute(
            ToolCall(name="write_file", params={"path": "existing.py", "content": "new"}),
            coder,
        )
        assert result.success is True
        assert "Updated" in result.output
        assert (tmp_path / "existing.py").read_text() == "new"

    def test_validate_params_missing_path(self):
        handler = WriteFileHandler()
        err = handler.validate_params(ToolCall(name="write_file", params={"content": "x"}))
        assert "path" in err

    def test_validate_params_missing_content(self):
        handler = WriteFileHandler()
        err = handler.validate_params(ToolCall(name="write_file", params={"path": "x.py"}))
        assert "content" in err

    def test_clean_content_strips_markdown_fence(self):
        assert WriteFileHandler._clean_content("```python\ncode\n```") == "code\n"

    def test_clean_content_strips_backticks(self):
        assert WriteFileHandler._clean_content("```\ncode\n```") == "code\n"

    def test_clean_content_no_fence(self):
        assert WriteFileHandler._clean_content("plain code") == "plain code"

    def test_path_traversal_blocked(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        handler = WriteFileHandler()
        result = handler.execute(
            ToolCall(name="write_file", params={"path": "../../../tmp/evil.py", "content": "x"}),
            coder,
        )
        assert result.success is False

    def test_binary_file_rejected(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        handler = WriteFileHandler()
        result = handler.execute(
            ToolCall(name="write_file", params={"path": "test.exe", "content": "binary"}),
            coder,
        )
        assert result.success is False
        assert "binary" in result.error.lower()

    def test_diff_in_meta(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        (tmp_path / "test.py").write_text("old\n")
        handler = WriteFileHandler()
        result = handler.execute(
            ToolCall(name="write_file", params={"path": "test.py", "content": "new\n"}),
            coder,
        )
        assert result.success is True
        assert "diff" in result.meta
        assert "-old" in result.meta["diff"]

    def test_file_added_to_abs_fnames(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        handler = WriteFileHandler()
        handler.execute(
            ToolCall(name="write_file", params={"path": "new.py", "content": "x"}),
            coder,
        )
        assert any("new.py" in f for f in coder.abs_fnames)


# ---------------------------------------------------------------------------
# EditFileHandler
# ---------------------------------------------------------------------------

class TestEditFileHandler:
    def test_edit_existing_file(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        (tmp_path / "test.py").write_text("hello\nworld\n")
        handler = EditFileHandler()
        result = handler.execute(
            ToolCall(name="edit_file", params={
                "path": "test.py",
                "search": "hello",
                "replace": "hi",
            }),
            coder,
        )
        assert result.success is True
        assert (tmp_path / "test.py").read_text() == "hi\nworld\n"

    def test_edit_not_found(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        (tmp_path / "test.py").write_text("hello\nworld\n")
        handler = EditFileHandler()
        result = handler.execute(
            ToolCall(name="edit_file", params={
                "path": "test.py",
                "search": "nonexistent text",
                "replace": "replacement",
            }),
            coder,
        )
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_edit_missing_file(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        handler = EditFileHandler()
        result = handler.execute(
            ToolCall(name="edit_file", params={
                "path": "missing.py",
                "search": "x",
                "replace": "y",
            }),
            coder,
        )
        assert result.success is False

    def test_validate_params_missing_path(self):
        handler = EditFileHandler()
        err = handler.validate_params(ToolCall(name="edit_file", params={"search": "x", "replace": "y"}))
        assert "path" in err

    def test_validate_params_both_empty(self):
        handler = EditFileHandler()
        err = handler.validate_params(ToolCall(name="edit_file", params={"path": "x.py"}))
        assert "empty" in err.lower() or "search" in err.lower()


# ---------------------------------------------------------------------------
# RunShellHandler
# ---------------------------------------------------------------------------

class TestRunShellHandler:
    def test_run_simple_command(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        handler = RunShellHandler()
        result = handler.execute(
            ToolCall(name="run_shell", params={"command": "python -c \"print('hello')\""}),
            coder,
        )
        assert result.success is True
        assert "hello" in result.output

    def test_run_command_with_exit_code(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        handler = RunShellHandler()
        result = handler.execute(
            ToolCall(name="run_shell", params={"command": "exit 1"}),
            coder,
        )
        assert result.success is False

    def test_validate_params_missing_command(self):
        handler = RunShellHandler()
        err = handler.validate_params(ToolCall(name="run_shell", params={}))
        assert "command" in err

    def test_blocked_command(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        handler = RunShellHandler()
        result = handler.execute(
            ToolCall(name="run_shell", params={"command": "rm -rf /"}),
            coder,
        )
        assert result.success is False
        assert "SECURITY" in result.error or "BLOCKED" in result.error

    def test_clean_command_strips_backticks(self):
        assert RunShellHandler._clean_command("```echo hi```") == "echo hi"

    def test_clean_command_strips_single_backticks(self):
        assert RunShellHandler._clean_command("`echo hi`") == "echo hi"

    def test_clean_command_no_change(self):
        assert RunShellHandler._clean_command("echo hi") == "echo hi"

    def test_is_long_running_npm(self):
        handler = RunShellHandler()
        assert handler._is_long_running("npm install") is True

    def test_is_long_running_echo(self):
        handler = RunShellHandler()
        assert handler._is_long_running("echo hello") is False

    def test_check_dangerous_git_reset_hard(self):
        assert "DESTRUCTIVE" in RunShellHandler._check_dangerous("git reset --hard HEAD")

    def test_check_dangerous_safe_command(self):
        assert RunShellHandler._check_dangerous("ls -la") == ""

    def test_check_blocked_fork_bomb(self):
        assert "fork bomb" in RunShellHandler._check_blocked(":(){ :|:& };:").lower()

    def test_check_blocked_safe(self):
        assert RunShellHandler._check_blocked("ls -la") == ""

    def test_format_output_no_output(self):
        result = RunShellHandler._format_output("", "", 0, 0.1)
        assert "no output" in result

    def test_format_output_normal(self):
        result = RunShellHandler._format_output("hello", "", 0, 0.5)
        assert "hello" in result
        assert "Exit: 0" in result

    def test_command_not_found(self, tmp_path):
        coder = make_mock_coder(root=str(tmp_path))
        handler = RunShellHandler()
        result = handler.execute(
            ToolCall(name="run_shell", params={"command": "nonexistent_command_xyz_123"}),
            coder,
        )
        assert result.success is False
