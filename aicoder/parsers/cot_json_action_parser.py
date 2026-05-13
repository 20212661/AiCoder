"""CoT JSON action parser — streaming character-level JSON extraction.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §8.4

Inspired by Dify's approach but adapted for AiCoder:
- Character-level streaming parse
- Brace-depth counting for JSON completeness detection
- Code-block extraction (```json ... ```)
- Residual cache tolerance on finalize

Explicitly NOT adopted from Dify:
- No bare variable state piles — uses JsonParseState dataclass
- No hard dependency on ``action:`` / ``thought:`` text prefixes
- No tight coupling between plain text and structured action logic
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aicoder.parsers.base import BaseParser, ParserEvent

if TYPE_CHECKING:
    from aicoder.tools.registry import ToolRegistry


@dataclass
class JsonParseState:
    """Mutable state for the streaming JSON parser."""

    in_code_block: bool = False
    in_json: bool = False
    brace_depth: int = 0
    code_block_cache: str = ""
    json_cache: str = ""
    text_cache: str = ""


class CotJsonActionParser(BaseParser):
    """Streaming JSON action parser with brace-depth tracking."""

    def __init__(self) -> None:
        self._state = JsonParseState()
        self._events: list[ParserEvent] = []

    # -- BaseParser interface ------------------------------------------------

    def parse(self, content: str, registry: ToolRegistry) -> list[ParserEvent]:
        """Parse complete content in one shot."""
        state = JsonParseState()
        events: list[ParserEvent] = []
        for ch in content:
            evts = self._process_char(ch, state)
            events.extend(evts)
        events.extend(self._flush(state))
        return events

    def feed(self, chunk: str, registry: ToolRegistry) -> list[ParserEvent]:
        """Process a streaming chunk incrementally."""
        events: list[ParserEvent] = []
        for ch in chunk:
            evts = self._process_char(ch, self._state)
            events.extend(evts)
        return events

    def finalize(self) -> list[ParserEvent]:
        """Flush residual caches."""
        events = self._flush(self._state)
        self._state = JsonParseState()
        return events

    # -- Internal -----------------------------------------------------------

    @staticmethod
    def _process_char(ch: str, state: JsonParseState) -> list[ParserEvent]:
        events: list[ParserEvent] = []

        # Track code-block boundaries: ``` ... ```
        if not state.in_code_block and not state.in_json:
            if ch == "`" and state.code_block_cache.count("`") < 2:
                state.code_block_cache += ch
                if state.code_block_cache == "```":
                    state.in_code_block = True
                    state.code_block_cache = ""
                    if state.text_cache.strip():
                        events.append(ParserEvent(
                            kind="text",
                            text=state.text_cache.strip(),
                            raw=state.text_cache,
                        ))
                        state.text_cache = ""
                return events
            elif state.code_block_cache:
                # False alarm — was not a code block opening
                state.text_cache += state.code_block_cache
                state.code_block_cache = ""

        if state.in_code_block:
            if ch == "`":
                state.code_block_cache += ch
                if state.code_block_cache == "```":
                    state.in_code_block = False
                    state.code_block_cache = ""
                    # Try to parse the accumulated content as JSON
                    inner = state.json_cache.strip()
                    state.json_cache = ""
                    if inner:
                        parsed = _try_parse_json_action(inner)
                        if parsed:
                            events.append(parsed)
                        else:
                            events.append(ParserEvent(
                                kind="text",
                                text=inner,
                                raw=inner,
                            ))
                return events
            else:
                if state.code_block_cache:
                    state.json_cache += state.code_block_cache
                    state.code_block_cache = ""
                state.json_cache += ch
                return events

        # Track JSON objects outside code blocks
        if state.in_json:
            state.json_cache += ch
            if ch == "{":
                state.brace_depth += 1
            elif ch == "}":
                state.brace_depth -= 1
                if state.brace_depth == 0:
                    state.in_json = False
                    parsed = _try_parse_json_action(state.json_cache.strip())
                    raw = state.json_cache
                    state.json_cache = ""
                    if parsed:
                        events.append(parsed)
                    else:
                        events.append(ParserEvent(
                            kind="text",
                            text=raw.strip(),
                            raw=raw,
                        ))
            return events

        # Outside code block and JSON — look for opening brace
        if ch == "{":
            if state.text_cache.strip():
                events.append(ParserEvent(
                    kind="text",
                    text=state.text_cache.strip(),
                    raw=state.text_cache,
                ))
                state.text_cache = ""
            state.in_json = True
            state.brace_depth = 1
            state.json_cache = ch
            return events

        # Normal text
        state.text_cache += ch
        return events

    @staticmethod
    def _flush(state: JsonParseState) -> list[ParserEvent]:
        """Flush residual caches at end of input."""
        events: list[ParserEvent] = []

        # If still in JSON, try to parse what we have
        if state.in_json and state.json_cache.strip():
            parsed = _try_parse_json_action(state.json_cache.strip())
            if parsed:
                events.append(parsed)
            else:
                events.append(ParserEvent(
                    kind="text",
                    text=state.json_cache.strip(),
                    raw=state.json_cache,
                ))

        # If still in code block, treat cached content as text
        if state.in_code_block and state.json_cache.strip():
            parsed = _try_parse_json_action(state.json_cache.strip())
            if parsed:
                events.append(parsed)
            else:
                events.append(ParserEvent(
                    kind="text",
                    text=state.json_cache.strip(),
                    raw=state.json_cache,
                ))

        # Flush remaining text cache
        if state.text_cache.strip():
            events.append(ParserEvent(
                kind="text",
                text=state.text_cache.strip(),
                raw=state.text_cache,
            ))

        # If no action events were emitted, promote last text to "final"
        has_action = any(e.kind == "action" for e in events)
        if not has_action and events:
            for e in reversed(events):
                if e.kind == "text":
                    e.kind = "final"
                    break

        return events


def _try_parse_json_action(text: str) -> ParserEvent | None:
    """Try to extract a tool-call action from a JSON string.

    Accepts ``{"name": "...", "arguments": {...}}`` or ``{"name": "...", "args": {...}}``.
    """
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(obj, dict):
        return None

    name = obj.get("name")
    if not name or not isinstance(name, str):
        return None

    arguments = obj.get("arguments") or obj.get("args") or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            pass

    return ParserEvent(
        kind="action",
        action_name=name,
        action_input=arguments if isinstance(arguments, dict) else str(arguments),
        raw=text,
    )
