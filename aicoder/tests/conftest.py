"""Shared test fixtures and mock infrastructure."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock IO
# ---------------------------------------------------------------------------

class MockIO:
    """Lightweight IO mock that captures output without touching the terminal."""

    def __init__(self):
        self.outputs: list[str] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self._yes = False
        self._confirm_answers: list[bool] = []

    def tool_output(self, message="", **kw):
        self.outputs.append(message)

    def tool_error(self, message=""):
        self.errors.append(message)

    def tool_warning(self, message=""):
        self.warnings.append(message)

    def confirm_ask(self, question, **kw):
        if self._confirm_answers:
            return self._confirm_answers.pop(0)
        return self._yes

    def set_confirm_answers(self, *answers: bool):
        self._confirm_answers = list(answers)

    def read_text(self, filename):
        try:
            with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            return None

    def write_text(self, filename, content):
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)


# ---------------------------------------------------------------------------
# Mock Coder
# ---------------------------------------------------------------------------

def make_mock_coder(root=None, abs_fnames=None):
    """Create a minimal mock Coder for handler tests."""
    coder = MagicMock()
    root = root or tempfile.mkdtemp()
    coder.root = root
    coder.abs_fnames = set(abs_fnames or [])
    coder.abs_read_only_fnames = set()
    coder.fence = ("```", "```")
    coder.done_messages = []
    coder.cur_messages = []
    coder.aider_commit_hashes = set()
    coder.commit_before_message = []
    coder.session_id = "test-session"
    coder._first_user_message = None
    coder._approval = None

    def abs_root_path(rel):
        return str(Path(root) / rel)

    coder.abs_root_path = abs_root_path

    io = MockIO()
    coder.io = io

    def get_rel_fname(abs_path):
        return str(Path(abs_path).relative_to(root))

    coder.get_rel_fname = get_rel_fname
    coder.get_inchat_relative_files = lambda: [
        str(Path(f).relative_to(root)) for f in coder.abs_fnames
    ]
    return coder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_io():
    return MockIO()


@pytest.fixture
def mock_coder(tmp_path):
    return make_mock_coder(root=str(tmp_path))


@pytest.fixture
def temp_dir(tmp_path):
    """Return a temporary directory path."""
    return tmp_path
