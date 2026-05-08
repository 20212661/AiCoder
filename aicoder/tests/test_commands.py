"""Unit tests for commands.py — slash command parsing and execution."""
import pytest
from unittest.mock import MagicMock, patch

from aicoder.commands import Commands, SwitchCoder, _parse_quoted_filenames
from aicoder.tests.conftest import MockIO, make_mock_coder


@pytest.fixture
def mock_coder_cmds(tmp_path):
    coder = make_mock_coder(root=str(tmp_path))
    return coder


@pytest.fixture
def cmds(mock_coder_cmds):
    io = mock_coder_cmds.io
    return Commands(io=io, coder=mock_coder_cmds)


class TestParseQuotedFilenames:
    def test_simple_space_separated(self):
        assert _parse_quoted_filenames("a.py b.py") == ["a.py", "b.py"]

    def test_double_quoted(self):
        assert _parse_quoted_filenames('"hello world.py" b.py') == ["hello world.py", "b.py"]

    def test_single_quoted(self):
        assert _parse_quoted_filenames("'my file.py' other.py") == ["my file.py", "other.py"]

    def test_empty_string(self):
        assert _parse_quoted_filenames("") == []

    def test_single_file(self):
        assert _parse_quoted_filenames("file.py") == ["file.py"]

    def test_mixed_quotes(self):
        result = _parse_quoted_filenames('"a.py" \'b.py\' c.py')
        assert result == ["a.py", "b.py", "c.py"]


class TestIsCommand:
    def test_slash_command(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        assert c.is_command("/help") is True

    def test_shell_command(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        assert c.is_command("!ls") is True

    def test_plain_text(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        assert c.is_command("hello world") is False

    def test_empty_string(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        assert c.is_command("") is False


class TestGetCommands:
    def test_returns_slash_prefixed(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        cmds = c.get_commands()
        assert all(cmd.startswith("/") for cmd in cmds)

    def test_includes_help(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        cmds = c.get_commands()
        assert "/help" in cmds

    def test_includes_add(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        cmds = c.get_commands()
        assert "/add" in cmds

    def test_includes_model(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        cmds = c.get_commands()
        assert "/model" in cmds


class TestMatchingCommands:
    def test_exact_match(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        result = c.matching_commands("/help")
        assert result is not None
        matching, first_word, rest = result
        assert "/help" in matching

    def test_prefix_match(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        result = c.matching_commands("/h")
        assert result is not None
        matching, _, _ = result
        assert "/help" in matching

    def test_no_match(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        result = c.matching_commands("/nonexistent")
        assert result is not None
        matching, _, _ = result
        assert len(matching) == 0

    def test_empty_input(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        assert c.matching_commands("") is None


class TestRun:
    def test_shell_shortcut(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        c.do_run = MagicMock()
        c.run("!echo hello")
        c.do_run.assert_called_once_with("run", "echo hello")

    def test_exact_command(self):
        c = Commands(io=MockIO(), coder=MagicMock())
        c.do_run = MagicMock()
        c.run("/help")
        c.do_run.assert_called_once_with("help", "")

    def test_unknown_command(self):
        io = MockIO()
        c = Commands(io=io, coder=MagicMock())
        c.run("/zzzznonexistent")
        assert any("Unknown command" in e for e in io.errors)


class TestCmdAdd:
    def test_add_existing_file(self, cmds, mock_coder_cmds, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")
        cmds.cmd_add(str(test_file))
        assert str(test_file.resolve()) in mock_coder_cmds.abs_fnames

    def test_add_already_added_file(self, cmds, mock_coder_cmds, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")
        abs_path = str(test_file.resolve())
        mock_coder_cmds.abs_fnames.add(abs_path)
        cmds.cmd_add(str(test_file))
        assert any("already in the chat" in e for e in mock_coder_cmds.io.errors)

    def test_add_glob_pattern(self, cmds, mock_coder_cmds, tmp_path):
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        pattern = str(tmp_path / "*.py")
        cmds.cmd_add(pattern)
        assert len(mock_coder_cmds.abs_fnames) >= 2


class TestCmdDrop:
    def test_drop_all(self, cmds, mock_coder_cmds):
        mock_coder_cmds.abs_fnames = {"/a.py", "/b.py"}
        mock_coder_cmds.abs_read_only_fnames = {"/c.py"}
        cmds.cmd_drop("")
        assert len(mock_coder_cmds.abs_fnames) == 0
        assert len(mock_coder_cmds.abs_read_only_fnames) == 0

    def test_drop_specific(self, cmds, mock_coder_cmds):
        mock_coder_cmds.abs_fnames = {"/path/to/test.py", "/path/to/other.py"}
        mock_coder_cmds.get_rel_fname = lambda f: f.split("/")[-1]
        cmds.cmd_drop("test.py")
        assert "/path/to/test.py" not in mock_coder_cmds.abs_fnames
        assert "/path/to/other.py" in mock_coder_cmds.abs_fnames

    def test_drop_no_match(self, cmds, mock_coder_cmds):
        mock_coder_cmds.abs_fnames = {"/a.py"}
        mock_coder_cmds.get_rel_fname = lambda f: f.split("/")[-1]
        cmds.cmd_drop("nonexistent.py")
        assert any("No files matched" in e for e in mock_coder_cmds.io.errors)


class TestCmdClear:
    def test_clear(self, cmds, mock_coder_cmds):
        mock_coder_cmds.done_messages = [{"role": "user", "content": "hi"}]
        mock_coder_cmds.cur_messages = [{"role": "assistant", "content": "hello"}]
        cmds.cmd_clear("")
        assert mock_coder_cmds.done_messages == []
        assert mock_coder_cmds.cur_messages == []


class TestCmdLs:
    def test_ls_with_files(self, cmds, mock_coder_cmds, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x")
        mock_coder_cmds.abs_fnames = {str(f.resolve())}
        cmds.cmd_ls("")
        assert any("test.py" in o for o in mock_coder_cmds.io.outputs)

    def test_ls_empty(self, cmds, mock_coder_cmds):
        cmds.cmd_ls("")
        assert any("No files" in o for o in mock_coder_cmds.io.outputs)


class TestCmdModel:
    def test_model_no_args(self, cmds, mock_coder_cmds):
        mock_coder_cmds.main_model = MagicMock()
        mock_coder_cmds.main_model.name = "gpt-4o"
        cmds.cmd_model("")
        assert any("gpt-4o" in o for o in mock_coder_cmds.io.outputs)

    def test_model_switch_raises(self, cmds, mock_coder_cmds):
        mock_coder_cmds.main_model = MagicMock()
        mock_coder_cmds.main_model.name = "gpt-4o"
        mock_coder_cmds.main_model.edit_format = "whole"
        mock_coder_cmds.edit_format = "whole"
        with pytest.raises(SwitchCoder):
            cmds.cmd_model("deepseek-chat")


class TestCmdModes:
    def test_plan_sets_plan_mode(self, cmds, mock_coder_cmds):
        mock_coder_cmds.tool_executor = MagicMock()
        mock_coder_cmds._update_tool_model_info = MagicMock()

        cmds.cmd_plan("")

        mock_coder_cmds.tool_executor.set_mode.assert_called_once_with("plan")
        assert any("inspection shell commands" in o for o in mock_coder_cmds.io.outputs)

    def test_act_sets_act_mode(self, cmds, mock_coder_cmds):
        mock_coder_cmds.tool_executor = MagicMock()
        mock_coder_cmds._update_tool_model_info = MagicMock()

        cmds.cmd_act("")

        mock_coder_cmds.tool_executor.set_mode.assert_called_once_with("act")
        assert any("routine shell actions" in o for o in mock_coder_cmds.io.outputs)


class TestCmdRun:
    def test_run_echo(self, cmds, mock_coder_cmds):
        cmds.cmd_run("python -c \"print('hello')\"")
        assert any("hello" in o for o in mock_coder_cmds.io.outputs)

    def test_run_empty(self, cmds, mock_coder_cmds):
        cmds.cmd_run("")
        assert len(mock_coder_cmds.io.outputs) == 0
