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
    """Assemble the full message list for the LLM.

    Delegates to pack_context(), which internally uses build_llm_history_view()
    to obtain the correct history for the current runner type (FC/CoT).
    """
    from ..context.packer import pack_context

    mode = getattr(coder, "tool_exec_state", None)
    mode_name = mode.mode if mode else "act"

    runner_type = "cot"
    try:
        from ..runners import get_runner as _get_runner
        runner = _get_runner(getattr(coder, "session_id", ""))
        if runner and hasattr(runner, "_runner_type"):
            runner_type = runner._runner_type()
    except Exception:
        pass

    packed = pack_context(
        coder, user_input="", mode=mode_name,
        runner_type=runner_type,
    )
    return packed.all_messages


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
    """Route all modes through the shared model loop.

    v1.1: sniff / plan / act all enter the same model -> parse -> permission
    -> execute -> observe cycle.  Mode-specific behavior is controlled by
    ModeConfig (read-only tools, permissions, completion criteria).
    """
    return "model"


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

    # --- Try runner delegation first ---
    from ..runners import get_runner as _get_runner
    runner = _get_runner(state.get("session_id", ""))

    if runner:
        return _model_node_via_runner(state, coder, messages, runner, has_finalize)

    # --- Fallback: original logic when no runner is registered ---
    return _model_node_fallback(state, coder, messages, has_finalize)


def _model_node_via_runner(state, coder, messages, runner, has_finalize) -> dict[str, Any]:
    """model_node logic using the runner delegation path."""
    io = coder.io
    iteration = state.get("loop_count", 0)
    max_iterations = state.get("max_loops", 5)

    step_result = runner.run_step(messages, iteration, max_iterations)
    response_text = step_result.raw_response
    clean_text = step_result.clean_text
    new_loop = iteration + 1

    # Build pending_tool_calls from StepResult (with tool_call_ids)
    ids = step_result.tool_call_ids
    pending = []
    for idx, tc in enumerate(step_result.tool_calls):
        entry = {"name": tc.name, "params": dict(tc.params)}
        if idx < len(ids):
            entry["tool_call_id"] = ids[idx]
        else:
            entry["tool_call_id"] = f"tc_{idx}"
        pending.append(entry)

    assistant_tool_message = None
    if pending:
        tool_calls = []
        for tc in pending:
            tool_calls.append({
                "id": tc["tool_call_id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": _serialize_tool_args(tc.get("params", {})),
                },
            })
        assistant_tool_message = {
            "role": "assistant",
            "content": clean_text or None,
            "tool_calls": tool_calls,
        }

    # Process failed normalization observations
    failed_obs: list[dict[str, Any]] = []
    for fo in step_result.failed_observations:
        obs_entry = {
            "tool_name": fo.tool_name,
            "success": False,
            "output": fo.output,
            "error": fo.error,
            "rejected": False,
            "params": {},
        }
        failed_obs.append(obs_entry)
        coder.cur_messages.append(fo.to_message())

    # Sync step store for failed normalization observations
    if failed_obs and step_result.step and runner.step_store:
        step = step_result.step
        if step.status == "parsed":
            first_fo = step_result.failed_observations[0]
            tool_meta = {
                "success": False,
                "rejected": False,
                "tool_name": first_fo.tool_name,
            }
            if first_fo.error:
                tool_meta["error"] = first_fo.error
            runner._update_step_after_tool(
                step,
                observation=first_fo.error or first_fo.output or "",
                tool_meta=tool_meta,
                tool_error=True,
            )

    if not step_result.tool_calls and not step_result.failed_observations:
        if has_finalize:
            io.finalize_streaming(response_text)

        if iteration == 0:
            coder.cur_messages.append(dict(role="user", content=state.get("user_input", "")))
        coder.cur_messages.append(dict(role="assistant", content=response_text))

        return {
            "phase": "summarizing",
            "messages": messages + [dict(role="assistant", content=response_text)],
            "pending_tool_calls": [],
            "loop_count": new_loop,
        }

    if has_finalize:
        display_text = clean_text if clean_text else "(used tools)"
        io.finalize_streaming(display_text, is_intermediate=True)

    if iteration == 0:
        coder.cur_messages.append(dict(role="user", content=state.get("user_input", "")))
    display_for_ctx = clean_text if clean_text else "(used tools)"
    coder.cur_messages.append(dict(role="assistant", content=display_for_ctx))

    result: dict[str, Any] = {
        "phase": "acting",
        "messages": messages + [assistant_tool_message or dict(role="assistant", content=response_text)],
        "pending_tool_calls": pending,
        "loop_count": new_loop,
    }
    if failed_obs:
        result["tool_observations"] = list(state.get("tool_observations", [])) + failed_obs
    return result


def _model_node_fallback(state, coder, messages, has_finalize) -> dict[str, Any]:
    """Original model_node logic — used when no runner is registered."""
    io = coder.io
    iteration = state.get("loop_count", 0)

    response_text = _call_llm(coder, messages)

    from ..tools.parser import parse_xml_tools
    from ..tools.result import ToolCall, TextBlock

    blocks = parse_xml_tools(response_text, coder.tool_registry)
    tool_calls = [b for b in blocks if isinstance(b, ToolCall)]
    text_parts = [b.content.strip() for b in blocks if isinstance(b, TextBlock) and b.content.strip()]

    pending = [{"name": tc.name, "params": dict(tc.params)} for tc in tool_calls]
    new_loop = iteration + 1

    if not tool_calls:
        if has_finalize:
            io.finalize_streaming(response_text)
        if iteration == 0:
            coder.cur_messages.append(dict(role="user", content=state.get("user_input", "")))
        coder.cur_messages.append(dict(role="assistant", content=response_text))
        return {
            "phase": "summarizing",
            "messages": messages + [dict(role="assistant", content=response_text)],
            "pending_tool_calls": [],
            "loop_count": new_loop,
        }

    if has_finalize:
        clean_text = "\n".join(text_parts) if text_parts else "(used tools)"
        io.finalize_streaming(clean_text, is_intermediate=True)
    if iteration == 0:
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
                "error_type": "permission_denied",
                "summary": f"Tool '{tc['name']}' denied: {decision.reason}",
                "recommended_next": "Try a read-only tool or switch mode.",
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
                    "error_type": "user_rejected",
                    "summary": f"Tool '{tc['name']}' rejected by user.",
                    "recommended_next": "Try an alternative approach.",
                    "files": [],
                })

    result: dict[str, Any] = {
        "pending_tool_calls": approved,
    }
    if new_obs:
        result["tool_observations"] = list(state.get("tool_observations", [])) + new_obs

    return result


def _suggest_next_step(result) -> str:
    """Suggest a follow-up action based on tool result."""
    if result.rejected:
        return "User rejected the tool call. Try an alternative approach."
    if not result.success:
        return "Tool failed. Consider: check params, try a different tool, or retry."
    return ""


def _fallback_summary(result) -> str:
    """Generate a fallback summary when meta.summary is empty."""
    if result.rejected:
        return f"Tool '{result.tool_name}' rejected."
    if not result.success:
        return f"Tool '{result.tool_name}' failed: {result.error}"
    return f"Tool '{result.tool_name}' succeeded."


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

    # Resolve runner for step store sync
    from ..runners import get_runner as _get_runner
    runner = _get_runner(state.get("session_id", ""))

    # Checkpoint recovery: skip already-completed tools
    from ..recovery.checkpoint_guard import get_guard
    guard = get_guard(state.get("session_id", ""))

    for tc in pending:
        tc_id = tc.get("tool_call_id", "")
        tc_params = tc.get("params", {})
        tc_name = tc["name"]

        # Idempotency: skip execution if already completed (crash recovery)
        if guard and guard.is_completed(tc_name, tc_params, tc_id):
            stored_obs = guard.get_observation(tc_name, tc_params, tc_id)
            if stored_obs:
                stored_obs["iteration"] = state.get("loop_count", 0)
                if tc_id:
                    stored_obs["tool_call_id"] = tc_id
                observations.append(stored_obs)

                # Emit checkpoint_skip audit event
                if runner and runner.step_store:
                    step_id = ""
                    last = runner.step_store.last_step()
                    if last:
                        step_id = last.id
                    runner.step_store.event_store.append(
                        iteration=state.get("loop_count", 0),
                        kind="checkpoint_skip",
                        payload={
                            "tool_name": tc_name,
                            "tool_call_id": tc_id,
                            "session_id": state.get("session_id", ""),
                            "step_id": step_id,
                        },
                    )
                continue

        tool_call = TC(name=tc["name"], params=tc.get("params", {}))
        result = coder.tool_executor.execute(tool_call, skip_permission=True)

        obs: dict[str, Any] = {
            "tool_name": result.tool_name,
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "rejected": result.rejected,
            "params": tc.get("params", {}),
            "error_type": result.meta.get("error_type", ""),
            "summary": result.meta.get("summary", "") or _fallback_summary(result),
            "recommended_next": result.meta.get("recommended_next", "") or _suggest_next_step(result),
            "files": result.meta.get("files", []),
            "iteration": state.get("loop_count", 0),
        }
        # Preserve tool_call_id for FC runner structured message path
        if tc.get("tool_call_id"):
            obs["tool_call_id"] = tc["tool_call_id"]
        observations.append(obs)

        # Write result into coder messages.
        # For FC runners: store structured records in the step store (tool_results)
        # instead of text-form to_message() which would corrupt the history.
        # The FC history rebuilds structured messages from step data via
        # AgentHistoryRebuilder.build_for_fc().
        if tc.get("tool_call_id") and _is_fc_runner(state):
            # FC path: persist structured data in step, not text in cur_messages
            if runner and runner.step_store:
                step = runner.step_store.last_step()
                if step:
                    step.tool_results.append({
                        "tool_call_id": tc["tool_call_id"],
                        "tool_name": result.tool_name,
                        "success": result.success,
                        "content": result.output or result.error or "",
                        "is_error": not result.success,
                        "rejected": result.rejected,
                    })
            # Also store assistant tool_call record if not already there
            if runner and runner.step_store:
                step = runner.step_store.last_step()
                if step:
                    existing_ids = {tc_r.get("tool_call_id") for tc_r in step.tool_calls}
                    if tc["tool_call_id"] not in existing_ids:
                        step.tool_calls.append({
                            "tool_call_id": tc["tool_call_id"],
                            "tool_name": tc["name"],
                            "arguments": tc.get("params", {}),
                        })
        else:
            # CoT / fallback path: text-form observation is correct
            coder.cur_messages.append(result.to_message())

        # Sync step store: write observation back to the current step
        if runner and runner.step_store:
            step = runner.step_store.last_step()
            if step and step.status == "parsed":
                tool_meta = {
                    "success": result.success,
                    "rejected": result.rejected,
                    "tool_name": result.tool_name,
                }
                if result.error:
                    tool_meta["error"] = result.error
                # v1.2: propagate structured fields into event payload
                summary = result.meta.get("summary", "")
                if summary:
                    tool_meta["summary"] = summary
                files = result.meta.get("files", [])
                if files:
                    tool_meta["files"] = files
                rec_next = result.meta.get("recommended_next", "")
                if rec_next:
                    tool_meta["recommended_next"] = rec_next
                error_type = result.meta.get("error_type", "")
                if error_type:
                    tool_meta["error_type"] = error_type
                runner._update_step_after_tool(
                    step,
                    observation=result.output or result.error or "",
                    tool_meta=tool_meta,
                    tool_error=not result.success,
                )

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


def verify_node(state: AgentGraphState) -> dict[str, Any]:
    """Run post-action verification tasks when files were modified.

    Only triggers in modes that support verification and when tool
    observations indicate file changes.  Results are stored as
    structured dicts in state['verification_results'].

    When verification failures are detected, invokes the recovery
    decision engine and appends RecoveryDecision to state.

    Verification and recovery events are emitted to the event store
    when a runner with step_store is available.
    """
    observations = state.get("tool_observations", [])
    mode = state.get("mode", "act")
    iteration = state.get("loop_count", 0)

    # Check if any tool modified files
    changed_files: list[str] = []
    for obs in observations:
        for f in obs.get("files", []):
            if f not in changed_files:
                changed_files.append(f)

    if not changed_files:
        return {"phase": "verifying"}

    from ..verification.policy import VerificationPolicy, select_verification_tasks, should_suppress_verification
    from ..verification.runner import run_verification_tasks

    root = state.get("root", ".")
    policy = VerificationPolicy()
    tasks = select_verification_tasks(mode, policy=policy, changed_files=changed_files)

    if not tasks:
        return {"phase": "verifying"}

    event_store = _get_event_store(state)

    # Debounce: suppress tasks that already failed in this iteration
    prior_vr = state.get("verification_results", [])
    prior_results_flat: list[dict] = []
    for vr_dict in prior_vr:
        for r in vr_dict.get("results", []):
            prior_results_flat.append({**r, "iteration": iteration})

    suppressed_count = 0
    run_tasks = []
    for task in tasks:
        if should_suppress_verification(task.task_id, iteration, prior_results_flat):
            suppressed_count += 1
            if event_store:
                event_store.append(
                    iteration=iteration,
                    kind="verification_suppressed",
                    payload={
                        "task_id": task.task_id,
                        "reason": "duplicate_failure_same_iteration",
                        "iteration": iteration,
                    },
                )
        else:
            run_tasks.append(task)

    if not run_tasks:
        return {"phase": "verifying"}

    # Emit verification_started
    if event_store:
        event_store.append(
            iteration=iteration,
            kind="verification_started",
            payload={
                "task_count": len(run_tasks),
                "changed_files": changed_files,
                "mode": mode,
                "suppressed_count": suppressed_count,
            },
        )

    round_ = run_verification_tasks(run_tasks, root=root, changed_files=changed_files)
    round_dict = round_.to_dict()

    existing_vr = list(state.get("verification_results", []))
    existing_vr.append(round_dict)

    result: dict[str, Any] = {
        "phase": "verifying",
        "verification_results": existing_vr,
    }

    # Emit individual verification_result events
    if event_store:
        for vr in round_.results:
            event_store.append(
                iteration=iteration,
                kind="verification_result",
                payload=vr.to_dict(),
            )

    # Run recovery decisions for verification failures
    if not round_.all_passed:
        from ..recovery.engine import decide_recovery_action
        from ..recovery.policy import RecoveryContext, RecoveryPolicy

        recovery_policy = RecoveryPolicy()
        recovery_decisions = list(state.get("recovery_decisions", []))

        # Resolve current step_id for traceability
        from ..runners import get_runner as _get_runner
        _runner = _get_runner(state.get("session_id", ""))
        step_id = ""
        if _runner and _runner.step_store:
            last = _runner.step_store.last_step()
            if last:
                step_id = last.id

        for vr in round_.results:
            if vr.ok:
                continue
            ctx = RecoveryContext(
                error_type="verification_failed",
                task_id=vr.task_id,
                is_required=_task_is_required(tasks, vr.task_id),
                detail=vr.error_message or vr.output_preview,
            )
            decision = decide_recovery_action(ctx, recovery_policy)
            decision.source_step_id = step_id
            decision.verification_task = vr.task_id
            recovery_decisions.append(decision.to_dict())

            # Emit recovery_decision event
            if event_store:
                event_store.append(
                    iteration=iteration,
                    kind="recovery_decision",
                    payload=decision.to_dict(),
                )

        result["recovery_decisions"] = recovery_decisions

    # Emit verification_finished
    if event_store:
        event_store.append(
            iteration=iteration,
            kind="verification_finished",
            payload={
                "all_passed": round_.all_passed,
                "pass_count": round_.pass_count,
                "fail_count": round_.fail_count,
                "error_count": round_.error_count,
            },
        )

    # Emit recovery_routed event for traceability
    # This runs in verify_node so it fires regardless of whether
    # route_after_verify is called through the graph or directly.
    if event_store:
        decisions = result.get("recovery_decisions", [])
        target = "continue"
        route_reason = "all_passed" if round_.all_passed else "has_retry_or_fallback"
        if decisions:
            for d in reversed(decisions):
                if d.get("action") == "halt":
                    target = "halt"
                    route_reason = d.get("reason", "halt")
                    break
        event_store.append(
            iteration=iteration,
            kind="recovery_routed",
            payload={
                "target": target,
                "reason": route_reason,
                "decision_count": len(decisions),
                "session_id": state.get("session_id", ""),
            },
        )

    return result


def _task_is_required(tasks: list, task_id: str) -> bool:
    """Check if a verification task is marked as required."""
    for t in tasks:
        if t.task_id == task_id:
            return t.required
    return False


def route_after_verify(state: AgentGraphState) -> str:
    """After verify_node: halt on unrecoverable failures, else continue.

    Inspects recovery_decisions written by verify_node:
    - Any ``"halt"`` decision -> route to summarize (stop the loop).
    - Otherwise -> continue to observe_tool_result (retry/fallback path).

    Writes ``last_recovery_route`` to state and emits ``recovery_routed``
    event for auditability.
    """
    decisions = state.get("recovery_decisions", [])

    if not decisions:
        state["last_recovery_route"] = {
            "target": "continue",
            "reason": "no_recovery_decisions",
            "decision_count": 0,
            "session_id": state.get("session_id", ""),
        }
        _emit_recovery_routed(state, "continue", "no_recovery_decisions", 0)
        return "continue"

    # Determine route from latest decisions
    target = "continue"
    reason = "all_retry_or_fallback"
    for d in reversed(decisions):
        if d.get("action") == "halt":
            target = "halt"
            reason = d.get("reason", "halt_decision")
            break

    state["last_recovery_route"] = {
        "target": target,
        "reason": reason,
        "decision_count": len(decisions),
        "session_id": state.get("session_id", ""),
    }

    _emit_recovery_routed(state, target, reason, len(decisions))
    return target


def _emit_recovery_routed(
    state: AgentGraphState,
    target: str,
    reason: str,
    decision_count: int,
) -> None:
    """Emit a recovery_routed event for tracing."""
    event_store = _get_event_store(state)
    if not event_store:
        return
    iteration = state.get("loop_count", 0)
    event_store.append(
        iteration=iteration,
        kind="recovery_routed",
        payload={
            "target": target,
            "reason": reason,
            "decision_count": decision_count,
            "session_id": state.get("session_id", ""),
        },
    )


def _get_event_store(state: AgentGraphState):
    """Get the event store from the runner's step store, if available."""
    try:
        from ..runners import get_runner as _get_runner
        runner = _get_runner(state.get("session_id", ""))
        if runner and hasattr(runner, "step_store") and runner.step_store:
            return runner.step_store.event_store
    except Exception:
        pass
    return None


def observe_tool_result(state: AgentGraphState) -> dict[str, Any]:
    """Write tool results back into messages and prepare for next model call.

    For FC runner: produces structured tool messages with tool_call_id.
    For CoT runner / fallback: produces textual user observations.
    """
    observations = state.get("tool_observations", [])
    messages = list(state.get("messages", []))

    is_fc = _is_fc_runner(state)

    for obs in observations:
        if is_fc and obs.get("tool_call_id"):
            # FC structured path: tool message with tool_call_id
            if obs.get("rejected"):
                content = "User rejected the tool call."
            elif obs.get("success"):
                content = obs.get("output", "")
            else:
                content = f"FAILED: {obs.get('error', '')}"
            messages.append({
                "role": "tool",
                "tool_call_id": obs["tool_call_id"],
                "content": content,
            })
        else:
            # CoT / fallback path: textual observation
            label = f"[{obs['tool_name']}]"
            if obs.get("rejected"):
                text = f"{label} REJECTED by user."
            elif obs.get("success"):
                output = obs.get("output", "").strip()
                text = f"{label} Result:\n{output}" if output else f"{label} OK (no output)."
            else:
                text = f"{label} FAILED:\n{obs.get('error', '')}"
            messages.append(dict(role="user", content=text))

    # Merge recovery hints from verify_node's recovery_decisions
    decisions = state.get("recovery_decisions", [])
    hints = [
        d["next_hint"] for d in decisions
        if d.get("action") in ("retry", "fallback") and d.get("next_hint")
    ]
    if hints:
        hint_text = "Recovery guidance: " + "; ".join(hints)
        messages.append({"role": "user", "content": hint_text})

    return {
        "messages": messages,
        "tool_observations": [],
    }


def _is_fc_runner(state: AgentGraphState) -> bool:
    """Check whether the current runner is function-calling type."""
    from ..runners import get_runner as _get_runner
    runner = _get_runner(state.get("session_id", ""))
    if runner and hasattr(runner, "_runner_type"):
        return runner._runner_type() == "function-calling"
    return False


def _serialize_tool_args(params: dict[str, Any]) -> str:
    """Serialize tool params for assistant.tool_calls history."""
    try:
        import json
        return json.dumps(params or {})
    except (TypeError, ValueError):
        return str(params or {})


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

def should_finish_for_mode(state: AgentGraphState) -> bool:
    """Mode-aware completion check.

    - sniff: finish when no tool calls and model has produced text
    - plan:  finish when no tool calls (allows prior read-only tool loops)
    - act:   never force-finish here (relies on max_loops / error state)
    """
    mode = state.get("mode", "act")
    pending = state.get("pending_tool_calls")

    if pending:
        return False

    # No pending tools — for read-only modes, one response is sufficient
    if mode in ("sniff", "plan"):
        return True

    return False


def route_after_model(state: AgentGraphState) -> str:
    """After model_node: go to tool parsing if tools present, else summarize.

    Mode-aware completion:
    - sniff/plan with no pending tools -> finish immediately (text answer is enough)
    - act with no pending tools -> finish (standard behaviour)
    - any mode with pending tools and within loop budget -> tools
    """
    pending = state.get("pending_tool_calls")
    loop = state.get("loop_count", 0)
    max_loops = state.get("max_loops", 5)

    # Check coder error state
    coder = _get_coder(state)
    if coder and coder.tool_exec_state.too_many_errors:
        return "finish"

    if pending and loop <= max_loops:
        return "tools"

    # No pending tools — apply mode-specific completion rule
    if should_finish_for_mode(state):
        return "finish"

    # act mode with no tools but not forced: still finish
    # (this is the pre-existing default — act without tools = done)
    return "finish"


def route_after_permission(state: AgentGraphState) -> str:
    """After permission_node: execute if tools remain, else deny/summarize."""
    pending = state.get("pending_tool_calls")
    if pending:
        return "execute"

    return "deny"


def route_after_observe(state: AgentGraphState) -> str:
    """After observe_tool_result: loop back to model or finish.

    Mode-aware: sniff/plan finish after tool results are observed because
    they only run read-only tools and don't need further loops unless the
    model explicitly requests more.  But if there are pending observations
    that the model hasn't seen yet, we should give the model a chance.

    act mode continues looping until max_loops.
    """
    loop = state.get("loop_count", 0)
    max_loops = state.get("max_loops", 5)

    coder = _get_coder(state)
    if coder and coder.tool_exec_state.too_many_errors:
        return "finish"

    if loop >= max_loops:
        return "finish"

    # sniff/plan: after observing read-only tool results, give the model
    # one more chance to produce a final answer (it may have more context now)
    mode = state.get("mode", "act")
    if mode in ("sniff", "plan"):
        # Allow one more model call so it can synthesize results,
        # but should_finish_for_mode will end it after that call
        # if no new tool calls are produced.
        return "continue"

    # act mode: standard loop
    return "continue"
