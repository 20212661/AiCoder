"""Message formatting helpers extracted from base_coder."""

import os
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .base_coder import Coder


def build_system_messages(coder: "Coder") -> list[dict[str, Any]]:
    """Build and cache the system prompt + example messages."""
    mode_key = (
        coder.main_model.name if coder.main_model else "",
        "plan" if coder.tool_exec_state.is_plan_mode else "act",
    )
    if coder._cached_system_key == mode_key and coder._cached_system_messages is not None:
        return coder._cached_system_messages

    coder._update_tool_model_info()
    system_content = coder._system_prompt.build()
    main_system = getattr(coder.gpt_prompts, "main_system", "")
    system_reminder = getattr(coder.gpt_prompts, "system_reminder", "")
    if main_system:
        system_content += "\n\n" + main_system
    if system_reminder:
        system_content += "\n\n" + system_reminder
    cached: list[dict[str, Any]] = []
    if system_content:
        cached.append(dict(role="system", content=system_content))
    for msg in getattr(coder.gpt_prompts, "example_messages", []):
        cached.append(msg)
    coder._cached_system_messages = cached
    coder._cached_system_key = mode_key
    return cached


def format_messages(coder: "Coder") -> list[dict[str, Any]]:
    """Assemble the full message list sent to the LLM."""
    messages = list(build_system_messages(coder))
    messages.extend(build_runtime_state_messages(coder))
    messages.extend(build_mode_messages(coder))
    messages.extend(coder.done_messages)
    repo_map = coder.get_repo_map()
    if repo_map:
        messages += [dict(role="user", content=repo_map), dict(role="assistant", content="Ok.")]
    messages.extend(build_chat_files_messages(coder))
    messages.extend(coder.cur_messages)
    return messages


def build_runtime_state_messages(coder: "Coder") -> list[dict[str, Any]]:
    """Attach the exact live model/mode state so meta questions answer reliably."""
    current_model = coder.main_model.name if coder.main_model else "unknown"
    current_mode = "plan" if coder.tool_exec_state.is_plan_mode else "act"
    return [
        dict(
            role="system",
            content=(
                "CURRENT RUNTIME STATE:\n"
                f"- Current model: {current_model}\n"
                f"- Current mode: {current_mode}\n"
                "If the user asks what model or mode is currently active, answer using these exact values."
            ),
        )
    ]


def build_mode_messages(coder: "Coder") -> list[dict[str, Any]]:
    if not coder.tool_exec_state.is_plan_mode:
        return []

    return [
        dict(
            role="system",
            content=(
                "PLAN MODE ATTACHMENT:\n"
                "You are currently in read-only planning mode.\n"
                "- Explore with read_file, search_files, list_files, list_code_defs, and read-only run_shell.\n"
                "- Do not attempt file edits or mutating shell commands.\n"
                "- End with a concise plan, key findings, and a clear next step to switch to /act."
            ),
        )
    ]


def build_chat_files_messages(coder: "Coder") -> list[dict[str, Any]]:
    """Build the file-content and first-message context blocks."""
    chat: list[dict[str, Any]] = []
    cwd = coder.root.replace("\\", "/")
    if coder.abs_fnames:
        wh = "Working directory: " + cwd + "\n\nYou are in this directory. Files added to chat:"
        fc = wh + "\n\n" + coder.gpt_prompts.files_content_prefix + coder.get_files_content()
        fr = coder.gpt_prompts.files_content_assistant_reply
    else:
        fc = "Working directory: " + cwd + "\n\nNo files added to chat. You CAN explore with list_files, read_file, search_files."
        fr = "Ok."
    if coder._first_message:
        coder._first_message = False
        parts: list[str] = []
        ws = coder._build_workspace_info()
        if ws: parts.append(ws)
        if coder._file_tree is None:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            if os.path.abspath(coder.root) == os.path.abspath(desktop):
                parts.append("# Current Working Directory Files\n(Desktop files not shown automatically. Use list_files to explore.)\n")
            else:
                coder._file_tree = coder._build_file_tree()
        if coder._file_tree: parts.append(coder._file_tree)
        tools = coder._detect_cli_tools()
        if tools: parts.append(tools)
        max_tokens = coder.main_model.max_input_tokens
        cur_tokens = coder.main_model.token_count(coder.done_messages + coder.cur_messages)
        pct = round(cur_tokens / max_tokens * 100) if max_tokens > 0 else 0
        parts.append("# Context Window\n" + str(cur_tokens) + " / " + str(max_tokens) + " tokens (" + str(pct) + "%)\n")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parts.append("# Current Time\n" + now + "\n")
        if parts:
            chat += [dict(role="user", content="\n".join(parts)),
                     dict(role="assistant", content="Ok, I see the project.")]
    if fc: chat += [dict(role="user", content=fc), dict(role="assistant", content=fr)]
    return chat
