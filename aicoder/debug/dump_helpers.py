"""Debug dump helpers — structured inspection of pipeline outputs.

Each dump_* function returns a plain dict suitable for logging,
printing, or sending to external diagnostics systems.

Usage:
    from aicoder.debug.dump_helpers import (
        dump_llm_history_view,
        dump_runtime_history_view,
        dump_packed_context,
        dump_condensation_state,
    )
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..coders.base_coder import Coder


def dump_llm_history_view(
    coder: "Coder",
    mode: str,
    runner_type: str,
) -> dict[str, Any]:
    """Dump the LLM history view as a structured dict.

    Returns:
        dict with keys: message_count, messages (list of role+content preview),
        has_condensed, condensed_summary_preview
    """
    from ..context.history_view import build_llm_history_view

    view = build_llm_history_view(coder, mode, runner_type)

    messages = []
    condensed_count = 0
    condensed_preview = ""

    for m in view:
        role = m.get("role", "")
        content = m.get("content", "")
        preview = content[:200] if content else "(empty)"
        entry = {"role": role, "preview": preview}
        if m.get("condensed"):
            entry["condensed"] = True
            entry["covered_event_ids"] = m.get("covered_event_ids", [])
            condensed_count += 1
            if not condensed_preview:
                condensed_preview = content[:300]
        messages.append(entry)

    return {
        "message_count": len(view),
        "messages": messages,
        "has_condensed": condensed_count > 0,
        "condensed_summary_preview": condensed_preview,
    }


def dump_runtime_history_view(
    coder: "Coder",
    mode: str,
    runner_type: str,
) -> dict[str, Any]:
    """Dump the runtime history view as a structured dict.

    Returns:
        dict with keys: step_count, steps (list of step summaries)
    """
    from ..context.history_view import build_runtime_history_view

    view = build_runtime_history_view(coder, mode, runner_type)

    steps = []
    for entry in view:
        summary: dict[str, Any] = {
            "iteration": entry.get("iteration"),
            "step_id": entry.get("step_id"),
            "status": entry.get("status"),
            "mode": entry.get("mode"),
        }
        if entry.get("thought"):
            summary["thought_preview"] = entry["thought"][:100]
        if entry.get("action"):
            summary["action_tool"] = entry["action"].get("tool_name")
        if entry.get("observation"):
            obs = entry["observation"]
            summary["observation_success"] = obs.get("success")
            summary["observation_rejected"] = obs.get("rejected", False)
        if entry.get("final_answer"):
            summary["final_answer_preview"] = entry["final_answer"][:100]
        steps.append(summary)

    return {
        "step_count": len(view),
        "steps": steps,
    }


def dump_packed_context(
    coder: "Coder",
    user_input: str,
    mode: str,
    runner_type: str,
) -> dict[str, Any]:
    """Dump the packed context as a structured dict.

    Returns:
        dict with keys: system_count, conversation_count, total_tokens,
        system_messages, conversation_previews
    """
    from ..context.packer import pack_context

    packed = pack_context(coder, user_input, mode, runner_type)

    system_previews = [
        {"role": m.get("role", ""), "content_length": len(m.get("content", "") or "")}
        for m in packed.system_messages
    ]

    conv_previews = []
    for m in packed.conversation_messages:
        content = m.get("content", "") or ""
        preview = {
            "role": m.get("role", ""),
            "content_length": len(content),
        }
        if m.get("condensed"):
            preview["condensed"] = True
        if m.get("_trace_trimmed"):
            preview["trace_trimmed"] = True
        conv_previews.append(preview)

    total_chars = sum(
        len(m.get("content", "") or "") for m in packed.all_messages
    )

    trace = packed._layer_trace

    # Repo layer info
    repo_start = trace.get("repo_start", 0)
    repo_end = trace.get("repo_end", 0)
    repo_info: dict[str, Any] = {}
    if repo_end > repo_start:
        repo_msgs = packed.conversation_messages[repo_start:repo_end]
        repo_info = {
            "count": len(repo_msgs),
            "tokens": sum(len(m.get("content", "") or "") // 4 for m in repo_msgs),
            "selected_file_count": trace.get("repo_count", 0),
            "budget_tokens": trace.get("repo_budget_tokens", 0),
        }

    # Focused files layer info
    focused_info: dict[str, Any] = {
        "tokens_before": trace.get("focused_file_tokens_before", 0),
        "tokens_after": trace.get("focused_file_tokens_after", 0),
        "preference": trace.get("policy_focused_pref", ""),
    }

    return {
        "system_count": len(packed.system_messages),
        "conversation_count": len(packed.conversation_messages),
        "total_count": len(packed.all_messages),
        "total_tokens_approx": total_chars // 4,
        "system_messages": system_previews,
        "conversation_previews": conv_previews,
        "repo_layer": repo_info,
        "focused_files_layer": focused_info,
    }


def dump_condensation_state(
    coder: "Coder",
    mode: str,
) -> dict[str, Any]:
    """Dump the condensation pipeline state.

    Returns:
        dict with keys: events_available, threshold, triggered,
        pruned_stats, summary_stats, warnings
    """
    from ..context.history_view import _get_event_records, _CONDENSE_MIN_EVENTS
    from ..context.condense import (
        prune_history_events,
        summarize_history_events,
    )

    events = _get_event_records(coder)

    if not events:
        return {
            "events_available": 0,
            "threshold": _CONDENSE_MIN_EVENTS,
            "triggered": False,
            "reason": "no events",
        }

    triggered = len(events) >= _CONDENSE_MIN_EVENTS
    pruned = prune_history_events(events, mode)

    truncated = sum(
        1 for ev in pruned if ev.payload.get("observation_truncated")
    )

    result: dict[str, Any] = {
        "events_available": len(events),
        "threshold": _CONDENSE_MIN_EVENTS,
        "triggered": triggered,
        "pruned_stats": {
            "total": len(pruned),
            "truncated_observations": truncated,
        },
    }

    if triggered:
        block = summarize_history_events(pruned)
        if block:
            result["summary_stats"] = {
                "length_chars": len(block.summary),
                "covered_events": len(block.covered_event_ids),
                "sections": _extract_sections(block.summary),
            }
        else:
            result["summary_stats"] = {"produced": False}
    else:
        result["reason"] = f"events ({len(events)}) < threshold ({_CONDENSE_MIN_EVENTS})"

    return result


def _extract_sections(summary: str) -> list[str]:
    """Extract section names from a condensation summary."""
    sections = []
    for marker in [
        "Goal:", "Actions taken:", "Findings:", "Failures:",
        "Next steps:", "Files touched:", "Conclusion:",
    ]:
        if marker in summary:
            sections.append(marker.rstrip(":"))
    return sections


def dump_repo_context(
    coder: "Coder",
    mode: str,
) -> dict[str, Any]:
    """Dump repo context construction details.

    Returns:
        dict with keys: mode, budget_tokens, selected_count, top_files,
        token_estimate, rendered_preview
    """
    from ..context.policies import get_context_budget_for_mode
    from ..context.repo_ranker import rank_repo_files
    from ..context.repo_renderer import render_repo_context

    budget = get_context_budget_for_mode(mode)
    budget_tokens = budget.repo_map_tokens

    try:
        ranked = rank_repo_files(coder, mode)
        result = render_repo_context(ranked, budget_tokens, mode)
    except Exception as e:
        return {
            "mode": mode,
            "budget_tokens": budget_tokens,
            "error": str(e),
        }

    top_files = [
        {"path": h.path, "reason": h.reason, "score": h.score}
        for h in ranked[:10]
    ]

    rendered_preview = ""
    if result.rendered_messages:
        rendered_preview = result.rendered_messages[0].get("content", "")[:500]

    return {
        "mode": mode,
        "budget_tokens": budget_tokens,
        "selected_count": len(result.files),
        "candidate_count": len(ranked),
        "top_files": top_files,
        "token_estimate": result.token_estimate,
        "rendered_preview": rendered_preview,
    }


def dump_event_store(coder: "Coder") -> dict[str, Any]:
    """Dump event store state for diagnostics.

    Returns:
        dict with keys: event_count, backend_type, event_kinds,
        persisted, session_id, iteration_range
    """
    from ..context.history_view import _get_event_records, _get_runner
    from ..events.backend import InMemoryEventBackend
    from ..events.file_store import FileEventBackend

    session_id = getattr(coder, "session_id", "unknown")
    events = _get_event_records(coder)

    # Determine backend type
    backend_type = "unknown"
    persisted = False
    runner = _get_runner(coder)
    if runner and hasattr(runner, "step_store") and runner.step_store:
        backend = runner.step_store.event_store.backend
        if isinstance(backend, FileEventBackend):
            backend_type = "file"
            persisted = True
        elif isinstance(backend, InMemoryEventBackend):
            backend_type = "memory"

    # Count by kind
    kind_counts: dict[str, int] = {}
    for ev in events:
        kind_counts[ev.kind] = kind_counts.get(ev.kind, 0) + 1

    # Iteration range
    iterations = [ev.iteration for ev in events] if events else []
    iteration_range = (
        f"{min(iterations)}-{max(iterations)}" if iterations else "none"
    )

    return {
        "session_id": session_id,
        "event_count": len(events),
        "backend_type": backend_type,
        "persisted": persisted,
        "event_kinds": kind_counts,
        "iteration_range": iteration_range,
    }


def dump_replay_runtime_view(
    coder: "Coder",
    mode: str,
) -> dict[str, Any]:
    """Dump replay-based runtime view for diagnostics.

    Reconstructs runtime view from persisted events without depending
    on in-process step objects.

    Returns:
        dict with keys: step_count, steps (summary list), event_count
    """
    from ..context.history_view import _get_event_records
    from ..events.replay import replay_runtime_view

    events = _get_event_records(coder)
    runtime = replay_runtime_view(events)

    step_summaries = []
    for entry in runtime[:10]:
        summary: dict[str, Any] = {
            "iteration": entry.get("iteration"),
            "status": entry.get("status"),
        }
        if entry.get("thought"):
            summary["thought_preview"] = entry["thought"][:80]
        action = entry.get("action")
        if action:
            summary["tool_name"] = action.get("tool_name")
        obs = entry.get("observation")
        if obs:
            summary["observation_success"] = obs.get("success")
        step_summaries.append(summary)

    return {
        "event_count": len(events),
        "step_count": len(runtime),
        "steps": step_summaries,
    }


def dump_replay_llm_view(
    coder: "Coder",
    mode: str,
    runner_type: str,
) -> dict[str, Any]:
    """Dump replay-based LLM view for diagnostics.

    Reconstructs LLM history view from persisted events + done_messages.

    Returns:
        dict with keys: message_count, event_count, source, messages (preview)
    """
    from ..context.history_view import _get_event_records
    from ..events.replay import replay_llm_view

    events = _get_event_records(coder)
    done_messages = list(getattr(coder, "done_messages", []))

    messages = replay_llm_view(events, done_messages, runner_type=runner_type)

    msg_previews = []
    for m in messages[:10]:
        preview: dict[str, Any] = {
            "role": m.get("role", ""),
            "content_length": len(m.get("content", "") or ""),
        }
        if m.get("tool_calls"):
            preview["has_tool_calls"] = True
        if m.get("tool_call_id"):
            preview["tool_call_id"] = m["tool_call_id"]
        msg_previews.append(preview)

    return {
        "message_count": len(messages),
        "event_count": len(events),
        "source": "replay" if events else "done_messages",
        "messages": msg_previews,
    }


def dump_summary_blocks(
    coder: "Coder",
    mode: str,
) -> dict[str, Any]:
    """Dump summary block state for diagnostics.

    Returns:
        dict with keys: snapshot_available, snapshot_id, blocks, source,
        block_count, covered_event_count
    """
    session_id = getattr(coder, "session_id", "")
    root = getattr(coder, "root", "")

    result: dict[str, Any] = {
        "snapshot_available": False,
        "blocks": [],
        "block_count": 0,
        "source": "none",
    }

    if not session_id or not root:
        return result

    try:
        from ..context.summary_store import load_latest_snapshot
        snapshot = load_latest_snapshot(session_id, root)
        if snapshot is None:
            return result

        result["snapshot_available"] = True
        result["snapshot_id"] = snapshot.snapshot_id
        result["source_event_count"] = snapshot.source_event_count
        result["latest_event_id"] = snapshot.latest_event_id
        result["mode"] = snapshot.mode
        result["created_at"] = snapshot.created_at
        result["block_count"] = len(snapshot.blocks)
        result["source"] = "persisted"

        for block in snapshot.blocks:
            result["blocks"].append({
                "summary_id": block.summary_id,
                "kind": block.kind,
                "covered_event_count": len(block.covered_event_ids),
                "covered_iterations": block.covered_iterations,
                "goal": block.goal,
                "findings_count": len(block.findings),
                "actions_count": len(block.actions_taken),
                "failures_count": len(block.failures),
                "files_touched_count": len(block.files_touched),
                "next_steps_count": len(block.next_steps),
            })
    except Exception as e:
        result["error"] = str(e)

    return result


def dump_snapshot_state(
    coder: "Coder",
    mode: str,
) -> dict[str, Any]:
    """Dump snapshot reuse state for diagnostics.

    Returns:
        dict with keys: snapshot_reused, snapshot_id, coverage,
        uncovered_event_count, source
    """
    session_id = getattr(coder, "session_id", "")
    root = getattr(coder, "root", "")

    result: dict[str, Any] = {
        "snapshot_reused": False,
        "source": "none",
    }

    if not session_id or not root:
        return result

    try:
        from ..context.summary_store import load_latest_snapshot
        snapshot = load_latest_snapshot(session_id, root)
        if snapshot is None:
            return result

        result["snapshot_id"] = snapshot.snapshot_id
        result["snapshot_reused"] = True
        result["source"] = "persisted"

        from ..context.history_view import _get_event_records
        events = _get_event_records(coder)

        from ..context.snapshot import (
            snapshot_covers_events,
            count_uncovered_events,
        )
        result["coverage"] = "full" if snapshot_covers_events(snapshot, events) else "partial"
        result["total_events"] = len(events)
        result["uncovered_event_count"] = count_uncovered_events(snapshot, events)
        result["snapshot_event_count"] = snapshot.source_event_count

    except Exception as e:
        result["error"] = str(e)

    return result


def dump_tool_trace_retention(
    coder: "Coder",
    mode: str,
) -> dict[str, Any]:
    """Dump tool trace retention policy decisions for diagnostics.

    Returns:
        dict with keys: total_traces, must_keep, summarize_only,
        trim_aggressively, retention_ratio, decisions
    """
    from ..context.history_view import _get_event_records
    from ..context.tool_trace_policy import decide_tool_trace_retention

    events = _get_event_records(coder)
    report = decide_tool_trace_retention(events, mode)

    result: dict[str, Any] = {
        "total_traces": report.total_traces,
        "must_keep": report.must_keep,
        "summarize_only": report.summarize_only,
        "trim_aggressively": report.trim_aggressively,
        "retention_ratio": report.retention_ratio,
    }

    # Summarize decisions (don't dump all — just top categories)
    must_keep_reasons: list[str] = []
    for d in report.decisions[:20]:
        if d.tier.value == "must_keep":
            must_keep_reasons.append(d.reason)
        result.setdefault(f"{d.tier.value}_sample_reasons", []).append(d.reason)

    return result


def dump_verification_metrics(coder: "Coder") -> dict[str, Any]:
    """Dump verification quality metrics from persisted events.

    Returns:
        dict with keys: task_count, pass_count, fail_count, error_count,
        pass_rate, fail_rate, mean_duration_ms, rounds, by_task
    """
    from ..context.history_view import _get_event_records

    events = _get_event_records(coder)
    v_results = [ev for ev in events if ev.kind == "verification_result"]
    v_finished = [ev for ev in events if ev.kind == "verification_finished"]

    if not v_results:
        return {
            "task_count": 0,
            "pass_count": 0,
            "fail_count": 0,
            "error_count": 0,
            "pass_rate": 0.0,
            "fail_rate": 0.0,
            "mean_duration_ms": 0,
            "rounds": 0,
            "by_task": {},
        }

    pass_count = sum(1 for ev in v_results if ev.payload.get("status") == "passed")
    fail_count = sum(1 for ev in v_results if ev.payload.get("status") == "failed")
    error_count = sum(1 for ev in v_results if ev.payload.get("status") == "error")
    skip_count = sum(1 for ev in v_results if ev.payload.get("status") == "skipped")
    total = len(v_results)

    durations = [ev.payload.get("duration_ms", 0) for ev in v_results]
    mean_duration = sum(durations) / len(durations) if durations else 0

    by_task: dict[str, dict[str, int]] = {}
    for ev in v_results:
        task_id = ev.payload.get("task_id", "unknown")
        status = ev.payload.get("status", "unknown")
        if task_id not in by_task:
            by_task[task_id] = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "total": 0}
        by_task[task_id][status] = by_task[task_id].get(status, 0) + 1
        by_task[task_id]["total"] += 1

    return {
        "task_count": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "skip_count": skip_count,
        "pass_rate": round(pass_count / total, 3) if total else 0.0,
        "fail_rate": round(fail_count / total, 3) if total else 0.0,
        "mean_duration_ms": round(mean_duration, 1),
        "rounds": len(v_finished),
        "by_task": by_task,
    }


def dump_recovery_metrics(coder: "Coder") -> dict[str, Any]:
    """Dump recovery action metrics from persisted events.

    Returns:
        dict with keys: total_decisions, retry_count, fallback_count,
        halt_count, retry_rate, halt_rate, by_error_type
    """
    from ..context.history_view import _get_event_records

    events = _get_event_records(coder)
    decisions = [ev for ev in events if ev.kind == "recovery_decision"]

    if not decisions:
        return {
            "total_decisions": 0,
            "retry_count": 0,
            "fallback_count": 0,
            "halt_count": 0,
            "retry_rate": 0.0,
            "halt_rate": 0.0,
            "by_error_type": {},
        }

    retry_count = sum(1 for ev in decisions if ev.payload.get("action") == "retry")
    fallback_count = sum(1 for ev in decisions if ev.payload.get("action") == "fallback")
    halt_count = sum(1 for ev in decisions if ev.payload.get("action") == "halt")
    total = len(decisions)

    return {
        "total_decisions": total,
        "retry_count": retry_count,
        "fallback_count": fallback_count,
        "halt_count": halt_count,
        "retry_rate": round(retry_count / total, 3) if total else 0.0,
        "halt_rate": round(halt_count / total, 3) if total else 0.0,
    }


def dump_quality_summary(coder: "Coder") -> dict[str, Any]:
    """Dump combined quality metrics summary.

    Returns:
        dict with keys: verification, recovery, health, checkpoint_skip_count,
        verification_suppressed_count
    """
    from ..context.history_view import _get_event_records

    v = dump_verification_metrics(coder)
    r = dump_recovery_metrics(coder)

    events = _get_event_records(coder)
    skip_metrics = dump_checkpoint_skip_metrics(events)
    suppressed_count = sum(1 for ev in events if ev.kind == "verification_suppressed")

    # Derive health assessment
    health = "healthy"
    if v["fail_rate"] > 0.5:
        health = "degraded"
    if r["halt_rate"] > 0.5 and r["total_decisions"] > 0:
        health = "degraded"
    if v["fail_rate"] > 0.8:
        health = "critical"

    return {
        "verification": v,
        "recovery": r,
        "health": health,
        "checkpoint_skip_count": skip_metrics["skipped_duplicate_tool_calls"],
        "verification_suppressed_count": suppressed_count,
    }


def dump_checkpoint_skip_metrics(
    events: list,
) -> dict[str, Any]:
    """Count checkpoint_skip events for audit trail.

    Args:
        events: List of AgentEventRecord to scan.

    Returns:
        dict with keys: skipped_duplicate_tool_calls, by_tool
    """
    skip_events = [ev for ev in events if ev.kind == "checkpoint_skip"]
    by_tool: dict[str, int] = {}
    for ev in skip_events:
        tool = ev.payload.get("tool_name", "unknown")
        by_tool[tool] = by_tool.get(tool, 0) + 1

    return {
        "skipped_duplicate_tool_calls": len(skip_events),
        "by_tool": by_tool,
    }
