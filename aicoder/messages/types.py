"""Intermediate message types for LLM message construction.

These types decouple the execution/storage layer from the specific LLM
message format each runner requires (FC vs CoT).  All downstream code
should convert to StoredItem before passing to the conversion layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AssistantText:
    """Plain text produced by the assistant (thought / final answer)."""
    content: str


@dataclass
class UserText:
    """Plain text input from the user."""
    content: str


@dataclass
class ToolCallRecord:
    """A structured tool call made by the assistant."""
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    thought: str = ""


@dataclass
class ToolResultRecord:
    """The result of executing a tool call."""
    tool_call_id: str
    tool_name: str
    success: bool
    content: str
    is_error: bool = False
    rejected: bool = False


StoredItem = AssistantText | UserText | ToolCallRecord | ToolResultRecord
