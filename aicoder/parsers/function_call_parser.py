"""Function-call parser — extracts tool_calls from native model responses.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §8.5

Consumes the structured ``tool_calls`` list from models that support native
function calling (OpenAI-compatible format) and emits unified
``ParserEvent(kind="action", ...)`` events so that downstream step-update
logic is consistent between CoT and FC runners.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from aicoder.parsers.base import BaseParser, ParserEvent

if TYPE_CHECKING:
    from aicoder.tools.registry import ToolRegistry


class FunctionCallParser(BaseParser):
    """Parse native ``tool_calls`` from model responses into ParserEvents."""

    def parse(self, content: str, registry: ToolRegistry) -> list[ParserEvent]:
        # For FC mode, ``content`` is the text response (may be empty).
        # Actual tool calls come through ``parse_tool_calls()``.
        if content and content.strip():
            return [ParserEvent(kind="final", text=content.strip(), raw=content)]
        return []

    def feed(self, chunk: str, registry: ToolRegistry) -> list[ParserEvent]:
        # FC mode doesn't do incremental text parsing.
        return []

    def finalize(self) -> list[ParserEvent]:
        return []

    def parse_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[ParserEvent]:
        """Extract actions from the OpenAI-style ``tool_calls`` list.

        Each entry should have:
        - ``function.name``: tool name
        - ``function.arguments``: JSON string of arguments
        """
        if not tool_calls:
            return []

        events: list[ParserEvent] = []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            if not name:
                continue

            args_raw = func.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except (json.JSONDecodeError, ValueError):
                args = args_raw

            events.append(ParserEvent(
                kind="action",
                action_name=name,
                action_input=args if isinstance(args, dict) else str(args),
                raw=args_raw if isinstance(args_raw, str) else json.dumps(args_raw),
            ))
        return events

    def parse_response(
        self,
        content: str | None,
        tool_calls: list[dict[str, Any]] | None,
    ) -> list[ParserEvent]:
        """Convenience: parse both text content and tool_calls from a response.

        If tool_calls are present, they become ``action`` events.
        Otherwise, the text content becomes a ``final`` event.
        """
        events: list[ParserEvent] = []

        if tool_calls:
            tc_events = self.parse_tool_calls(tool_calls)
            events.extend(tc_events)

        # If there's text alongside tool calls, emit it as a text event
        if content and content.strip():
            if tool_calls:
                events.append(ParserEvent(
                    kind="text",
                    text=content.strip(),
                    raw=content,
                ))
            else:
                events.append(ParserEvent(
                    kind="final",
                    text=content.strip(),
                    raw=content,
                ))

        return events
