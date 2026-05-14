"""AgentHistoryTruncator — token-budget truncation by complete iterations.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §9.4-9.5

Key principle: never cut in the middle of an iteration (thought+action+observation).
Always drop or keep complete iteration groups.

Strategy (borrowed from Dify, adapted for AiCoder):
1. System messages are always preserved.
2. Keep iterations from most-recent backwards.
3. Add one complete iteration at a time.
4. If adding an iteration would exceed the budget, drop it entirely.
"""

from __future__ import annotations

from typing import Any, Callable


class AgentHistoryTruncator:
    """Truncate message history by complete iteration boundaries."""

    @staticmethod
    def truncate(
        messages: list[dict[str, Any]],
        max_tokens: int,
        token_fn: Callable[[list[dict[str, Any]]], int],
    ) -> list[dict[str, Any]]:
        """Truncate messages to fit within max_tokens, preserving complete iterations.

        Args:
            messages: Full message list (system + conversation).
            max_tokens: Token budget.
            token_fn: Function that counts tokens for a message list.

        Returns:
            Truncated message list that fits within budget.
        """
        if not messages:
            return messages

        try:
            if token_fn(messages) <= max_tokens:
                return messages
        except Exception:
            return messages

        # Step 1: Separate system messages from conversation messages
        system_msgs, conv_msgs = _split_system_and_conversation(messages)

        # If even system messages exceed budget, return them as-is
        if system_msgs:
            try:
                if token_fn(system_msgs) >= max_tokens:
                    return system_msgs
            except Exception:
                return system_msgs

        # Step 2: Group conversation messages into iterations
        iterations = _group_into_iterations(conv_msgs)

        # Step 3: Keep iterations from most-recent backwards
        kept: list[list[dict[str, Any]]] = []
        budget_remaining = max_tokens

        try:
            budget_remaining -= token_fn(system_msgs)
        except Exception:
            budget_remaining = max_tokens

        for iteration in reversed(iterations):
            try:
                iter_tokens = token_fn(iteration)
            except Exception:
                continue

            if iter_tokens > budget_remaining:
                break

            kept.insert(0, iteration)
            budget_remaining -= iter_tokens

        result = list(system_msgs)
        for iteration in kept:
            result.extend(iteration)

        # Ensure result doesn't exceed budget (safety check)
        try:
            if token_fn(result) > max_tokens and len(result) > len(system_msgs) + 2:
                # Drop oldest iteration as last resort
                result = list(system_msgs) + result[len(system_msgs) + _first_iteration_len(result[len(system_msgs):]):]
        except Exception:
            pass

        return result


def _split_system_and_conversation(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split messages into system prefix and conversation body."""
    system_end = 0
    for i, m in enumerate(messages):
        if m.get("role") == "system":
            system_end = i + 1
        else:
            break

    return messages[:system_end], messages[system_end:]


def _group_into_iterations(
    messages: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group conversation messages into complete iterations.

    An iteration is one complete thought-action-observation cycle:
    - CoT: [user?] [assistant] [user/tool-result]
    - FC:  [assistant with tool_calls] [tool result]

    We use a simple heuristic: group from one user/tool message to the next,
    or treat each assistant message as a potential iteration boundary.
    """
    if not messages:
        return []

    iterations: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")

        # A new iteration starts at each user message that follows an assistant message,
        # or at each tool message that follows a tool message from a different call.
        if (
            role == "user"
            and current
            and any(m.get("role") == "assistant" for m in current)
        ):
            iterations.append(current)
            current = [msg]
            continue

        # Tool messages following a tool message from a different tool_call_id
        # belong to the same iteration (parallel tool calls).
        if role == "tool" and current and current[-1].get("role") == "tool":
            current.append(msg)
            continue

        current.append(msg)

    if current:
        iterations.append(current)

    return iterations


def _first_iteration_len(messages: list[dict[str, Any]]) -> int:
    """Find the length of the first iteration group in messages."""
    iterations = _group_into_iterations(messages)
    if iterations:
        return len(iterations[0])
    return len(messages)
