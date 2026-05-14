"""AgentHistoryRebuilder — reconstruct prompt history from done_messages + steps.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §9.3

Replaces the current approach of directly using ``done_messages + cur_messages``
with a step-aware reconstruction that preserves complete iteration boundaries.

v1.1: FC path now delegates to the unified message conversion layer.
"""
from __future__ import annotations

from typing import Any

from aicoder.agent_step_store import AgentStep
from aicoder.messages.types import (
    AssistantText,
    ToolCallRecord,
    ToolResultRecord,
)
from aicoder.messages.conversion import (
    build_llm_messages_for_fc,
    build_llm_messages_for_cot,
)


def _step_to_stored_items(step: AgentStep) -> list:
    """Convert a single AgentStep into StoredItem records.

    For FC steps that have structured tool_calls/tool_results data,
    prefer those over the legacy action_name/observation fields.
    """
    items = []

    if step.status == "created":
        return items

    if step.status == "final" and step.final_answer:
        items.append(AssistantText(content=step.final_answer))
        return items

    # Thought as assistant text
    if step.thought:
        items.append(AssistantText(content=step.thought))

    # FC structured path: use step.tool_calls and step.tool_results
    if step.tool_calls:
        for tc_rec in step.tool_calls:
            items.append(ToolCallRecord(
                tool_call_id=tc_rec.get("tool_call_id", step.id),
                tool_name=tc_rec.get("tool_name", "unknown"),
                arguments=tc_rec.get("arguments", {}),
            ))
        for tr_rec in step.tool_results:
            items.append(ToolResultRecord(
                tool_call_id=tr_rec.get("tool_call_id", step.id),
                tool_name=tr_rec.get("tool_name", "unknown"),
                success=tr_rec.get("success", True),
                content=tr_rec.get("content", ""),
                is_error=tr_rec.get("is_error", False),
                rejected=tr_rec.get("rejected", False),
            ))
        return items

    # Legacy / CoT path: use action_name and observation
    if step.action_name and step.status in ("parsed", "observed", "error"):
        action_input = step.action_input if isinstance(step.action_input, dict) else {}
        tool_call_id = step.id
        items.append(ToolCallRecord(
            tool_call_id=tool_call_id,
            tool_name=step.action_name,
            arguments=action_input,
        ))

    # Tool result (legacy)
    if step.status == "observed":
        meta = step.tool_meta or {}
        if meta.get("rejected"):
            items.append(ToolResultRecord(
                tool_call_id=step.id,
                tool_name=step.action_name or "unknown",
                success=False,
                content="User rejected the tool call.",
                is_error=False,
                rejected=True,
            ))
        elif meta.get("success") is False:
            items.append(ToolResultRecord(
                tool_call_id=step.id,
                tool_name=step.action_name or "unknown",
                success=False,
                content=f"FAILED: {step.observation or ''}",
                is_error=True,
            ))
        elif step.observation:
            items.append(ToolResultRecord(
                tool_call_id=step.id,
                tool_name=step.action_name or "unknown",
                success=True,
                content=step.observation,
                is_error=False,
            ))
    elif step.status == "error" and step.error:
        items.append(ToolResultRecord(
            tool_call_id=step.id,
            tool_name=step.action_name or "unknown",
            success=False,
            content=f"Error: {step.error}",
            is_error=True,
        ))

    return items


class AgentHistoryRebuilder:
    """Reconstruct LLM message history from persisted messages and step records."""

    @staticmethod
    def build_for_cot(
        done_messages: list[dict[str, Any]],
        steps: list[AgentStep],
    ) -> list[dict[str, Any]]:
        """Build scratchpad-style message history for CoT runner.

        Uses the unified conversion layer for consistency.
        """
        items: list = []
        for step in steps:
            items.extend(_step_to_stored_items(step))

        messages = list(done_messages)
        messages.extend(build_llm_messages_for_cot(items))
        return messages

    @staticmethod
    def build_for_fc(
        done_messages: list[dict[str, Any]],
        steps: list[AgentStep],
    ) -> list[dict[str, Any]]:
        """Build assistant/tool message-pair history for Function Calling runner.

        Uses the unified conversion layer to preserve structured tool_calls
        and tool messages with tool_call_id.
        """
        items: list = []
        for step in steps:
            items.extend(_step_to_stored_items(step))

        messages = list(done_messages)
        messages.extend(build_llm_messages_for_fc(items))
        return messages
