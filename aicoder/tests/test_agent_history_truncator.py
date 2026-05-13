"""Tests for AgentHistoryTruncator."""

import pytest

from aicoder.agent_history_truncator import AgentHistoryTruncator, _group_into_iterations


def _char_token_fn(messages):
    """Simple char-based token counter for testing."""
    total = 0
    for m in messages:
        total += len(str(m.get("content", "")))
    return total


def _msg(role, content, **extra):
    msg = {"role": role, "content": content}
    msg.update(extra)
    return msg


class TestGroupIntoIterations:
    def test_empty(self):
        assert _group_into_iterations([]) == []

    def test_single_message(self):
        msgs = [_msg("user", "hello")]
        groups = _group_into_iterations(msgs)
        assert len(groups) == 1

    def test_conversation_pairs(self):
        msgs = [
            _msg("user", "question 1"),
            _msg("assistant", "answer 1"),
            _msg("user", "question 2"),
            _msg("assistant", "answer 2"),
        ]
        groups = _group_into_iterations(msgs)
        assert len(groups) == 2

    def test_tool_result_pairs(self):
        msgs = [
            _msg("assistant", "thinking..."),
            _msg("user", "[tool] Result: file contents"),
            _msg("assistant", "more thinking..."),
            _msg("user", "[tool] Result: more contents"),
        ]
        groups = _group_into_iterations(msgs)
        # Groups: [assistant], [user+assistant], [user] — iteration boundaries
        # split at user messages that follow assistant messages
        assert len(groups) >= 1
        # All messages are preserved
        total = sum(len(g) for g in groups)
        assert total == 4

    def test_parallel_tool_messages(self):
        msgs = [
            _msg("assistant", "calling tools"),
            _msg("tool", "result 1", tool_call_id="t1"),
            _msg("tool", "result 2", tool_call_id="t2"),
        ]
        groups = _group_into_iterations(msgs)
        assert len(groups) == 1
        assert len(groups[0]) == 3


class TestAgentHistoryTruncator:
    def test_no_truncation_needed(self):
        msgs = [
            _msg("system", "you are helpful"),
            _msg("user", "hi"),
            _msg("assistant", "hello"),
        ]
        result = AgentHistoryTruncator.truncate(msgs, max_tokens=10000, token_fn=_char_token_fn)
        assert result == msgs

    def test_empty_messages(self):
        result = AgentHistoryTruncator.truncate([], max_tokens=100, token_fn=_char_token_fn)
        assert result == []

    def test_system_messages_preserved(self):
        system = _msg("system", "A" * 10)
        msgs = [
            system,
            _msg("user", "B" * 100),
            _msg("assistant", "C" * 100),
            _msg("user", "D" * 100),
            _msg("assistant", "E" * 100),
        ]
        # Budget only fits system + last iteration
        budget = 10 + 100 + 100 + 10  # system + last pair + margin
        result = AgentHistoryTruncator.truncate(msgs, max_tokens=budget, token_fn=_char_token_fn)
        assert result[0]["role"] == "system"
        assert len(result) >= 1

    def test_drops_oldest_iteration_first(self):
        # Build messages where each iteration is ~50 tokens (chars)
        msgs = [
            _msg("system", "sys"),
            _msg("user", "A" * 50),
            _msg("assistant", "a" * 50),
            _msg("user", "B" * 50),
            _msg("assistant", "b" * 50),
            _msg("user", "C" * 50),
            _msg("assistant", "c" * 50),
        ]
        # Budget fits system + last 2 iterations only
        budget = 3 + 50 + 50 + 50 + 50 + 5
        result = AgentHistoryTruncator.truncate(msgs, max_tokens=budget, token_fn=_char_token_fn)

        assert result[0]["content"] == "sys"
        # Should have kept the most recent iterations
        assert any("B" * 50 in str(m.get("content", "")) for m in result)
        assert any("c" * 50 in str(m.get("content", "")) for m in result)

    def test_keeps_recent_complete_iterations(self):
        msgs = [
            _msg("system", "sys"),
            _msg("user", "old question"),
            _msg("assistant", "old answer"),
            _msg("user", "new question"),
            _msg("assistant", "new answer"),
        ]
        # Budget fits system + only the last iteration
        budget = 3 + 13 + 11 + 5
        result = AgentHistoryTruncator.truncate(msgs, max_tokens=budget, token_fn=_char_token_fn)

        assert result[0]["content"] == "sys"
        # "old" should be dropped
        assert not any("old" in m.get("content", "") for m in result[1:])
        # "new" should be kept
        assert any("new" in m.get("content", "") for m in result)

    def test_single_iteration_fits(self):
        msgs = [
            _msg("system", "sys"),
            _msg("user", "hello"),
            _msg("assistant", "world"),
        ]
        result = AgentHistoryTruncator.truncate(msgs, max_tokens=1000, token_fn=_char_token_fn)
        assert result == msgs

    def test_returns_system_only_when_tight(self):
        system = _msg("system", "short")
        msgs = [
            system,
            _msg("user", "X" * 1000),
            _msg("assistant", "Y" * 1000),
        ]
        result = AgentHistoryTruncator.truncate(msgs, max_tokens=5, token_fn=_char_token_fn)
        # Should at minimum preserve system messages
        assert result[0]["role"] == "system"
