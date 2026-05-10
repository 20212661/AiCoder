"""LangGraph nodes for the aiCoder agent workflow.

Each node receives the full AgentGraphState and returns a dict of state updates.
Nodes access Coder infrastructure via state['_coder'].
"""
from __future__ import annotations

import time
from typing import Any

from ..exceptions import LLMError
from .state import AgentGraphState


def _get_coder(state: AgentGraphState):
    from .state import get_registered_coder
    session_id = state.get("session_id", "")
    coder = get_registered_coder(session_id)
    if coder:
        return coder
    # Fallback for legacy state that still has _coder
    return state.get("_coder")


def _trim_messages(coder, messages: list[dict], reserve: int = 4096) -> list[dict]:
    """Trim messages to fit within the model's context window.

    3-tier strategy (mirrors legacy _trim_context_for_model):
    1. LLM summarization of older messages (if summarizer available)
    2. ContextManager truncation (progressive pair dropping)
    3. Emergency truncation (keep system prefix + last N messages)
    """
    max_tokens = getattr(coder.main_model, "max_input_tokens", 0)
    if max_tokens <= 0:
        return messages
    token_fn = getattr(coder.main_model, "token_count", None)
    if token_fn is None:
        return messages
    try:
        if token_fn(messages) <= max_tokens - reserve:
            return messages
    except Exception:
        return messages

    # Tier 1: LLM summarization (if summarizer is available on the coder)
    summarizer = getattr(coder, "summarizer", None)
    if summarizer is None:
        try:
            from ..history import ChatSummary
            summarizer = ChatSummary(models=[coder.main_model], max_tokens=reserve)
            coder.summarizer = summarizer
        except Exception:
            pass
    if summarizer:
        try:
            if summarizer.too_big(messages):
                summarized = summarizer.summarize(messages)
                if token_fn(summarized) <= max_tokens - reserve:
                    return summarized
        except Exception:
            pass

    # Tier 2: ContextManager truncation (progressive pair dropping)
    try:
        from ..context_manager import ContextManager
        ctx_mgr = ContextManager(
            token_counter=token_fn,
            max_input_tokens=max_tokens,
        )
        snap = ctx_mgr.prepare_messages(messages)
        if snap.truncated and token_fn(snap.messages) <= max_tokens - reserve:
            return snap.messages
    except Exception:
        pass

    # Tier 3: Emergency truncation — drop oldest pairs
    system_end = 0
    for i, m in enumerate(messages):
        if m.get("role") == "user":
            system_end = i
            break

    trimmed = list(messages)
    while len(trimmed) > system_end + 4 and token_fn(trimmed) > max_tokens - reserve:
        if system_end + 2 <= len(trimmed):
            trimmed = trimmed[:system_end] + trimmed[system_end + 2:]
        else:
            break

    if token_fn(trimmed) > max_tokens - reserve:
        trimmed = list(messages[:system_end]) + list(messages[-8:])

    return trimmed


# ---------------------------------------------------------------------------
# Shared: call LLM with retry, return raw text + stream to IO
# ---------------------------------------------------------------------------

def _call_llm(coder, messages: list[dict]) -> str:
    """Call the LLM (stream or non-stream) with 3-retry, return full text."""
    io = coder.io
    text = ""
    for attempt in range(3):
        try:
            if coder.stream:
                resp = coder.main_model.send_completion(messages, stream=True)
                chunks: list[str] = []
                for chunk in resp:
                    if chunk.choices and chunk.choices[0].delta:
                        c = chunk.choices[0].delta.content
                        if c:
                            chunks.append(c)
                            io.print_streaming(c)
                text = "".join(chunks)
            else:
                text = coder.main_model.simple_send(messages) or ""
                if text:
                    io.print_assistant_output(text)
            break
        except Exception as err:
            if attempt < 2:
                delay = 2 ** attempt
                io.tool_warning(
                    f"LLM error [{coder.main_model.name}] "
                    f"(retry {attempt + 1}/3 in {delay}s): {err}"
                )
                time.sleep(delay)
            else:
                raise LLMError(coder.main_model.name, str(err))
    return text


def _build_llm_messages(coder) -> list[dict[str, Any]]:
    """Assemble the full message list for the LLM."""
    from ..coders.message_builder import (
        build_system_messages,
        build_chat_files_messages,
        build_mode_messages,
        build_runtime_state_messages,
    )

    msgs = list(build_system_messages(coder))
    msgs.extend(build_runtime_state_messages(coder))
    msgs.extend(build_mode_messages(coder))
    msgs.extend(coder.done_messages)
    msgs.extend(build_chat_files_messages(coder))
    msgs.extend(coder.cur_messages)
    return msgs


# ---------------------------------------------------------------------------
# Nodes: plan path
# ---------------------------------------------------------------------------

def prepare_context(state: AgentGraphState) -> dict[str, Any]:
    """Build system messages, file context, and mode attachments."""
    coder = _get_coder(state)
    messages = []
    if coder:
        coder._first_message = True
        messages = _build_llm_messages(coder)

    messages.append(dict(role="user", content=state.get("user_input", "")))

    return {
        "phase": "preparing",
        "messages": messages,
    }


def route_mode(state: AgentGraphState) -> str:
    """Route to 'plan' or 'act' based on the current mode."""
    if state.get("mode") == "plan":
        return "plan"
    return "act"


def plan_node(state: AgentGraphState) -> dict[str, Any]:
    """Call the LLM to generate a plan (read-only, no tool execution)."""
    coder = _get_coder(state)
    if not coder:
        return {"phase": "error", "error": "No coder instance in state"}

    io = coder.io
    has_finalize = hasattr(io, "finalize_streaming")

    io.user_input(state.get("user_input", ""))

    coder._first_message = True
    messages = _build_llm_messages(coder)
    messages.append(dict(role="user", content=state.get("user_input", "")))

    plan_text = _call_llm(coder, messages)

    if has_finalize:
        io.finalize_streaming(plan_text)

    coder.cur_messages.append(dict(role="user", content=state.get("user_input", "")))
    coder.cur_messages.append(dict(role="assistant", content=plan_text))

    return {
        "phase": "planning",
        "current_plan": plan_text,
        "messages": messages + [dict(role="assistant", content=plan_text)],
    }


def request_plan_approval(state: AgentGraphState) -> dict[str, Any]:
    """Finalize the plan and write it into state. End the graph here."""
    coder = _get_coder(state)
    plan = state.get("current_plan", "")

    if coder:
        coder.done_messages.extend(coder.cur_messages)
        coder.cur_messages = []
        coder._save_session()

    return {
        "phase": "done",
        "final_response": plan,
    }


# ---------------------------------------------------------------------------
# Nodes: act path
# ---------------------------------------------------------------------------

def model_node(state: AgentGraphState) -> dict[str, Any]:
    """Call the LLM model, stream the response, and detect tool calls."""
    coder = _get_coder(state)
    if not coder:
        return {"phase": "error", "error": "No coder instance in state"}

    io = coder.io
    has_finalize = hasattr(io, "finalize_streaming")

    # First call: append user_input; subsequent loops: messages already contain tool results
    if state.get("loop_count", 0) == 0:
        io.user_input(state.get("user_input", ""))

    messages = state.get("messages", [])
    if not messages:
        coder._first_message = True
        messages = _build_llm_messages(coder)
        messages.append(dict(role="user", content=state.get("user_input", "")))

    # Trim context if messages are too long for the model
    messages = _trim_messages(coder, messages)

    # Reset execution state for each model call
    coder.tool_exec_state.reset()

    response_text = _call_llm(coder, messages)

    # Parse tool calls from the response
    from ..tools.parser import parse_xml_tools
    from ..tools.result import ToolCall, TextBlock

    blocks = parse_xml_tools(response_text, coder.tool_registry)
    tool_calls = [b for b in blocks if isinstance(b, ToolCall)]
    text_parts = [b.content.strip() for b in blocks if isinstance(b, TextBlock) and b.content.strip()]

    # Update pending_tool_calls in state
    pending = []
    for tc in tool_calls:
        pending.append({"name": tc.name, "params": dict(tc.params)})

    # Determine next route
    new_loop = state.get("loop_count", 0) + 1

    # If no tool calls, this is the final response
    if not tool_calls:
        if has_finalize:
            io.finalize_streaming(response_text)

        # Update coder messages
        if state.get("loop_count", 0) == 0:
            coder.cur_messages.append(dict(role="user", content=state.get("user_input", "")))
        coder.cur_messages.append(dict(role="assistant", content=response_text))

        return {
            "phase": "summarizing",
            "messages": messages + [dict(role="assistant", content=response_text)],
            "pending_tool_calls": [],
            "loop_count": new_loop,
        }

    # Intermediate finalize for streaming
    if has_finalize:
        clean_text = "\n".join(text_parts) if text_parts else "(used tools)"
        io.finalize_streaming(clean_text, is_intermediate=True)

    # Append intermediate assistant message to coder
    if state.get("loop_count", 0) == 0:
        coder.cur_messages.append(dict(role="user", content=state.get("user_input", "")))
    clean_for_ctx = "\n".join(text_parts) if text_parts else "(used tools)"
    coder.cur_messages.append(dict(role="assistant", content=clean_for_ctx))

    return {
        "phase": "acting",
        "messages": messages + [dict(role="assistant", content=response_text)],
        "pending_tool_calls": pending,
        "loop_count": new_loop,
    }


def parse_tool_calls(state: AgentGraphState) -> dict[str, Any]:
    """Pass-through: tool calls are already parsed in model_node."""
    return {"phase": "tool_running"}


def permission_node(state: AgentGraphState) -> dict[str, Any]:
    """Decide allow/ask/deny for each pending tool call.

    Returns:
      - pending_tool_calls kept -> route to execute
      - pending_tool_calls cleared -> route to deny/summarize
    """
    coder = _get_coder(state)
    if not coder:
        return {}

    from ..permission_modes import can_use_tool_in_mode, ToolPermissionContext

    approval = getattr(coder, "_approval", None)
    pending = state.get("pending_tool_calls", [])
    mode = state.get("mode", "act")

    needs_approval: list[dict] = []
    approved: list[dict] = []
    new_obs: list[dict[str, Any]] = []

    for tc in pending:
        decision = can_use_tool_in_mode(
            tc["name"],
            tc.get("params"),
            ToolPermissionContext(mode=mode),
            approval,
        )
        if decision.behavior == "deny":
            new_obs.append({
                "tool_name": tc["name"],
                "params": tc.get("params", {}),
                "success": False,
                "error": decision.reason,
                "rejected": False,
            })
            coder.io.tool_warning(f"Denied: {tc['name']} — {decision.reason}")
            continue

        if decision.behavior == "ask":
            needs_approval.append(tc)
        else:
            approved.append(tc)

    if needs_approval:
        from .interrupts import request_tool_approval

        for tc in needs_approval:
            handler = coder.tool_coordinator.get(tc["name"])
            desc = handler.description(tc) if handler and hasattr(handler, "description") else tc["name"]
            params_preview = str(tc.get("params", ""))[:200]
            ok = request_tool_approval(
                state,
                tool_name=tc["name"],
                desc=desc,
                params_preview=params_preview,
            )
            if ok:
                approved.append(tc)
            else:
                coder.tool_exec_state.did_reject_tool = True
                new_obs.append({
                    "tool_name": tc["name"],
                    "params": tc.get("params", {}),
                    "success": False,
                    "error": "User rejected the tool call.",
                    "rejected": True,
                })

    result: dict[str, Any] = {
        "pending_tool_calls": approved,
    }
    if new_obs:
        result["tool_observations"] = list(state.get("tool_observations", [])) + new_obs

    return result


def execute_tool_node(state: AgentGraphState) -> dict[str, Any]:
    """Execute approved tool calls via the existing ToolExecutor."""
    coder = _get_coder(state)
    if not coder:
        return {}

    pending = state.get("pending_tool_calls", [])
    if not pending:
        return {}

    from ..tools.result import ToolCall as TC

    observations: list[dict[str, Any]] = list(state.get("tool_observations", []))

    for tc in pending:
        tool_call = TC(name=tc["name"], params=tc.get("params", {}))
        result = coder.tool_executor.execute(tool_call, skip_permission=True)

        obs: dict[str, Any] = {
            "tool_name": result.tool_name,
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "rejected": result.rejected,
            "params": tc.get("params", {}),
        }
        observations.append(obs)

        # Write result into coder messages (mirrors old behavior)
        coder.cur_messages.append(result.to_message())

        # Stop if rejected
        if result.rejected:
            coder.io.tool_warning("REJECTED - skipping remaining tools")
            break

        # Stop if too many errors
        if coder.tool_exec_state.too_many_errors:
            coder.io.tool_warning("ERROR LIMIT - stopping")
            break

    return {
        "tool_observations": observations,
        "pending_tool_calls": [],
    }


def observe_tool_result(state: AgentGraphState) -> dict[str, Any]:
    """Write tool results back into messages and prepare for next model call."""
    observations = state.get("tool_observations", [])
    messages = list(state.get("messages", []))

    for obs in observations:
        label = f"[{obs['tool_name']}]"
        if obs.get("rejected"):
            text = f"{label} REJECTED by user."
        elif obs.get("success"):
            output = obs.get("output", "").strip()
            text = f"{label} Result:\n{output}" if output else f"{label} OK (no output)."
        else:
            text = f"{label} FAILED:\n{obs.get('error', '')}"
        messages.append(dict(role="user", content=text))

    return {
        "messages": messages,
        "tool_observations": [],
    }


# ---------------------------------------------------------------------------
# Nodes: shared
# ---------------------------------------------------------------------------

def summarize_node(state: AgentGraphState) -> dict[str, Any]:
    """Produce a final summary and persist session."""
    messages = state.get("messages", [])
    final = ""
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            final = msg["content"]
            break

    coder = _get_coder(state)
    if coder:
        # Auto-commit if there were file edits
        edited = coder.tool_exec_state.had_file_edits
        if edited and coder.auto_commits and coder.repo:
            coder.auto_commit()

        # LLM summarization of old messages (mirrors legacy summarize_if_needed)
        summarizer = getattr(coder, "summarizer", None)
        if summarizer is None:
            try:
                from ..history import ChatSummary
                summarizer = ChatSummary(models=[coder.main_model], max_tokens=4096)
                coder.summarizer = summarizer
            except Exception:
                pass
        if summarizer and summarizer.too_big(coder.done_messages):
            try:
                coder.done_messages = summarizer.summarize(coder.done_messages)
            except Exception:
                pass

        coder.done_messages.extend(coder.cur_messages)
        coder.cur_messages = []
        coder._save_session()

    return {"phase": "done", "final_response": final}


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------

def route_after_model(state: AgentGraphState) -> str:
    """After model_node: go to tool parsing if tools present, else summarize."""
    pending = state.get("pending_tool_calls")
    loop = state.get("loop_count", 0)
    max_loops = state.get("max_loops", 5)

    # Check coder error state
    coder = _get_coder(state)
    if coder and coder.tool_exec_state.too_many_errors:
        return "finish"

    if pending and loop <= max_loops:
        return "tools"
    return "finish"


def route_after_permission(state: AgentGraphState) -> str:
    """After permission_node: execute if tools remain, else deny/summarize."""
    pending = state.get("pending_tool_calls")
    if pending:
        return "execute"

    return "deny"


def route_after_observe(state: AgentGraphState) -> str:
    """After observe_tool_result: loop back to model or finish."""
    loop = state.get("loop_count", 0)
    max_loops = state.get("max_loops", 5)

    coder = _get_coder(state)
    if coder and coder.tool_exec_state.too_many_errors:
        return "finish"

    if loop < max_loops:
        return "continue"
    return "finish"
