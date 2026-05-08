"""Shared test fixtures and mock infrastructure."""
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Mock IO — lightweight (for handler / command tests)
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
# Mock IO — full (for graph / workflow tests with streaming support)
# ---------------------------------------------------------------------------

class FakeIO:
    """IO mock with streaming, finalize, and structured approval support."""

    def __init__(self, confirm_answers: list[bool] | None = None):
        self.outputs: list[str] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.streaming_tokens: list[str] = []
        self.finalized: list[tuple] = []
        self._confirm_answers = list(confirm_answers or [])

    def tool_output(self, msg="", **kw):
        self.outputs.append(msg)

    def tool_error(self, msg=""):
        self.errors.append(msg)

    def tool_warning(self, msg=""):
        self.warnings.append(msg)

    def print_streaming(self, token):
        self.streaming_tokens.append(token)

    def print_assistant_output(self, text):
        self.outputs.append(text)

    def finalize_streaming(self, text, is_intermediate=False):
        self.finalized.append((text, is_intermediate))

    def user_input(self, text):
        pass

    def confirm_ask(self, question, **kw):
        if self._confirm_answers:
            return self._confirm_answers.pop(0)
        return False

    def request_structured_approval(self, kind, desc, preview):
        if self._confirm_answers:
            return self._confirm_answers.pop(0)
        return False

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
# Fake model
# ---------------------------------------------------------------------------

class FakeModel:
    """Minimal model stub with configurable responses."""

    def __init__(self, responses: list[str] | None = None, max_input_tokens: int = 128000):
        self.name = "test-model"
        self.max_input_tokens = max_input_tokens
        self.responses = list(responses or [])
        self._call_idx = 0

    def send_completion(self, messages, stream=False):
        text = self.responses[self._call_idx] if self._call_idx < len(self.responses) else "done"
        self._call_idx += 1
        return self._fake_stream(text)

    def simple_send(self, messages):
        text = self.responses[self._call_idx] if self._call_idx < len(self.responses) else "done"
        self._call_idx += 1
        return text

    @staticmethod
    def _fake_stream(text):
        chunk_size = 20
        for i in range(0, len(text), chunk_size):
            delta = SimpleNamespace(content=text[i : i + chunk_size])
            choice = SimpleNamespace(delta=delta)
            yield SimpleNamespace(choices=[choice])

    def token_count(self, messages):
        total = sum(len(m.get("content", "")) for m in messages) // 4
        return total


# ---------------------------------------------------------------------------
# Mock Coder factories
# ---------------------------------------------------------------------------

# Tool parameter specs: name -> list of param names
_TOOL_PARAMS = {
    "read_file": ["path"],
    "write_file": ["path", "content"],
    "edit_file": ["path", "old_text", "new_text"],
    "run_shell": ["command"],
    "list_files": ["path"],
    "search_files": ["query", "path"],
    "list_code_defs": ["path"],
}


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


def make_graph_coder(
    responses: list[str],
    confirm_answers: list[bool] | None = None,
    mode: str = "act",
    root: str | None = None,
):
    """Build a fully-wired mock coder for graph / workflow tests."""
    from aicoder.tools.executor import ToolCoordinator, ToolExecutor
    from aicoder.tools.registry import ToolRegistry
    from aicoder.tools.result import ExecutionState
    from aicoder.tools.handlers.read_file_handler import ReadFileHandler
    from aicoder.tools.handlers.list_files_handler import ListFilesHandler
    from aicoder.tools.handlers.search_files_handler import SearchFilesHandler
    from aicoder.tools.handlers.list_code_defs_handler import ListCodeDefsHandler
    from aicoder.tools.handlers.edit_file_handler import EditFileHandler
    from aicoder.tools.handlers.write_file_handler import WriteFileHandler
    from aicoder.tools.handlers.run_shell_handler import RunShellHandler
    from aicoder.tools.spec import ToolSpec, ParamSpec

    root = root or os.getcwd()
    io = FakeIO(confirm_answers=confirm_answers)
    model = FakeModel(responses)

    coder = MagicMock()
    coder.io = io
    coder.main_model = model
    coder.stream = True
    coder.root = root
    coder.session_id = "test-session"
    coder.done_messages = []
    coder.cur_messages = []
    coder.abs_fnames = set()
    coder.abs_read_only_fnames = set()
    coder._first_message = True
    coder._approval = None
    coder.auto_commits = False
    coder.repo = None
    coder._first_user_message = None
    coder.verbose = False
    coder.summarizer = None
    coder.edit_format = "whole"
    coder.abs_root_path_cache = {}

    coder._save_session = MagicMock()
    coder.auto_commit = MagicMock()

    def abs_root_path(path):
        p = Path(path)
        res = str(Path(root) / path)
        return str(Path(res).resolve())

    coder.abs_root_path = abs_root_path

    # Tool infrastructure
    registry = ToolRegistry()
    coord = ToolCoordinator()
    exec_state = ExecutionState()
    exec_state.mode = mode

    handlers = [
        ReadFileHandler(),
        ListFilesHandler(),
        SearchFilesHandler(),
        ListCodeDefsHandler(),
        EditFileHandler(),
        WriteFileHandler(),
        RunShellHandler(),
    ]
    for h in handlers:
        param_names = _TOOL_PARAMS.get(h.name, [])
        param_specs = [
            ParamSpec(name=p, required=True, description=p, usage=f"<{p}>value</{p}>")
            for p in param_names
        ]
        registry.register(ToolSpec(
            name=h.name,
            description=h.name,
            parameters=param_specs,
            instruction="",
        ))
        coord.register(h)

    coder.tool_registry = registry
    coder.tool_coordinator = coord
    coder.tool_exec_state = exec_state
    coder.tool_executor = ToolExecutor(coord, coder, exec_state)

    return coder


def make_tool_call_xml(name: str, **params) -> str:
    """Build an XML tool call string."""
    inner = "".join(f"<{k}>{v}</{k}>" for k, v in params.items())
    return f"<{name}>{inner}</{name}>"


def invoke_graph(coder, user_input: str, mode: str = "act", *, max_loops: int = 5):
    """Build and invoke the graph with the given coder and patched message builder."""
    from aicoder.graph.workflow import build_agent_graph

    graph = build_agent_graph()
    state: dict = {
        "session_id": coder.session_id,
        "user_input": user_input,
        "messages": [],
        "mode": mode,
        "phase": "idle",
        "root": coder.root,
        "pending_tool_calls": [],
        "tool_observations": [],
        "loop_count": 0,
        "max_loops": max_loops,
        "_coder": coder,
    }
    with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
         patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
         patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode:
        mock_sys.return_value = [{"role": "system", "content": "You are a helpful assistant."}]
        mock_chat.return_value = []
        mock_mode.return_value = []
        result = graph.invoke(state)
    return result


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


@pytest.fixture
def graph_coder(tmp_path):
    """A fully-wired graph test coder with a simple text response."""
    return make_graph_coder(responses=["Hello!"], root=str(tmp_path))
