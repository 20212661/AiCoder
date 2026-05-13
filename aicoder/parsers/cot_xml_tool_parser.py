"""CoT XML tool-call parser — wraps the existing character-by-character state machine.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §8

This parser wraps ``aicoder.tools.parser.parse_xml_tools`` into the unified
``BaseParser`` interface. XML tool calls are inherently non-incremental (you
don't know a tag is complete until the closing tag arrives), so ``feed()``
buffers chunks and ``finalize()`` performs a single full parse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aicoder.parsers.base import BaseParser, ParserEvent

if TYPE_CHECKING:
    from aicoder.tools.registry import ToolRegistry


class CotXmlToolParser(BaseParser):
    """Wraps the existing XML tool parser into the BaseParser interface."""

    def __init__(self) -> None:
        self._buffer: list[str] = []

    def parse(self, content: str, registry: ToolRegistry) -> list[ParserEvent]:
        from aicoder.tools.parser import parse_xml_tools
        from aicoder.tools.result import TextBlock, ToolCall

        blocks = parse_xml_tools(content, registry)
        return self._blocks_to_events(blocks, content)

    def feed(self, chunk: str, registry: ToolRegistry) -> list[ParserEvent]:
        self._buffer.append(chunk)
        return []

    def finalize(self) -> list[ParserEvent]:
        if not self._buffer:
            return []
        from aicoder.tools.parser import parse_xml_tools
        from aicoder.tools.result import TextBlock, ToolCall
        from aicoder.tools.registry import ToolRegistry

        full = "".join(self._buffer)
        self._buffer.clear()

        # We need a registry here. If feed was used without parse, we can't
        # finalize without one. Return the raw text as a text event.
        return [ParserEvent(kind="text", text=full, raw=full)]

    def finalize_with_registry(self, registry: ToolRegistry) -> list[ParserEvent]:
        """Finalize with a registry for proper XML parsing."""
        if not self._buffer:
            return []
        from aicoder.tools.parser import parse_xml_tools
        from aicoder.tools.result import TextBlock, ToolCall

        full = "".join(self._buffer)
        self._buffer.clear()
        blocks = parse_xml_tools(full, registry)
        return self._blocks_to_events(blocks, full)

    @staticmethod
    def _blocks_to_events(blocks, content: str) -> list[ParserEvent]:
        from aicoder.tools.result import TextBlock, ToolCall

        events: list[ParserEvent] = []
        for block in blocks:
            if isinstance(block, ToolCall):
                events.append(ParserEvent(
                    kind="action",
                    action_name=block.name,
                    action_input=dict(block.params),
                    raw=_extract_raw(content, block),
                ))
            elif isinstance(block, TextBlock):
                text = block.content.strip()
                if text:
                    events.append(ParserEvent(kind="text", text=text, raw=text))

        has_action = any(e.kind == "action" for e in events)
        if not has_action and events:
            events[-1].kind = "final"
        return events


def _extract_raw(content: str, tool_call) -> str:
    """Extract the raw XML substring for a tool call from content."""
    open_tag = f"<{tool_call.name}>"
    close_tag = f"</{tool_call.name}>"
    start = content.find(open_tag)
    if start == -1:
        return open_tag + "..."
    end = content.find(close_tag, start)
    if end == -1:
        return content[start:]
    return content[start : end + len(close_tag)]
