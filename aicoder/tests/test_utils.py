"""Unit tests for utils.py and exceptions.py."""
import pytest
from pathlib import Path

from aicoder.utils import safe_abs_path, is_image_file, format_messages
from aicoder.exceptions import AiCoderError, ConfigError, LLMError, ToolError


class TestSafeAbsPath:
    def test_normal_path(self):
        result = safe_abs_path("test.py")
        assert Path(result).is_absolute()

    def test_absolute_path(self):
        result = safe_abs_path("/tmp/test.py")
        assert Path(result).is_absolute()

    def test_relative_path(self):
        result = safe_abs_path("some/dir/file.txt")
        assert Path(result).is_absolute()


class TestIsImageFile:
    def test_png(self):
        assert is_image_file("photo.png") is True

    def test_jpg(self):
        assert is_image_file("photo.jpg") is True

    def test_svg(self):
        assert is_image_file("icon.svg") is True

    def test_python_file(self):
        assert is_image_file("script.py") is False

    def test_case_insensitive(self):
        assert is_image_file("photo.PNG") is True
        assert is_image_file("photo.Jpeg") is True


class TestFormatMessages:
    def test_basic(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        result = format_messages(msgs)
        assert "[0] user: hello" in result
        assert "[1] assistant: world" in result

    def test_long_content_truncated(self):
        msg = {"role": "user", "content": "x" * 200}
        result = format_messages([msg])
        assert "..." in result
        assert len(result) < 250

    def test_empty_messages(self):
        result = format_messages([])
        assert result == ""


class TestExceptions:
    def test_aicoder_error_is_exception(self):
        assert issubclass(AiCoderError, Exception)

    def test_config_error(self):
        assert issubclass(ConfigError, AiCoderError)
        e = ConfigError("bad config")
        assert str(e) == "bad config"

    def test_llm_error(self):
        assert issubclass(LLMError, AiCoderError)
        e = LLMError("gpt-4o", "timeout")
        assert "gpt-4o" in str(e)
        assert "timeout" in str(e)
        assert e.model == "gpt-4o"

    def test_tool_error(self):
        assert issubclass(ToolError, AiCoderError)
