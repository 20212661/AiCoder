"""Structured TUI message pipeline inspired by chat UIs like Cline."""
from __future__ import annotations

from dataclasses import dataclass, field


LOW_STAKES_TOOLS = {"read_file", "list_files", "search_files", "list_code_defs"}


@dataclass
class UiEvent:
    kind: str
    event_id: str = ""
    content: str = ""
    msg_type: str = "system"
    tool_name: str = ""
    phase: str = ""
    params: dict[str, str] = field(default_factory=dict)
    success: bool | None = None
    output: str = ""
    error: str = ""
    partial: bool = False
    meta: dict = field(default_factory=dict)


@dataclass
class RenderNode:
    kind: str
    content: str = ""
    msg_type: str = "system"
    title: str = ""
    body: str = ""
    items: list[str] = field(default_factory=list)
    pending: bool = False
    partial: bool = False
    meta: dict = field(default_factory=dict)


def transform_events(events: list[UiEvent]) -> list[RenderNode]:
    """Collapse noisy tool chatter into a compact chat-friendly structure."""
    nodes: list[RenderNode] = []
    index = 0

    while index < len(events):
        event = events[index]

        if event.kind != "tool":
            nodes.append(
                RenderNode(
                    kind="message",
                    content=event.content,
                    msg_type=event.msg_type,
                    partial=event.partial,
                    meta=dict(event.meta),
                )
            )
            index += 1
            continue

        if _should_skip_start(events, index):
            index += 1
            continue

        if _is_low_stakes_finish(event):
            group_items: list[str] = []
            counts: dict[str, int] = {}
            while index < len(events) and _is_low_stakes_finish(events[index]):
                grouped = events[index]
                counts[grouped.tool_name] = counts.get(grouped.tool_name, 0) + 1
                group_items.append(_summarize_low_stakes_tool(grouped))
                index += 1
            nodes.append(
                RenderNode(
                    kind="tool_group",
                    title=_build_tool_group_title(counts),
                    items=group_items,
                    partial=any(item.partial for item in events[max(0, index - len(group_items)):index]),
                )
            )
            continue

        nodes.append(_event_to_node(event))
        index += 1

    return nodes


def _should_skip_start(events: list[UiEvent], index: int) -> bool:
    event = events[index]
    if event.kind != "tool" or event.phase != "start":
        return False
    if index + 1 >= len(events):
        return False
    nxt = events[index + 1]
    return (
        nxt.kind == "tool"
        and nxt.phase == "finish"
        and nxt.tool_name == event.tool_name
        and nxt.params == event.params
    )


def _is_low_stakes_finish(event: UiEvent) -> bool:
    return (
        event.kind == "tool"
        and event.phase == "finish"
        and event.success is True
        and event.tool_name in LOW_STAKES_TOOLS
    )


def _event_to_node(event: UiEvent) -> RenderNode:
    if event.kind != "tool":
        return RenderNode(
            kind="message",
            content=event.content,
            msg_type=event.msg_type,
            partial=event.partial,
            meta=dict(event.meta),
        )

    if event.phase == "start":
        return RenderNode(
            kind="tool_status",
            title=_pending_title(event),
            pending=True,
            partial=True,
            meta=dict(event.meta),
        )

    if event.tool_name == "run_shell":
        return RenderNode(
            kind="command",
            title=_command_title(event),
            body=_command_body(event),
            pending=False,
            partial=event.partial,
            meta=dict(event.meta),
        )

    if event.tool_name in {"edit_file", "write_file"} and event.meta.get("diff"):
        return RenderNode(
            kind="diff",
            title=_diff_title(event),
            body=event.meta.get("diff", ""),
            pending=False,
            partial=event.partial,
            meta=dict(event.meta),
        )

    title = _tool_title(event)
    body = _tool_body(event)
    return RenderNode(
        kind="tool",
        title=title,
        body=body,
        pending=False,
        partial=event.partial,
        meta=dict(event.meta),
    )


def _pending_title(event: UiEvent) -> str:
    if event.tool_name == "run_shell":
        return "Running command..."
    if event.tool_name == "read_file":
        return f"Reading {event.params.get('path', '(unknown file)')}..."
    if event.tool_name == "list_files":
        return f"Listing {event.params.get('path', '.')}..."
    if event.tool_name == "search_files":
        return f"Searching {event.params.get('path', '.')}..."
    if event.tool_name == "list_code_defs":
        return f"Inspecting symbols in {event.params.get('path', '.')}..."
    return f"Executing {event.tool_name}..."


def _build_tool_group_title(counts: dict[str, int]) -> str:
    parts: list[str] = []
    if counts.get("read_file"):
        count = counts["read_file"]
        parts.append(f"read {count} file" + ("s" if count != 1 else ""))
    if counts.get("list_files"):
        count = counts["list_files"]
        parts.append(f"listed {count} folder" + ("s" if count != 1 else ""))
    if counts.get("search_files"):
        count = counts["search_files"]
        parts.append(f"ran {count} search" + ("es" if count != 1 else ""))
    if counts.get("list_code_defs"):
        count = counts["list_code_defs"]
        parts.append(f"checked {count} symbol set" + ("s" if count != 1 else ""))
    joined = ", ".join(parts) if parts else "used tools"
    return "AiCoder " + joined + ":"


def _summarize_low_stakes_tool(event: UiEvent) -> str:
    tool_name = event.tool_name
    params = event.params
    if tool_name == "read_file":
        path = params.get("path", "(unknown file)")
        start = params.get("start_line", "").strip()
        end = params.get("end_line", "").strip()
        if start and end:
            return f"FILE {path}  lines {start}-{end}"
        if start:
            return f"FILE {path}  from line {start}"
        return f"FILE {path}"
    if tool_name == "list_files":
        path = params.get("path", ".")
        recursive = params.get("recursive", "false").lower() == "true"
        return f"DIR  {path}{'  recursive' if recursive else ''}"
    if tool_name == "search_files":
        regex = params.get("regex", "")
        path = params.get("path", ".")
        return f"SEARCH {regex!r} in {path}"
    if tool_name == "list_code_defs":
        path = params.get("path", ".")
        return f"SYMS {path}"
    return event.tool_name


def _command_title(event: UiEvent) -> str:
    command = event.params.get("command", "").strip() or "(empty command)"
    status = "OK" if event.success else "FAILED"
    return f"Command {status}: {command}"


def _command_body(event: UiEvent) -> str:
    text = event.output if event.success else event.error
    lines = [line for line in text.splitlines() if line.strip()]
    preview = lines[:12]
    if len(lines) > 12:
        preview.append(f"... ({len(lines) - 12} more lines)")
    return "\n".join(preview)


def _diff_title(event: UiEvent) -> str:
    path = event.meta.get("path") or event.params.get("path") or "(unknown file)"
    action = event.meta.get("action", "Updated")
    return f"{action} {path}"


def _tool_title(event: UiEvent) -> str:
    tool = event.tool_name
    if event.success:
        return f"Tool OK: {tool}"
    return f"Tool FAILED: {tool}"


def _tool_body(event: UiEvent) -> str:
    text = event.output if event.success else event.error
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    preview = lines[:10]
    if len(lines) > 10:
        preview.append(f"... ({len(lines) - 10} more lines)")
    return "\n".join(preview)
