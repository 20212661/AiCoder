"""Replay builders — reconstruct history views from persisted events.

Replays events to produce runtime and LLM history views without depending
on in-process step store objects. Used for session resume and diagnostics.
"""
from __future__ import annotations

from typing import Any

from .types import AgentEventRecord


def replay_runtime_view(events: list[AgentEventRecord]) -> list[dict[str, Any]]:
    """Reconstruct runtime history view from events.

    Groups events by iteration and step_id, producing the same structure
    as ``build_runtime_history_view`` but purely from event data.
    """
    if not events:
        return []

    # Group by iteration -> step_id
    steps: dict[tuple[int, str], dict[str, Any]] = {}

    for ev in events:
        step_id = ev.payload.get("step_id", "")
        key = (ev.iteration, step_id)

        if key not in steps:
            steps[key] = {
                "iteration": ev.iteration,
                "step_id": step_id,
                "status": "created",
                "mode": "",
            }

        entry = steps[key]

        if ev.kind == "step_started":
            entry["status"] = "started"
            entry["mode"] = ev.payload.get("mode", "")
            entry["runner_type"] = ev.payload.get("runner_type", "")

        elif ev.kind == "assistant_thought":
            entry["thought"] = ev.payload.get("thought", "")

        elif ev.kind == "tool_call":
            entry["status"] = "parsed"
            entry["action"] = {
                "tool_name": ev.payload.get("tool_name", ""),
                "tool_input": ev.payload.get("tool_input", {}),
            }

        elif ev.kind == "tool_result":
            entry["status"] = "observed"
            obs: dict[str, Any] = {"output": ev.payload.get("observation", "")}
            meta = ev.payload.get("tool_meta", {})
            if meta:
                obs["tool_meta"] = meta
                obs["success"] = meta.get("success", True)
                obs["rejected"] = meta.get("rejected", False)
            else:
                obs["success"] = True
                obs["rejected"] = False
            files = ev.payload.get("files", [])
            if files:
                obs["files"] = files
            entry["observation"] = obs

        elif ev.kind == "tool_error":
            entry["status"] = "error"
            obs_err: dict[str, Any] = {
                "output": ev.payload.get("observation", ""),
                "error": ev.payload.get("error", ""),
                "success": False,
                "rejected": False,
            }
            meta = ev.payload.get("tool_meta", {})
            if meta:
                obs_err["tool_meta"] = meta
                obs_err["rejected"] = meta.get("rejected", False)
            entry["observation"] = obs_err

        elif ev.kind == "step_finished":
            entry["status"] = "final"
            fa = ev.payload.get("final_answer", "")
            if fa:
                entry["final_answer"] = fa

    # Sort by iteration
    result = sorted(steps.values(), key=lambda e: (e["iteration"], e.get("step_id", "")))
    return result


def replay_verification_trace(
    events: list[AgentEventRecord],
) -> list[dict[str, Any]]:
    """Reconstruct verification and recovery trace from events.

    Returns a list of trace entries, each representing one verification
    round with its results and any recovery decisions.
    """
    if not events:
        return []

    rounds: dict[int, dict[str, Any]] = {}
    results_by_iter: dict[int, list[dict]] = {}
    decisions_by_iter: dict[int, list[dict]] = {}

    for ev in events:
        if ev.kind == "verification_started":
            rounds[ev.iteration] = {
                "iteration": ev.iteration,
                "started": True,
                "task_count": ev.payload.get("task_count", 0),
                "changed_files": ev.payload.get("changed_files", []),
                "results": [],
                "decisions": [],
            }
            results_by_iter[ev.iteration] = []
            decisions_by_iter[ev.iteration] = []

        elif ev.kind == "verification_result":
            if ev.iteration not in results_by_iter:
                results_by_iter[ev.iteration] = []
            results_by_iter[ev.iteration].append(ev.payload)

        elif ev.kind == "recovery_decision":
            if ev.iteration not in decisions_by_iter:
                decisions_by_iter[ev.iteration] = []
            decisions_by_iter[ev.iteration].append(ev.payload)

        elif ev.kind == "verification_finished":
            if ev.iteration in rounds:
                rounds[ev.iteration]["finished"] = True
                rounds[ev.iteration]["all_passed"] = ev.payload.get("all_passed", False)
                rounds[ev.iteration]["pass_count"] = ev.payload.get("pass_count", 0)
                rounds[ev.iteration]["fail_count"] = ev.payload.get("fail_count", 0)
                rounds[ev.iteration]["error_count"] = ev.payload.get("error_count", 0)

    # Merge results and decisions into rounds
    for iteration, round_data in rounds.items():
        round_data["results"] = results_by_iter.get(iteration, [])
        round_data["decisions"] = decisions_by_iter.get(iteration, [])

    return sorted(rounds.values(), key=lambda r: r["iteration"])


def replay_llm_view(
    events: list[AgentEventRecord],
    done_messages: list[dict[str, Any]],
    runner_type: str = "cot",
) -> list[dict[str, Any]]:
    """Reconstruct LLM history view from events + done_messages.

    For CoT: produces user/assistant pairs from tool_call/tool_result events.
    For FC: produces assistant tool_calls + role=tool messages.

    Falls back to done_messages when events are insufficient.
    """
    if not events:
        return list(done_messages)

    messages = list(done_messages)
    replay_msgs = _replay_tool_messages(events, runner_type)

    if replay_msgs:
        messages.extend(replay_msgs)

    return messages


def _replay_tool_messages(
    events: list[AgentEventRecord],
    runner_type: str,
) -> list[dict[str, Any]]:
    """Replay tool call/result events into LLM-format messages."""
    messages: list[dict[str, Any]] = []

    # Collect tool_call and tool_result events in order
    for ev in events:
        if ev.kind == "tool_call":
            tool_name = ev.payload.get("tool_name", "")
            tool_input = ev.payload.get("tool_input", {})

            if runner_type == "function-calling":
                # FC: structured tool_calls in assistant message
                tc_id = ev.payload.get("tool_call_id", ev.event_id)
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": str(tool_input),
                        },
                    }],
                })
            else:
                # CoT: text-form thought + action
                thought = ""
                # Look for preceding thought event in same iteration
                for prev_ev in events:
                    if (prev_ev.iteration == ev.iteration
                            and prev_ev.kind == "assistant_thought"
                            and prev_ev.payload.get("step_id") == ev.payload.get("step_id")):
                        thought = prev_ev.payload.get("thought", "")
                        break
                content = thought if thought else f"Using {tool_name}"
                messages.append({"role": "assistant", "content": content})

        elif ev.kind == "tool_result":
            if runner_type == "function-calling":
                # Find the preceding tool_call to get the tool_call_id
                tc_id = ""
                for prev_ev in reversed(events):
                    if (prev_ev.kind == "tool_call"
                            and prev_ev.payload.get("step_id") == ev.payload.get("step_id")):
                        tc_id = prev_ev.payload.get("tool_call_id", prev_ev.event_id)
                        break
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": ev.payload.get("observation", ""),
                })
            else:
                tool_name = ""
                for prev_ev in reversed(events):
                    if (prev_ev.kind == "tool_call"
                            and prev_ev.payload.get("step_id") == ev.payload.get("step_id")):
                        tool_name = prev_ev.payload.get("tool_name", "tool")
                        break
                output = ev.payload.get("observation", "")
                messages.append({
                    "role": "user",
                    "content": f"[{tool_name}] Result: {output}",
                })

        elif ev.kind == "tool_error":
            if runner_type == "function-calling":
                tc_id = ""
                for prev_ev in reversed(events):
                    if (prev_ev.kind == "tool_call"
                            and prev_ev.payload.get("step_id") == ev.payload.get("step_id")):
                        tc_id = prev_ev.payload.get("tool_call_id", prev_ev.event_id)
                        break
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": ev.payload.get("error", ev.payload.get("observation", "")),
                })
            else:
                messages.append({
                    "role": "user",
                    "content": f"[tool] Error: {ev.payload.get('error', 'unknown')}",
                })

    return messages
