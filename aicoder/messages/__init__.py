"""Message types and conversion layer."""
from .types import (
    AssistantText,
    StoredItem,
    ToolCallRecord,
    ToolResultRecord,
    UserText,
)
from .conversion import (
    build_llm_messages_for_fc,
    build_llm_messages_for_cot,
)

__all__ = [
    "AssistantText",
    "UserText",
    "ToolCallRecord",
    "ToolResultRecord",
    "StoredItem",
    "build_llm_messages_for_fc",
    "build_llm_messages_for_cot",
]
