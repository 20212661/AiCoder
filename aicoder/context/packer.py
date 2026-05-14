"""Unified context packer — single entry point for LLM message assembly.

All graph nodes and runners that need to build the full LLM message list
must go through ``pack_context()`` instead of manually calling the
individual message_builder helpers.

The underlying message_builder functions are still used for the actual
construction — ContextPacker orchestrates them into a coherent whole.

v1.2: Budget is applied in layered order:
1. tool_trace_tokens — trim old tool output bodies in the history view
2. history_tokens — trim the (possibly condensed) history to budget
3. focused_file_tokens — trim chat file content to budget
4. repo_map_tokens — repo map budget
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from .policies import ContextBudget, get_context_budget_for_mode, get_context_policy

if TYPE_CHECKING:
    from ..coders.base_coder import Coder


@dataclass
class PackedContext:
    """Result of context packing — ready for LLM consumption."""

    system_messages: list[dict[str, Any]] = field(default_factory=list)
    conversation_messages: list[dict[str, Any]] = field(default_factory=list)
    # v1.2.3: per-layer trace for context observability
    _layer_trace: dict[str, Any] = field(default_factory=dict)

    @property
    def all_messages(self) -> list[dict[str, Any]]:
        return self.system_messages + self.conversation_messages


def _approx_token_count(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate: ~4 chars per token."""
    total = 0
    for m in messages:
        total += len(m.get("content", "") or "")
    return total // 4


def _trim_to_budget(
    messages: list[dict[str, Any]],
    budget_tokens: int,
) -> list[dict[str, Any]]:
    """Drop oldest message pairs until within budget.

    Keeps messages intact — removes complete user/assistant pairs
    starting from the oldest.
    """
    if _approx_token_count(messages) <= budget_tokens:
        return messages

    trimmed = list(messages)
    while len(trimmed) >= 2 and _approx_token_count(trimmed) > budget_tokens:
        trimmed = trimmed[2:]
    return trimmed


# --- File-section splitting for focused_file_preference strategies ---

_FILE_BOUNDARY_RE = re.compile(r'\n\n(?=---\s)')


def _split_file_sections(content: str) -> tuple[str, list[str]]:
    """Split content into header + file sections by ``--- name ---`` markers."""
    parts = _FILE_BOUNDARY_RE.split(content)
    if len(parts) <= 1:
        return content, []
    header = parts[0]
    sections = [p for p in parts[1:] if p.strip()]
    return header, sections


def _depth_trim_content(content: str, max_chars: int) -> str:
    """Drop entire trailing file sections to fit within *max_chars*."""
    header, sections = _split_file_sections(content)
    if not sections:
        return content[:max_chars]
    result = header
    for section in sections:
        candidate = result + "\n\n" + section
        if len(candidate) > max_chars:
            break
        result = candidate
    return result


def _breadth_trim_content(content: str, max_chars: int) -> str:
    """Keep all file sections but truncate each proportionally."""
    header, sections = _split_file_sections(content)
    if not sections:
        return content[:max_chars]
    margin = len(sections) * 30
    available = max_chars - len(header) - margin
    if available <= 0:
        return content[:max_chars]
    per_section = available // len(sections)
    trimmed = []
    for section in sections:
        if len(section) <= per_section:
            trimmed.append(section)
        else:
            trimmed.append(section[:per_section] + "\n...[file trimmed]")
    return header + "\n\n".join(trimmed)


def _balanced_trim_content(content: str, max_chars: int) -> str:
    """Keep full sections until budget, then truncate the next one."""
    header, sections = _split_file_sections(content)
    if not sections:
        return content[:max_chars]
    result = header
    for section in sections:
        candidate = result + "\n\n" + section
        if len(candidate) > max_chars:
            remaining = max_chars - len(result) - 2
            if remaining > 50:
                result = result + "\n\n" + section[:remaining] + "\n...[file trimmed]"
            break
        result = candidate
    return result


def _trim_focused_files(
    messages: list[dict[str, Any]],
    budget_tokens: int,
    mode: str = "act",
) -> list[dict[str, Any]]:
    """Trim chat file messages to fit within focused_file_tokens budget.

    Strategy:
    1. Calculate total tokens of all chat file messages
    2. If over budget, find the file-content user message and truncate it
    3. Preserve first-message/workspace pairs (they are small)

    In act mode the budget is larger (8000) so more focused content survives.
    In sniff mode the budget is smaller (4000) so aggressive trimming happens.
    """
    if not messages or budget_tokens <= 0:
        return messages

    total_tokens = _approx_token_count(messages)
    if total_tokens <= budget_tokens:
        return messages

    result = list(messages)

    # Find the file-content user message (contains "Files added to chat")
    file_msg_idx = None
    for i, m in enumerate(result):
        content = m.get("content", "") or ""
        if m.get("role") == "user" and "Files added to chat" in content:
            file_msg_idx = i
            break

    # Fallback: trim the largest user message
    if file_msg_idx is None:
        user_indices = [
            (i, len(m.get("content", "") or ""))
            for i, m in enumerate(result) if m.get("role") == "user"
        ]
        if user_indices:
            file_msg_idx = max(user_indices, key=lambda x: x[1])[0]

    if file_msg_idx is None:
        return result

    # Budget remaining for the file-content message after reserving space for others
    other_chars = sum(
        len(m.get("content", "") or "")
        for i, m in enumerate(result) if i != file_msg_idx
    )
    file_budget_tokens = budget_tokens - (other_chars // 4)
    max_file_chars = max(file_budget_tokens, 0) * 4

    content = result[file_msg_idx].get("content", "") or ""

    if max_file_chars <= 0:
        # No room — keep only the header line
        header_end = content.find("\n\n")
        result[file_msg_idx] = dict(result[file_msg_idx])
        if header_end > 0:
            result[file_msg_idx]["content"] = content[:header_end] + "\n\n[trimmed: focused_file_tokens budget exhausted]"
        else:
            result[file_msg_idx]["content"] = "[trimmed: focused_file_tokens budget exhausted]"
        result[file_msg_idx]["_focused_trimmed"] = True
        return result

    if len(content) > max_file_chars:
        result[file_msg_idx] = dict(result[file_msg_idx])
        pref = get_context_policy(mode).focused_file_preference
        if pref == "breadth":
            trimmed = _breadth_trim_content(content, max_file_chars)
        elif pref == "depth":
            trimmed = _depth_trim_content(content, max_file_chars)
        else:  # balanced
            trimmed = _balanced_trim_content(content, max_file_chars)
        result[file_msg_idx]["content"] = trimmed + "\n...[trimmed to focused_file_tokens budget]"
        result[file_msg_idx]["_focused_trimmed"] = True

    return result


def _trim_tool_traces(
    messages: list[dict[str, Any]],
    budget_tokens: int,
) -> list[dict[str, Any]]:
    """Trim old tool output bodies to fit within tool_trace_tokens.

    Detects tool trace messages across roles:
    - user: "[tool_name] Result:..." / "[tool_name] FAILED:..." (CoT path)
    - assistant: "[tool_name] Result:..." (CoT assistant observations)
    - tool: structured FC tool messages

    Only older half of traces are trimmed — recent traces stay intact.
    """
    if not messages or budget_tokens <= 0:
        return messages

    # Identify tool trace messages across all roles
    tool_trace_indices = []
    for i, m in enumerate(messages):
        role = m.get("role", "")
        content = m.get("content") or ""
        # FC tool messages
        if role == "tool":
            tool_trace_indices.append(i)
        # CoT text-form observations: "[tool_name] ..."
        elif content and content.startswith("[") and "]" in content:
            tool_trace_indices.append(i)

    if not tool_trace_indices:
        return messages

    # Calculate total trace tokens
    total_trace = sum(
        len(messages[i].get("content", "")) // 4
        for i in tool_trace_indices
    )
    if total_trace <= budget_tokens:
        return messages

    # Trim from oldest trace messages, keeping recent ones intact
    result = list(messages)
    target_per_trace = budget_tokens // max(len(tool_trace_indices), 1)
    max_trace_content = target_per_trace * 4  # chars

    # Only trim the older half of traces — recent traces stay full
    split = len(tool_trace_indices) // 2
    for idx_pos in range(split):
        i = tool_trace_indices[idx_pos]
        content = result[i].get("content", "")
        if len(content) > max_trace_content:
            result[i] = dict(result[i])
            result[i]["content"] = content[:max_trace_content] + "\n...[trimmed]"
            result[i]["_trace_trimmed"] = True

    return result


def pack_context(
    coder: "Coder",
    user_input: str,
    mode: str,
    runner_type: str,
    history_override: list[dict[str, Any]] | None = None,
) -> PackedContext:
    """Build the full LLM context from coder state.

    Centralizes:
    1. System prompt construction
    2. Runtime state attachment
    3. Mode-specific attachments
    4. History messages (from history view, trimmed by budget)
    5. Tool trace trimming (tool_trace_tokens)
    6. File context (chat files) — focused_file_tokens budget
    7. Current messages
    8. User input
    9. Repo context

    Args:
        coder: The Coder instance with all state.
        user_input: The user's latest input.
        mode: Current execution mode ("sniff", "plan", "act").
        runner_type: "function-calling" or "cot".
        history_override: When provided (e.g. by FC runner's
            ``build_history_messages()``), used in place of
            ``coder.done_messages`` so that structured tool_calls /
            tool messages survive into the final LLM context.

    Returns:
        PackedContext with system_messages and conversation_messages.
    """
    from ..coders.message_builder import (
        build_system_messages,
        build_runtime_state_messages,
        build_mode_messages,
        build_chat_files_messages,
    )

    budget = get_context_budget_for_mode(mode)
    policy = get_context_policy(mode)

    # --- System section ---
    system_messages: list[dict[str, Any]] = []
    system_messages.extend(build_system_messages(coder))
    system_messages.extend(build_runtime_state_messages(coder))
    system_messages.extend(build_mode_messages(coder))

    # --- Conversation section ---
    conversation_messages: list[dict[str, Any]] = []
    trace: dict[str, int] = {}

    # History: prefer structured rebuild from runner (FC), fall back to done_messages (CoT)
    if history_override is not None:
        # Compat fallback: explicit override takes precedence
        history = list(history_override)
    else:
        # v1.2: use history view to get the right history for this runner type
        from .history_view import build_llm_history_view
        history = build_llm_history_view(coder, mode, runner_type)

    # v1.2: apply tool_trace_tokens trimming before history budget trim
    history = _trim_tool_traces(history, budget.tool_trace_tokens)

    # v1.2: history_tokens now applies to the (possibly condensed) history view
    history = _trim_to_budget(history, budget.history_tokens)
    trace["history_start"] = len(conversation_messages)
    conversation_messages.extend(history)
    trace["history_end"] = len(conversation_messages)

    # File context (chat files, workspace info) — enforce focused_file_tokens
    trace["chat_files_start"] = len(conversation_messages)
    chat_files_raw = build_chat_files_messages(coder)
    trace["focused_file_tokens_before"] = _approx_token_count(chat_files_raw)
    chat_files = _trim_focused_files(chat_files_raw, budget.focused_file_tokens, mode)
    trace["focused_file_tokens_after"] = _approx_token_count(chat_files)
    conversation_messages.extend(chat_files)
    trace["chat_files_end"] = len(conversation_messages)

    # Current in-progress messages
    trace["current_start"] = len(conversation_messages)
    conversation_messages.extend(coder.cur_messages)
    trace["current_end"] = len(conversation_messages)

    # User input (new message)
    trace["user_input_start"] = len(conversation_messages)
    if user_input:
        conversation_messages.append(dict(role="user", content=user_input))
    trace["user_input_end"] = len(conversation_messages)

    # Repo context slot
    repo_ctx = build_repo_context(coder, mode, budget.repo_map_tokens)
    trace["repo_count"] = len(repo_ctx)
    trace["repo_budget_tokens"] = budget.repo_map_tokens
    trace["repo_token_estimate"] = _approx_token_count(repo_ctx)
    if repo_ctx:
        # Insert repo context after system, before conversation
        conversation_messages = repo_ctx + conversation_messages
        # Adjust trace offsets for prepended repo context
        offset = len(repo_ctx)
        for key in ("history_start", "history_end", "chat_files_start",
                     "chat_files_end", "current_start", "current_end",
                     "user_input_start", "user_input_end"):
            if key in trace:
                trace[key] += offset
        trace["repo_start"] = 0
        trace["repo_end"] = offset

    # v1.3: policy observability in trace
    trace["policy_detail_level"] = policy.repo_detail_level
    trace["policy_include_symbols"] = policy.include_symbols
    trace["policy_include_snippets"] = policy.include_snippets
    trace["policy_focused_pref"] = policy.focused_file_preference

    return PackedContext(
        system_messages=system_messages,
        conversation_messages=conversation_messages,
        _layer_trace=trace,
    )


def build_repo_context(
    coder: "Coder",
    mode: str,
    budget_tokens: int,
) -> list[dict[str, Any]]:
    """Build repo context messages within the given budget.

    Delegates to ``aicoder.context.repo_map.build_repo_context()``.
    """
    from .repo_map import build_repo_context as _build_repo_context
    return _build_repo_context(coder, mode, budget_tokens)


def federation_context_messages(bundle: Any) -> list[dict[str, Any]]:
    """Convert a RestoreBundle into LLM-consumable messages.

    Returns a list of user/assistant message pairs describing the federated
    context from prior sessions. Empty list if bundle has no content.
    """
    if bundle is None:
        return []

    sections: list[str] = []

    if getattr(bundle, "goals", None):
        goals_text = "\n".join(f"  - {g}" for g in bundle.goals)
        sections.append(f"Prior session goals:\n{goals_text}")

    if getattr(bundle, "decisions", None):
        dec_text = "\n".join(f"  - {d}" for d in bundle.decisions[:10])
        sections.append(f"Key decisions from prior sessions:\n{dec_text}")

    if getattr(bundle, "open_loops", None):
        loops_text = "\n".join(f"  - {l}" for l in bundle.open_loops[:5])
        sections.append(f"Open items to continue:\n{loops_text}")

    if getattr(bundle, "critical_files", None):
        files_text = ", ".join(bundle.critical_files[:15])
        sections.append(f"Critical files from prior sessions: {files_text}")

    if getattr(bundle, "constraints", None):
        con_text = "\n".join(f"  - {c}" for c in bundle.constraints[:5])
        sections.append(f"Constraints from prior sessions:\n{con_text}")

    if not sections:
        return []

    content = "\n\n".join(sections)
    return [dict(role="user", content=f"[Federation Context]\n{content}")]


def trim_federation_context(bundle: Any, max_tokens: int) -> str:
    """Trim a RestoreBundle's text representation to fit within max_tokens.

    Applies layered trimming: drops oldest goals/decisions first, then
    truncates remaining content to fit the budget.
    """
    if bundle is None:
        return ""

    msgs = federation_context_messages(bundle)
    if not msgs:
        return ""

    combined = "\n".join(m.get("content", "") for m in msgs)
    total_chars = len(combined)
    budget_chars = max_tokens * 4

    if total_chars <= budget_chars:
        return combined

    # Progressive trimming: drop items from the bundle
    import copy
    trimmed = copy.deepcopy(bundle)

    # Phase 1: Truncate decisions (most voluminous)
    if len(trimmed.decisions) > 5:
        trimmed.decisions = trimmed.decisions[-5:]

    # Phase 2: Truncate goals
    if len(trimmed.goals) > 3:
        trimmed.goals = trimmed.goals[-3:]

    # Phase 3: Truncate open loops
    if len(trimmed.open_loops) > 3:
        trimmed.open_loops = trimmed.open_loops[-3:]

    # Phase 4: Truncate critical files
    if len(trimmed.critical_files) > 10:
        trimmed.critical_files = trimmed.critical_files[-10:]

    msgs2 = federation_context_messages(trimmed)
    combined2 = "\n".join(m.get("content", "") for m in msgs2)

    if len(combined2) <= budget_chars:
        return combined2

    # Final fallback: hard truncate
    return combined2[:budget_chars]
