"""Base types for the parser layer.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §8.3
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from aicoder.tools.registry import ToolRegistry

ParserEventKind = Literal[
    "text",
    "thought",
    "action",
    "final",
    "error",
]


@dataclass
class ParserEvent:
    """Unified output event from any parser."""

    kind: ParserEventKind
    text: str = ""
    action_name: str | None = None
    action_input: dict | str | None = None
    raw: str = ""


class BaseParser(ABC):
    """Abstract base for model output parsers."""

    @abstractmethod
    def parse(self, content: str, registry: ToolRegistry) -> list[ParserEvent]:
        """Parse complete model output into a sequence of events."""
        ...

    @abstractmethod
    def feed(self, chunk: str, registry: ToolRegistry) -> list[ParserEvent]:
        """Feed a streaming chunk. Returns incremental events if available."""
        ...

    @abstractmethod
    def finalize(self) -> list[ParserEvent]:
        """Flush any remaining buffered content and return final events."""
        ...
