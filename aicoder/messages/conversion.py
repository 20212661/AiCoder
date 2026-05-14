"""Unified conversion from StoredItem -> LLM message dicts.

Two conversion strategies:
- FC (Function Calling): preserves structured tool_calls / tool messages
- CoT (Chain of Thought): textual observation format
"""
from __future__ import annotations

import json
from typing import Any

from .types import (
    AssistantText,
    StoredItem,
    ToolCallRecord,
    ToolResultRecord,
    UserText,
)


# ---------------------------------------------------------------------------
# FC conversion
# ---------------------------------------------------------------------------

def build_llm_messages_for_fc(items: list[StoredItem]) -> list[dict[str, Any]]:
    """Convert StoredItems into OpenAI-compatible FC messages.

    Rules:
    1. AssistantText -> assistant content
    2. ToolCallRecord -> assistant with tool_calls
    3. A ToolCallRecord immediately following an AssistantText merges into
       one assistant message (text + tool_calls).
    4. ToolResultRecord -> tool message with tool_call_id
    5. Tool results are NEVER downgraded to plain user text.
    """
    messages: list[dict[str, Any]] = []
    i = 0

    while i < len(items):
        item = items[i]

        if isinstance(item, UserText):
            messages.append({"role": "user", "content": item.content})
            i += 1

        elif isinstance(item, AssistantText):
            # Look ahead: if next item is ToolCallRecord, merge them
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": item.content or None,
            }
            tool_calls_list: list[dict[str, Any]] = []

            j = i + 1
            while j < len(items) and isinstance(items[j], ToolCallRecord):
                tc = items[j]  # type: ignore[assignment]
                tool_calls_list.append({
                    "id": tc.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": _serialize_args(tc.arguments),
                    },
                })
                j += 1

            if tool_calls_list:
                assistant_msg["tool_calls"] = tool_calls_list
                if not assistant_msg["content"]:
                    assistant_msg["content"] = None
                messages.append(assistant_msg)
                i = j
            else:
                if not item.content:
                    i += 1
                    continue
                messages.append({"role": "assistant", "content": item.content})
                i += 1

        elif isinstance(item, ToolCallRecord):
            # Standalone tool call(s) — group consecutive ToolCallRecords
            tool_calls_list: list[dict[str, Any]] = [{
                "id": item.tool_call_id,
                "type": "function",
                "function": {
                    "name": item.tool_name,
                    "arguments": _serialize_args(item.arguments),
                },
            }]
            thought = item.thought
            j = i + 1
            while j < len(items) and isinstance(items[j], ToolCallRecord):
                tc = items[j]  # type: ignore[assignment]
                tool_calls_list.append({
                    "id": tc.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": _serialize_args(tc.arguments),
                    },
                })
                j += 1
            assistant_msg = {
                "role": "assistant",
                "content": thought or None,
                "tool_calls": tool_calls_list,
            }
            messages.append(assistant_msg)
            i = j

        elif isinstance(item, ToolResultRecord):
            messages.append({
                "role": "tool",
                "tool_call_id": item.tool_call_id,
                "content": item.content,
            })
            i += 1

        else:
            i += 1

    return messages


# ---------------------------------------------------------------------------
# CoT conversion
# ---------------------------------------------------------------------------

def build_llm_messages_for_cot(items: list[StoredItem]) -> list[dict[str, Any]]:
    """Convert StoredItems into textual (CoT) messages.

    Rules:
    1. AssistantText -> assistant text
    2. ToolCallRecord -> assistant text (action description)
    3. ToolResultRecord -> user observation text
    """
    messages: list[dict[str, Any]] = []

    for item in items:
        if isinstance(item, UserText):
            messages.append({"role": "user", "content": item.content})

        elif isinstance(item, AssistantText):
            if item.content:
                messages.append({"role": "assistant", "content": item.content})

        elif isinstance(item, ToolCallRecord):
            desc = item.thought or f"<{item.tool_name}>...</{item.tool_name}>"
            # Merge with previous assistant if possible, else add new
            if messages and messages[-1].get("role") == "assistant":
                prev = messages[-1]["content"] or ""
                messages[-1]["content"] = f"{prev}\n{desc}".strip()
            else:
                messages.append({"role": "assistant", "content": desc})

        elif isinstance(item, ToolResultRecord):
            label = f"[{item.tool_name}]"
            if item.rejected:
                text = f"{label} REJECTED by user."
            elif item.is_error or not item.success:
                text = f"{label} FAILED:\n{item.content}"
            else:
                text = f"{label} Result:\n{item.content}"
            messages.append({"role": "user", "content": text})

    return messages


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_args(args: dict[str, Any]) -> str:
    """Serialize tool arguments to a JSON string."""
    if not args:
        return "{}"
    try:
        return json.dumps(args)
    except (TypeError, ValueError):
        return str(args)
