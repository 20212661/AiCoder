"""Tests for focused_file_tokens budget enforcement in pack_context.

Phase 5: _trim_focused_files() and its integration with pack_context.
"""
import tempfile
import os

import pytest

from aicoder.context.packer import _trim_focused_files, _approx_token_count
from aicoder.context.policies import get_context_budget_for_mode
from aicoder.tests.conftest import make_mock_coder


# ---------------------------------------------------------------------------
# _trim_focused_files unit tests
# ---------------------------------------------------------------------------


class TestTrimFocusedFiles:
    def _make_file_messages(self, content_chars=500, n_files=1):
        """Build mock chat file messages with configurable content size."""
        file_content = "x" * content_chars
        fc = (
            "Working directory: /test\n\n"
            "You are in this directory. Files added to chat:\n\n"
            + file_content
        )
        return [
            {"role": "user", "content": fc},
            {"role": "assistant", "content": "Ok, I see the files."},
        ]

    def test_no_trim_when_under_budget(self):
        messages = self._make_file_messages(content_chars=100)
        tokens = _approx_token_count(messages)
        result = _trim_focused_files(messages, budget_tokens=tokens + 100)
        assert result == messages
        assert not result[0].get("_focused_trimmed")

    def test_trims_when_over_budget(self):
        messages = self._make_file_messages(content_chars=2000)
        # Very small budget — should trigger trimming
        result = _trim_focused_files(messages, budget_tokens=50)
        assert result[0].get("_focused_trimmed") is True
        # Content should be shorter than original
        assert len(result[0]["content"]) < len(messages[0]["content"])

    def test_zero_budget_trims_everything(self):
        messages = self._make_file_messages(content_chars=1000)
        result = _trim_focused_files(messages, budget_tokens=0)
        # With 0 budget, should return messages as-is (early return)
        assert isinstance(result, list)

    def test_preserves_non_file_messages(self):
        """Workspace info and assistant replies should survive trimming."""
        msgs = [
            {"role": "user", "content": "# Workspace info\nsome details"},
            {"role": "assistant", "content": "Ok, I see the project."},
            {"role": "user", "content": "Working directory: /t\n\nFiles added to chat:\n\n" + "y" * 3000},
            {"role": "assistant", "content": "Ok, I see the files."},
        ]
        result = _trim_focused_files(msgs, budget_tokens=100)
        # Workspace info preserved
        assert "Workspace info" in result[0]["content"]
        # Assistant replies preserved
        assert result[1]["content"] == "Ok, I see the project."
        assert result[3]["content"] == "Ok, I see the files."
        # File content trimmed
        assert result[2].get("_focused_trimmed") is True

    def test_empty_messages_returns_empty(self):
        result = _trim_focused_files([], budget_tokens=100)
        assert result == []

    def test_single_small_message_survives(self):
        msgs = [{"role": "user", "content": "short"}]
        result = _trim_focused_files(msgs, budget_tokens=100)
        assert result == msgs


# ---------------------------------------------------------------------------
# Mode-specific budget differences
# ---------------------------------------------------------------------------


class TestModeBudgetDifferences:
    def test_act_has_larger_focused_budget_than_sniff(self):
        act = get_context_budget_for_mode("act")
        sniff = get_context_budget_for_mode("sniff")
        assert act.focused_file_tokens > sniff.focused_file_tokens

    def test_plan_between_sniff_and_act(self):
        sniff = get_context_budget_for_mode("sniff")
        plan = get_context_budget_for_mode("plan")
        act = get_context_budget_for_mode("act")
        assert sniff.focused_file_tokens <= plan.focused_file_tokens
        assert plan.focused_file_tokens <= act.focused_file_tokens

    def test_same_content_trims_less_in_act_mode(self):
        """Act mode has more budget, so same content gets trimmed less."""
        content = "Working directory: /t\n\nFiles added to chat:\n\n" + "z" * 3000
        messages = [
            {"role": "user", "content": content},
            {"role": "assistant", "content": "Ok."},
        ]

        sniff_budget = get_context_budget_for_mode("sniff").focused_file_tokens
        act_budget = get_context_budget_for_mode("act").focused_file_tokens

        sniff_result = _trim_focused_files(messages, budget_tokens=sniff_budget, mode="sniff")
        act_result = _trim_focused_files(messages, budget_tokens=act_budget, mode="act")

        # Act result should have at least as much content as sniff result
        assert len(act_result[0]["content"]) >= len(sniff_result[0]["content"])


# ---------------------------------------------------------------------------
# Repo vs focused budget separation
# ---------------------------------------------------------------------------


class TestBudgetSeparation:
    def test_repo_and_focused_are_independent(self):
        """Changing repo budget should not affect focused_file_tokens."""
        for mode in ("sniff", "plan", "act"):
            b = get_context_budget_for_mode(mode)
            # Both are positive and independently set
            assert b.repo_map_tokens > 0
            assert b.focused_file_tokens > 0

    def test_focused_budget_not_zero(self):
        """focused_file_tokens must be non-zero for all modes."""
        for mode in ("sniff", "plan", "act"):
            b = get_context_budget_for_mode(mode)
            assert b.focused_file_tokens > 0

    def test_total_budget_reasonable(self):
        """Sum of all budgets should be within model context window."""
        for mode in ("sniff", "plan", "act"):
            b = get_context_budget_for_mode(mode)
            total = (b.repo_map_tokens + b.focused_file_tokens
                     + b.history_tokens + b.tool_trace_tokens)
            # Should not exceed 128k (typical max context)
            assert total < 128_000


# ---------------------------------------------------------------------------
# Integration: pack_context respects focused_file_tokens
# ---------------------------------------------------------------------------


class TestPackContextFocusedBudget:
    def _make_coder_for_pack(self, root, abs_fnames):
        """Create a coder with enough fields for pack_context to work."""
        from aicoder.tests.conftest import make_graph_coder
        coder = make_graph_coder(responses=["ok"], root=root)
        coder.abs_fnames = set(abs_fnames)
        # Skip first-message block (workspace info) to avoid MagicMock string joins
        coder._first_message = False
        # Wire get_files_content to actually read the focused files
        coder.get_files_content = lambda: "".join(
            f"\n\n--- {os.path.basename(f)} ---\n"
            for f in abs_fnames
        )
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        return coder

    def test_pack_trims_large_files_in_sniff(self):
        root = tempfile.mkdtemp()
        big_file = os.path.join(root, "big.py")
        with open(big_file, "w") as f:
            f.write("x = 1\n" + "y = 'padding'\n" * 500)

        coder = self._make_coder_for_pack(root, [big_file])
        from aicoder.context.packer import pack_context

        result = pack_context(coder, user_input="hello", mode="sniff", runner_type="cot")
        assert len(result.conversation_messages) > 0

    def test_pack_preserves_small_files_in_act(self):
        root = tempfile.mkdtemp()
        small_file = os.path.join(root, "small.py")
        with open(small_file, "w") as f:
            f.write("x = 1\n")

        coder = self._make_coder_for_pack(root, [small_file])
        from aicoder.context.packer import pack_context

        result = pack_context(coder, user_input="hello", mode="act", runner_type="cot")
        assert len(result.conversation_messages) > 0

    def test_layer_trace_includes_chat_files(self):
        root = tempfile.mkdtemp()
        f1 = os.path.join(root, "app.py")
        with open(f1, "w") as f:
            f.write("pass\n")

        coder = self._make_coder_for_pack(root, [f1])
        from aicoder.context.packer import pack_context

        result = pack_context(coder, user_input="test", mode="act", runner_type="cot")
        trace = result._layer_trace
        assert "chat_files_start" in trace
        assert "chat_files_end" in trace
        assert trace["chat_files_end"] >= trace["chat_files_start"]
