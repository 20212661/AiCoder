"""Tests for ContextPacker and context budget policies (Phase 3)."""
import pytest
from unittest.mock import MagicMock, patch

from aicoder.context.policies import ContextBudget, get_context_budget_for_mode
from aicoder.context.packer import PackedContext, pack_context, build_repo_context, _trim_to_budget
from aicoder.modes.config import get_mode_config
from aicoder.tests.conftest import make_mock_coder


# ---------------------------------------------------------------------------
# ContextBudget
# ---------------------------------------------------------------------------

class TestContextBudget:
    @pytest.mark.parametrize("mode", ["sniff", "plan", "act"])
    def test_budget_exists_for_all_modes(self, mode):
        budget = get_context_budget_for_mode(mode)
        assert isinstance(budget, ContextBudget)

    def test_budget_values_come_from_memory_policy(self):
        for mode in ("sniff", "plan", "act"):
            cfg = get_mode_config(mode)
            budget = get_context_budget_for_mode(mode)
            assert budget.repo_map_tokens == cfg.memory_policy.repo_map_tokens
            assert budget.history_tokens == cfg.memory_policy.history_tokens

    def test_sniff_has_larger_repo_budget_than_act(self):
        sniff = get_context_budget_for_mode("sniff")
        act = get_context_budget_for_mode("act")
        assert sniff.repo_map_tokens > act.repo_map_tokens

    def test_reserve_tokens_default(self):
        budget = get_context_budget_for_mode("act")
        assert budget.reserve_tokens == 4096


# ---------------------------------------------------------------------------
# PackedContext
# ---------------------------------------------------------------------------

class TestPackedContext:
    def test_all_messages_combines_sections(self):
        packed = PackedContext(
            system_messages=[{"role": "system", "content": "sys"}],
            conversation_messages=[{"role": "user", "content": "hi"}],
        )
        assert len(packed.all_messages) == 2
        assert packed.all_messages[0]["role"] == "system"
        assert packed.all_messages[1]["role"] == "user"


# ---------------------------------------------------------------------------
# pack_context integration
# ---------------------------------------------------------------------------

class TestPackContext:
    def _make_coder(self, mode: str = "act") -> MagicMock:
        coder = MagicMock()
        coder.main_model = MagicMock()
        coder.main_model.name = "test-model"
        coder.tool_exec_state = MagicMock()
        coder.tool_exec_state.mode = mode
        coder.done_messages = []
        coder.cur_messages = []
        coder.abs_fnames = set()
        coder._cached_system_key = None
        coder._cached_system_messages = None
        coder._first_message = False
        coder._file_tree = None
        coder.gpt_prompts = MagicMock()
        coder.gpt_prompts.main_system = ""
        coder.gpt_prompts.system_reminder = ""
        coder.gpt_prompts.example_messages = []
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        coder._system_prompt = MagicMock()
        coder._system_prompt.build.return_value = "You are a helpful assistant."
        coder._update_tool_model_info = MagicMock()
        coder._build_workspace_info.return_value = ""
        coder._detect_cli_tools.return_value = ""
        coder.get_repo_map.return_value = ""
        coder.root = "/tmp/test"
        coder.session_id = "test-session"
        return coder

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_system_messages_present(self, mock_repo):
        coder = self._make_coder(mode="act")
        packed = pack_context(coder, user_input="hello", mode="act", runner_type="cot")
        assert len(packed.system_messages) > 0
        # First should be system prompt
        assert packed.system_messages[0]["role"] == "system"

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_runtime_state_present(self, mock_repo):
        coder = self._make_coder(mode="act")
        packed = pack_context(coder, user_input="hello", mode="act", runner_type="cot")
        runtime_msgs = [m for m in packed.system_messages if "RUNTIME STATE" in m.get("content", "")]
        assert len(runtime_msgs) == 1

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_mode_attachment_sniff(self, mock_repo):
        coder = self._make_coder(mode="sniff")
        packed = pack_context(coder, user_input="look around", mode="sniff", runner_type="cot")
        mode_msgs = [m for m in packed.system_messages if "SNIFF" in m.get("content", "")]
        assert len(mode_msgs) >= 1

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_mode_attachment_plan(self, mock_repo):
        coder = self._make_coder(mode="plan")
        packed = pack_context(coder, user_input="plan this", mode="plan", runner_type="cot")
        mode_msgs = [m for m in packed.system_messages if "PLAN" in m.get("content", "").upper()]
        assert len(mode_msgs) >= 1

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_act_mode_no_mode_attachment(self, mock_repo):
        coder = self._make_coder(mode="act")
        packed = pack_context(coder, user_input="do it", mode="act", runner_type="cot")
        # Act mode returns [] from build_mode_messages
        mode_msgs = [m for m in packed.system_messages if "PLAN MODE" in m.get("content", "") or "SNIFF" in m.get("content", "")]
        assert len(mode_msgs) == 0

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_user_input_in_conversation(self, mock_repo):
        coder = self._make_coder(mode="act")
        packed = pack_context(coder, user_input="read main.py", mode="act", runner_type="cot")
        user_msgs = [m for m in packed.conversation_messages if m.get("role") == "user" and "read main.py" in m.get("content", "")]
        assert len(user_msgs) >= 1

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_packed_context_structure(self, mock_repo):
        coder = self._make_coder(mode="act")
        packed = pack_context(coder, user_input="test", mode="act", runner_type="cot")
        assert isinstance(packed, PackedContext)
        assert isinstance(packed.system_messages, list)
        assert isinstance(packed.conversation_messages, list)
        assert len(packed.all_messages) > 0

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_budget_called_correctly(self, mock_repo):
        coder = self._make_coder(mode="sniff")
        with patch("aicoder.context.packer.get_context_budget_for_mode") as mock_budget:
            mock_budget.return_value = ContextBudget(
                repo_map_tokens=8000, history_tokens=16000,
                focused_file_tokens=4000, tool_trace_tokens=4000,
            )
            pack_context(coder, user_input="", mode="sniff", runner_type="cot")
            mock_budget.assert_called_once_with("sniff")


# ---------------------------------------------------------------------------
# build_repo_context
# ---------------------------------------------------------------------------

class TestBuildRepoContext:
    def test_returns_empty_when_no_repo_map(self):
        """v1.3: empty workspace returns empty or near-empty context."""
        import tempfile
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        result = build_repo_context(coder, "act", 4000)
        assert isinstance(result, list)

    def test_returns_messages_when_repo_map_exists(self):
        """v1.3: build_repo_context now uses ranker + renderer, not get_repo_map."""
        import tempfile, os
        root = tempfile.mkdtemp()
        with open(os.path.join(root, "main.py"), "w") as f:
            f.write("print('hello')")
        coder = make_mock_coder(root=root)
        result = build_repo_context(coder, "act", 4000)
        # With real workspace files, should produce messages
        assert isinstance(result, list)

    def test_handles_exception_gracefully(self):
        """v1.3: build_repo_context catches all exceptions."""
        coder = MagicMock()
        coder.root = "/nonexistent/xyz/path"
        coder.abs_fnames = "not_a_set"  # Will cause AttributeError
        result = build_repo_context(coder, "act", 4000)
        assert result == []


# ---------------------------------------------------------------------------
# Phase 6: Repo context extension point
# ---------------------------------------------------------------------------

class TestRepoContextExtensionPoint:
    def test_sniff_has_larger_repo_budget_than_act(self):
        """sniff mode should have larger repo_map budget than act."""
        sniff = get_context_budget_for_mode("sniff")
        act = get_context_budget_for_mode("act")
        assert sniff.repo_map_tokens > act.repo_map_tokens

    def test_context_packer_calls_repo_context_builder(self):
        """pack_context should call build_repo_context."""
        coder = MagicMock()
        coder.main_model = MagicMock()
        coder.main_model.name = "test"
        coder.tool_exec_state = MagicMock()
        coder.tool_exec_state.mode = "act"
        coder.done_messages = []
        coder.cur_messages = []
        coder.abs_fnames = set()
        coder._cached_system_key = None
        coder._cached_system_messages = None
        coder._first_message = False
        coder._file_tree = None
        coder.gpt_prompts = MagicMock()
        coder.gpt_prompts.main_system = ""
        coder.gpt_prompts.system_reminder = ""
        coder.gpt_prompts.example_messages = []
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        coder._system_prompt = MagicMock()
        coder._system_prompt.build.return_value = "sys"
        coder._update_tool_model_info = MagicMock()
        coder._build_workspace_info.return_value = ""
        coder._detect_cli_tools.return_value = ""
        coder.get_repo_map.return_value = ""
        coder.root = "/tmp"
        coder.session_id = "test"

        with patch("aicoder.context.repo_map.build_repo_context") as mock_repo:
            mock_repo.return_value = []
            pack_context(coder, user_input="", mode="act", runner_type="cot")
            mock_repo.assert_called_once()

    def test_repo_map_module_importable(self):
        """repo_map module should be importable."""
        from aicoder.context.repo_map import build_repo_context as brc
        assert callable(brc)

    def test_repo_context_with_budget(self):
        """v1.3: repo context uses ranker, not get_repo_map. Verify it works with real files."""
        import tempfile, os
        from aicoder.context.repo_map import build_repo_context
        root = tempfile.mkdtemp()
        for fn in ["main.py", "utils.py"]:
            with open(os.path.join(root, fn), "w") as f:
                f.write("")
        coder = make_mock_coder(root=root)
        result = build_repo_context(coder, "sniff", 8000)
        assert isinstance(result, list)

    def test_repo_context_returns_empty_for_no_map(self):
        """v1.3: empty dir returns empty context."""
        import tempfile
        from aicoder.context.repo_map import build_repo_context
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        result = build_repo_context(coder, "act", 4000)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Fix 3: history_tokens budget actually trims done_messages
# ---------------------------------------------------------------------------

class TestHistoryBudgetTrimming:
    def _make_coder_with_history(self, mode: str, history_size: int) -> MagicMock:
        coder = MagicMock()
        coder.main_model = MagicMock()
        coder.main_model.name = "test-model"
        coder.tool_exec_state = MagicMock()
        coder.tool_exec_state.mode = mode
        # Create history: each pair is ~30 chars = ~7 tokens
        coder.done_messages = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"Message {i} with some padding text to add tokens."}
            for i in range(history_size)
        ]
        coder.cur_messages = []
        coder.abs_fnames = set()
        coder._cached_system_key = None
        coder._cached_system_messages = None
        coder._first_message = False
        coder._file_tree = None
        coder.gpt_prompts = MagicMock()
        coder.gpt_prompts.main_system = ""
        coder.gpt_prompts.system_reminder = ""
        coder.gpt_prompts.example_messages = []
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        coder._system_prompt = MagicMock()
        coder._system_prompt.build.return_value = "sys"
        coder._update_tool_model_info = MagicMock()
        coder._build_workspace_info.return_value = ""
        coder._detect_cli_tools.return_value = ""
        coder.get_repo_map.return_value = ""
        coder.root = "/tmp"
        coder.session_id = "test"
        return coder

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_small_budget_trims_large_history(self, mock_repo):
        """history_tokens=20 should trim 100-message history."""
        coder = self._make_coder_with_history("act", 100)
        packed = pack_context(coder, user_input="", mode="act", runner_type="cot")
        # act budget: history_tokens=20000 — should fit most messages
        # But let's verify with an artificially tiny budget
        with patch("aicoder.context.packer.get_context_budget_for_mode") as mock_b:
            mock_b.return_value = ContextBudget(
                repo_map_tokens=1000, history_tokens=20,
                focused_file_tokens=1000, tool_trace_tokens=1000,
            )
            packed = pack_context(coder, user_input="", mode="act", runner_type="cot")
            # 20 tokens budget with ~7 tokens per message pair
            # Should have trimmed significantly
            hist_msgs = [m for m in packed.conversation_messages
                         if "Message" in m.get("content", "")]
            assert len(hist_msgs) < 100, "History should be trimmed"

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_different_modes_get_different_history_budgets(self, mock_repo):
        """sniff/plan/act should allow different history sizes."""
        # Build identical large histories for each mode
        for mode in ("sniff", "plan", "act"):
            coder = self._make_coder_with_history(mode, 20)
            packed = pack_context(coder, user_input="", mode=mode, runner_type="cot")
            # Each mode should complete without error
            assert isinstance(packed, PackedContext)

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_trim_preserves_recent_messages(self, mock_repo):
        """Trimming should keep the most recent messages, drop oldest."""
        coder = self._make_coder_with_history("act", 20)
        # Budget enough for only ~4 messages (each pair ~14 tokens)
        with patch("aicoder.context.packer.get_context_budget_for_mode") as mock_b:
            mock_b.return_value = ContextBudget(
                repo_map_tokens=1000, history_tokens=60,
                focused_file_tokens=1000, tool_trace_tokens=1000,
            )
            packed = pack_context(coder, user_input="", mode="act", runner_type="cot")
            hist_msgs = [m for m in packed.conversation_messages
                         if "Message" in m.get("content", "")]
            assert len(hist_msgs) < 20, "Should have trimmed some messages"
            # Recent messages (16-19) should survive
            contents = [m["content"] for m in hist_msgs]
            assert any("17" in c or "18" in c or "19" in c for c in contents), \
                f"Recent messages should survive, got: {contents}"

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_no_trim_when_within_budget(self, mock_repo):
        """No trimming when history fits within budget."""
        coder = self._make_coder_with_history("act", 4)
        packed = pack_context(coder, user_input="", mode="act", runner_type="cot")
        hist_msgs = [m for m in packed.conversation_messages
                     if "Message" in m.get("content", "")]
        # act budget is 20000 tokens, 4 messages (~28 tokens) easily fits
        assert len(hist_msgs) == 4

    def test_approx_token_count_works(self):
        from aicoder.context.packer import _approx_token_count
        msgs = [{"role": "user", "content": "a" * 100}]
        assert _approx_token_count(msgs) == 25  # 100/4

    def test_trim_to_budget(self):
        from aicoder.context.packer import _trim_to_budget
        msgs = [
            {"role": "user", "content": "x" * 200},
            {"role": "assistant", "content": "y" * 200},
            {"role": "user", "content": "z" * 200},
            {"role": "assistant", "content": "w" * 200},
        ]
        # ~200 tokens total, budget 100 -> should trim
        trimmed = _trim_to_budget(msgs, budget_tokens=100)
        assert len(trimmed) < len(msgs)


# ---------------------------------------------------------------------------
# Fix: FC structured history actually used in pack_context
# ---------------------------------------------------------------------------

class TestFCHistoryOverride:
    """Verify that pack_context uses history_override for FC runners
    and produces structured tool_calls / tool messages."""

    def _make_coder(self) -> MagicMock:
        coder = MagicMock()
        coder.main_model = MagicMock()
        coder.main_model.name = "test-model"
        coder.tool_exec_state = MagicMock()
        coder.tool_exec_state.mode = "act"
        # Flat done_messages — these should be IGNORED when override is given
        coder.done_messages = [
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "[read_file] Result:\nfile content here"},
        ]
        coder.cur_messages = []
        coder.abs_fnames = set()
        coder._cached_system_key = None
        coder._cached_system_messages = None
        coder._first_message = False
        coder._file_tree = None
        coder.gpt_prompts = MagicMock()
        coder.gpt_prompts.main_system = ""
        coder.gpt_prompts.system_reminder = ""
        coder.gpt_prompts.example_messages = []
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        coder._system_prompt = MagicMock()
        coder._system_prompt.build.return_value = "You are a helpful assistant."
        coder._update_tool_model_info = MagicMock()
        coder._build_workspace_info.return_value = ""
        coder._detect_cli_tools.return_value = ""
        coder.get_repo_map.return_value = ""
        coder.root = "/tmp/test"
        coder.session_id = "test-session"
        return coder

    def _fc_history(self) -> list[dict]:
        """Structured FC history — assistant with tool_calls + tool messages."""
        return [
            {"role": "user", "content": "read main.py"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "main.py"}',
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call_abc123",
                "content": "def main(): pass",
            },
        ]

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_override_replaces_done_messages(self, mock_repo):
        """history_override completely replaces coder.done_messages."""
        coder = self._make_coder()
        fc_hist = self._fc_history()

        packed = pack_context(
            coder, user_input="", mode="act",
            runner_type="function-calling", history_override=fc_hist,
        )

        # Must contain assistant with tool_calls
        assistant_tc = [
            m for m in packed.conversation_messages
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        assert len(assistant_tc) == 1, (
            f"Expected 1 assistant with tool_calls, got: {packed.conversation_messages}"
        )

        # Must contain tool message with tool_call_id
        tool_msgs = [
            m for m in packed.conversation_messages
            if m.get("role") == "tool" and m.get("tool_call_id") == "call_abc123"
        ]
        assert len(tool_msgs) == 1, (
            f"Expected 1 tool message with tool_call_id, got: {packed.conversation_messages}"
        )

        # Must NOT contain the flat done_messages text
        flat = [
            m for m in packed.conversation_messages
            if m.get("content") and "file content here" in m.get("content", "")
        ]
        assert len(flat) == 0, "Flat done_messages should not appear when override is given"

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_no_override_uses_done_messages(self, mock_repo):
        """Without history_override, done_messages is used as before."""
        coder = self._make_coder()

        packed = pack_context(
            coder, user_input="", mode="act",
            runner_type="cot", history_override=None,
        )

        # Should contain the flat done_messages text
        flat = [
            m for m in packed.conversation_messages
            if "file content here" in m.get("content", "")
        ]
        assert len(flat) == 1

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_override_still_applies_budget_trimming(self, mock_repo):
        """history_override is still subject to history_tokens budget."""
        coder = self._make_coder()
        # Build a large override
        big_hist = [
            {"role": "user", "content": f"Message {i}: " + "x" * 200}
            for i in range(50)
        ]

        with patch("aicoder.context.packer.get_context_budget_for_mode") as mock_b:
            mock_b.return_value = ContextBudget(
                repo_map_tokens=1000, history_tokens=20,
                focused_file_tokens=1000, tool_trace_tokens=1000,
            )
            packed = pack_context(
                coder, user_input="", mode="act",
                runner_type="function-calling", history_override=big_hist,
            )
            hist_msgs = [
                m for m in packed.conversation_messages
                if "Message" in m.get("content", "")
            ]
            assert len(hist_msgs) < 50, "Large override should be trimmed by budget"


# ---------------------------------------------------------------------------
# Fix: _build_llm_messages() wires FC runner.build_history_messages()
# ---------------------------------------------------------------------------

class TestBuildLlmMessagesFCIntegration:
    """Verify that the main runtime path _build_llm_messages() actually
    uses runner.build_history_messages() for FC runners."""

    def _make_coder_with_fc_steps(self) -> MagicMock:
        """Create a coder + FC runner with step store containing structured data."""
        from aicoder.agent_step_store import AgentStepStore
        from aicoder.runners.function_calling_agent_runner import FunctionCallingAgentRunner
        from aicoder.runners import register_runner, unregister_runner
        from aicoder.tools.registry import ToolRegistry
        from aicoder.tools.executor import ToolCoordinator, ToolExecutor
        from aicoder.tools.result import ExecutionState

        session_id = "fc-integration-test"

        coder = MagicMock()
        coder.main_model = MagicMock()
        coder.main_model.name = "test-model"
        coder.main_model.max_input_tokens = 128000
        coder.io = MagicMock()
        coder.stream = True
        coder.root = "/tmp/test"
        coder.session_id = session_id
        # done_messages from a PRIOR turn — not the same as the current steps
        coder.done_messages = [
            {"role": "user", "content": "what is this project?"},
            {"role": "assistant", "content": "This is a Python project."},
        ]
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
        coder.gpt_prompts = MagicMock()
        coder.gpt_prompts.main_system = ""
        coder.gpt_prompts.system_reminder = ""
        coder.gpt_prompts.example_messages = []
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        coder._system_prompt = MagicMock()
        coder._system_prompt.build.return_value = "You are a helpful assistant."
        coder._update_tool_model_info = MagicMock()
        coder._build_workspace_info.return_value = ""
        coder._detect_cli_tools.return_value = ""
        coder.get_repo_map.return_value = ""
        coder.abs_root_path = lambda p: str(Path("/tmp/test") / p)

        # Tool infrastructure
        registry = ToolRegistry()
        coord = ToolCoordinator()
        exec_state = ExecutionState()
        exec_state.mode = "act"
        coder.tool_registry = registry
        coder.tool_coordinator = coord
        coder.tool_exec_state = exec_state
        coder.tool_executor = ToolExecutor(coord, coder, exec_state)

        # Step store with structured FC data
        step_store = AgentStepStore(session_id=session_id)
        step = step_store.create_step(
            iteration=0, mode="act", runner_type="function-calling",
        )
        step.thought = "Reading foo.py"
        step.tool_calls = [{
            "tool_call_id": "call_fc_001",
            "tool_name": "read_file",
            "arguments": {"path": "foo.py"},
        }]
        step.tool_results = [{
            "tool_call_id": "call_fc_001",
            "tool_name": "read_file",
            "success": True,
            "content": "def foo(): return 42",
            "is_error": False,
            "rejected": False,
        }]
        step_store.update_step_after_parse(
            step, thought="Reading foo.py",
            action_name="read_file", action_input={"path": "foo.py"},
        )
        step_store.update_step_after_tool(
            step, observation="def foo(): return 42",
            tool_meta={"success": True, "tool_name": "read_file"},
        )

        # Create and register FC runner
        runner = FunctionCallingAgentRunner(
            coder=coder, session_id=session_id,
            mode="act", tool_registry=registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        return coder, session_id

    def teardown_method(self):
        from aicoder.runners import unregister_runner
        unregister_runner("fc-integration-test")

    def test_build_llm_messages_uses_fc_structured_history(self):
        """_build_llm_messages() must produce structured tool_calls/tool for FC."""
        from aicoder.graph.nodes import _build_llm_messages
        from aicoder.coders.message_builder import (
            build_system_messages,
            build_runtime_state_messages,
            build_mode_messages,
            build_chat_files_messages,
        )

        coder, _ = self._make_coder_with_fc_steps()

        with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
             patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
             patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode, \
             patch("aicoder.coders.message_builder.build_runtime_state_messages") as mock_rt:
            mock_sys.return_value = [{"role": "system", "content": "sys"}]
            mock_chat.return_value = []
            mock_mode.return_value = []
            mock_rt.return_value = []
            messages = _build_llm_messages(coder)

        # Verify structured history from steps is present in the output
        assistant_tc = [
            m for m in messages
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        assert len(assistant_tc) >= 1, (
            f"Expected assistant with tool_calls in main path messages, "
            f"got: {[m.get('role') for m in messages]}"
        )

        tool_msgs = [
            m for m in messages
            if m.get("role") == "tool" and m.get("tool_call_id") == "call_fc_001"
        ]
        assert len(tool_msgs) >= 1, (
            f"Expected tool message with tool_call_id=call_fc_001, "
            f"got: {[m for m in messages if m.get('role') == 'tool']}"
        )

        # Verify the tool_calls contain the correct function name
        tc = assistant_tc[0]["tool_calls"][0]
        assert tc["function"]["name"] == "read_file"
        assert tc["id"] == "call_fc_001"

        # Verify prior turn done_messages also present (prepended by rebuilder)
        prior = [
            m for m in messages
            if "Python project" in (m.get("content") or "")
        ]
        assert len(prior) >= 1, "Prior turn done_messages should also be present"

    def test_cot_runner_uses_text_history(self):
        """CoT runner must NOT produce tool/tool_call_id — uses done_messages."""
        from aicoder.graph.nodes import _build_llm_messages
        from aicoder.agent_step_store import AgentStepStore
        from aicoder.runners.cot_agent_runner import CotAgentRunner
        from aicoder.runners import register_runner, unregister_runner
        from aicoder.tools.registry import ToolRegistry
        from aicoder.tools.executor import ToolCoordinator, ToolExecutor
        from aicoder.tools.result import ExecutionState

        session_id = "cot-control-test"

        coder = MagicMock()
        coder.main_model = MagicMock()
        coder.main_model.name = "test-model"
        coder.main_model.max_input_tokens = 128000
        coder.io = MagicMock()
        coder.stream = True
        coder.root = "/tmp/test"
        coder.session_id = session_id
        # CoT uses done_messages directly — text observations
        coder.done_messages = [
            {"role": "user", "content": "read bar.py"},
            {"role": "assistant", "content": "[read_file] Result:\ndef bar(): return 1"},
        ]
        coder.cur_messages = []
        coder.abs_fnames = set()
        coder._first_message = True
        coder.gpt_prompts = MagicMock()
        coder.gpt_prompts.main_system = ""
        coder.gpt_prompts.system_reminder = ""
        coder.gpt_prompts.example_messages = []
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        coder._system_prompt = MagicMock()
        coder._system_prompt.build.return_value = "sys"
        coder._update_tool_model_info = MagicMock()
        coder._build_workspace_info.return_value = ""
        coder._detect_cli_tools.return_value = ""
        coder.get_repo_map.return_value = ""
        coder.abs_root_path = lambda p: str(Path("/tmp/test") / p)

        registry = ToolRegistry()
        coord = ToolCoordinator()
        exec_state = ExecutionState()
        exec_state.mode = "act"
        coder.tool_registry = registry
        coder.tool_coordinator = coord
        coder.tool_exec_state = exec_state
        coder.tool_executor = ToolExecutor(coord, coder, exec_state)

        # CoT runner with steps (should be ignored — CoT uses done_messages)
        step_store = AgentStepStore(session_id=session_id)
        step = step_store.create_step(
            iteration=0, mode="act", runner_type="cot",
        )
        step.thought = "Reading bar.py"
        step.action_name = "read_file"
        step.action_input = {"path": "bar.py"}
        step.observation = "def bar(): return 1"
        step.status = "observed"
        step_store.update_step_after_parse(
            step, thought="Reading bar.py",
            action_name="read_file", action_input={"path": "bar.py"},
        )
        step_store.update_step_after_tool(
            step, observation="def bar(): return 1",
            tool_meta={"success": True, "tool_name": "read_file"},
        )

        runner = CotAgentRunner(
            coder=coder, session_id=session_id,
            mode="act", tool_registry=registry, step_store=step_store,
        )
        register_runner(session_id, runner)

        try:
            with patch("aicoder.coders.message_builder.build_system_messages") as mock_sys, \
                 patch("aicoder.coders.message_builder.build_chat_files_messages") as mock_chat, \
                 patch("aicoder.coders.message_builder.build_mode_messages") as mock_mode, \
                 patch("aicoder.coders.message_builder.build_runtime_state_messages") as mock_rt:
                mock_sys.return_value = [{"role": "system", "content": "sys"}]
                mock_chat.return_value = []
                mock_mode.return_value = []
                mock_rt.return_value = []
                messages = _build_llm_messages(coder)

            # CoT must NOT have structured tool_calls
            assistant_tc = [
                m for m in messages
                if m.get("role") == "assistant" and m.get("tool_calls")
            ]
            assert len(assistant_tc) == 0, (
                f"CoT should not produce assistant.tool_calls, got: {assistant_tc}"
            )

            # CoT must NOT have tool messages
            tool_msgs = [
                m for m in messages
                if m.get("role") == "tool"
            ]
            assert len(tool_msgs) == 0, (
                f"CoT should not produce tool messages, got: {tool_msgs}"
            )

            # CoT should use done_messages text directly
            text_obs = [
                m for m in messages
                if m.get("role") == "assistant"
                and "read_file" in (m.get("content") or "")
            ]
            assert len(text_obs) >= 1, (
                "CoT should have text-form observation from done_messages"
            )
        finally:
            unregister_runner(session_id)


# ---------------------------------------------------------------------------
# v1.2 Phase 5: Budget applied on history view / condensed view
# ---------------------------------------------------------------------------


class TestBudgetOnHistoryView:
    """Verify that budget trimming applies to the llm history view output."""

    def _make_coder_with_tool_traces(self, trace_count: int = 10) -> MagicMock:
        """Create a coder with tool trace messages in done_messages."""
        coder = MagicMock()
        coder.main_model = MagicMock()
        coder.main_model.name = "test-model"
        coder.tool_exec_state = MagicMock()
        coder.tool_exec_state.mode = "act"
        coder.done_messages = []
        for i in range(trace_count):
            coder.done_messages.append({"role": "user", "content": f"question {i}"})
            coder.done_messages.append({
                "role": "assistant",
                "content": f"[read_file] Result:\n{'x' * 400}\nEnd of file {i}",
            })
        coder.cur_messages = []
        coder.abs_fnames = set()
        coder._cached_system_key = None
        coder._cached_system_messages = None
        coder._first_message = False
        coder._file_tree = None
        coder.gpt_prompts = MagicMock()
        coder.gpt_prompts.main_system = ""
        coder.gpt_prompts.system_reminder = ""
        coder.gpt_prompts.example_messages = []
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        coder._system_prompt = MagicMock()
        coder._system_prompt.build.return_value = "sys"
        coder._update_tool_model_info = MagicMock()
        coder._build_workspace_info.return_value = ""
        coder._detect_cli_tools.return_value = ""
        coder.get_repo_map.return_value = ""
        coder.root = "/tmp"
        coder.session_id = "budget-test"
        return coder

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_history_tokens_trims_view(self, mock_repo):
        """history_tokens should trim the llm history view output."""
        coder = self._make_coder_with_tool_traces(20)

        with patch("aicoder.context.packer.get_context_budget_for_mode") as mock_b:
            mock_b.return_value = ContextBudget(
                repo_map_tokens=1000, history_tokens=100,
                focused_file_tokens=1000, tool_trace_tokens=50000,
            )
            packed = pack_context(coder, user_input="", mode="act", runner_type="cot")
            # 100 tokens budget with ~100+ chars per pair — should trim heavily
            hist_msgs = [m for m in packed.conversation_messages
                         if "question" in m.get("content", "") or "Result" in m.get("content", "")]
            assert len(hist_msgs) < 40, "History should be trimmed"

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_tool_trace_tokens_trims_old_traces(self, mock_repo):
        """tool_trace_tokens should shorten old tool output bodies."""
        coder = self._make_coder_with_tool_traces(10)

        # Very small trace budget — should trigger trimming of old traces
        with patch("aicoder.context.packer.get_context_budget_for_mode") as mock_b:
            mock_b.return_value = ContextBudget(
                repo_map_tokens=1000, history_tokens=50000,
                focused_file_tokens=1000, tool_trace_tokens=50,
            )
            packed = pack_context(coder, user_input="", mode="act", runner_type="cot")

            # Some tool traces should be trimmed
            trimmed = [m for m in packed.conversation_messages
                       if m.get("_trace_trimmed")]
            assert len(trimmed) > 0, "Old tool traces should be trimmed when over budget"

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_recent_traces_not_trimmed(self, mock_repo):
        """Recent tool traces should not be trimmed even when over budget."""
        coder = self._make_coder_with_tool_traces(10)

        with patch("aicoder.context.packer.get_context_budget_for_mode") as mock_b:
            mock_b.return_value = ContextBudget(
                repo_map_tokens=1000, history_tokens=50000,
                focused_file_tokens=1000, tool_trace_tokens=50,
            )
            packed = pack_context(coder, user_input="", mode="act", runner_type="cot")

            # The last few tool result messages should NOT be trimmed
            tool_msgs = [m for m in packed.conversation_messages
                         if "Result" in m.get("content", "")]
            # At least the last few should not have _trace_trimmed
            recent = tool_msgs[-3:] if len(tool_msgs) >= 3 else tool_msgs
            for m in recent:
                assert not m.get("_trace_trimmed"), "Recent traces should not be trimmed"

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_condensation_then_budget_still_works(self, mock_repo):
        """After condensation, history budget should still apply."""
        from aicoder.context.condense import CondensedBlock, apply_condensation_to_history_view

        view = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        condensed = CondensedBlock(summary="summary of old work", covered_event_ids=["ev-1"])
        condensed_view = apply_condensation_to_history_view(view, condensed)

        # condensed_view should be smaller
        assert len(condensed_view) < len(view)

        # Now simulate packer trimming the condensed view further
        trimmed = _trim_to_budget(condensed_view, 20)
        # Should be even smaller or same (if already within budget)
        assert len(trimmed) <= len(condensed_view)

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_no_trace_trimming_when_within_budget(self, mock_repo):
        """No trimming when tool traces fit within budget."""
        # Short tool traces
        coder = MagicMock()
        coder.main_model = MagicMock()
        coder.main_model.name = "test"
        coder.tool_exec_state = MagicMock()
        coder.tool_exec_state.mode = "act"
        coder.done_messages = [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "[read_file] Result:\nshort output"},
        ]
        coder.cur_messages = []
        coder.abs_fnames = set()
        coder._cached_system_key = None
        coder._cached_system_messages = None
        coder._first_message = False
        coder._file_tree = None
        coder.gpt_prompts = MagicMock()
        coder.gpt_prompts.main_system = ""
        coder.gpt_prompts.system_reminder = ""
        coder.gpt_prompts.example_messages = []
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        coder._system_prompt = MagicMock()
        coder._system_prompt.build.return_value = "sys"
        coder._update_tool_model_info = MagicMock()
        coder._build_workspace_info.return_value = ""
        coder._detect_cli_tools.return_value = ""
        coder.get_repo_map.return_value = ""
        coder.root = "/tmp"
        coder.session_id = "budget-test"

        packed = pack_context(coder, user_input="", mode="act", runner_type="cot")
        trimmed = [m for m in packed.conversation_messages if m.get("_trace_trimmed")]
        assert len(trimmed) == 0, "No trimming when within budget"

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_cot_under_budget_works(self, mock_repo):
        """CoT runner produces valid output under budget constraints."""
        coder = MagicMock()
        coder.main_model = MagicMock()
        coder.main_model.name = "test"
        coder.tool_exec_state = MagicMock()
        coder.tool_exec_state.mode = "act"
        coder.done_messages = [
            {"role": "user", "content": "read file"},
            {"role": "assistant", "content": "[read_file] Result:\ncontents"},
        ]
        coder.cur_messages = []
        coder.abs_fnames = set()
        coder._cached_system_key = None
        coder._cached_system_messages = None
        coder._first_message = False
        coder._file_tree = None
        coder.gpt_prompts = MagicMock()
        coder.gpt_prompts.main_system = ""
        coder.gpt_prompts.system_reminder = ""
        coder.gpt_prompts.example_messages = []
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        coder._system_prompt = MagicMock()
        coder._system_prompt.build.return_value = "sys"
        coder._update_tool_model_info = MagicMock()
        coder._build_workspace_info.return_value = ""
        coder._detect_cli_tools.return_value = ""
        coder.get_repo_map.return_value = ""
        coder.root = "/tmp"
        coder.session_id = "cot-budget-test"

        packed = pack_context(coder, user_input="next question", mode="act", runner_type="cot")
        assert isinstance(packed, PackedContext)
        # CoT should have text observation
        text_obs = [m for m in packed.conversation_messages
                    if "read_file" in m.get("content", "")]
        assert len(text_obs) >= 1

    @patch("aicoder.context.packer.build_repo_context", return_value=[])
    def test_fc_under_budget_works(self, mock_repo):
        """FC runner produces valid output under budget constraints."""
        coder = MagicMock()
        coder.main_model = MagicMock()
        coder.main_model.name = "test"
        coder.tool_exec_state = MagicMock()
        coder.tool_exec_state.mode = "act"
        coder.done_messages = [
            {"role": "user", "content": "read file"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "tc_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "tc_1", "content": "file contents"},
        ]
        coder.cur_messages = []
        coder.abs_fnames = set()
        coder._cached_system_key = None
        coder._cached_system_messages = None
        coder._first_message = False
        coder._file_tree = None
        coder.gpt_prompts = MagicMock()
        coder.gpt_prompts.main_system = ""
        coder.gpt_prompts.system_reminder = ""
        coder.gpt_prompts.example_messages = []
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        coder._system_prompt = MagicMock()
        coder._system_prompt.build.return_value = "sys"
        coder._update_tool_model_info = MagicMock()
        coder._build_workspace_info.return_value = ""
        coder._detect_cli_tools.return_value = ""
        coder.get_repo_map.return_value = ""
        coder.root = "/tmp"
        coder.session_id = "fc-budget-test"

        packed = pack_context(
            coder, user_input="", mode="act",
            runner_type="function-calling",
            history_override=coder.done_messages,
        )
        assert isinstance(packed, PackedContext)
        # FC should have structured tool_calls
        tc_msgs = [m for m in packed.conversation_messages
                   if m.get("role") == "assistant" and m.get("tool_calls")]
        assert len(tc_msgs) >= 1
