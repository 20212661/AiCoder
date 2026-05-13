"""Context observability — trace what goes into the LLM context.

Produces a structured report based on the actual output of pack_context(),
showing per-layer token counts, condensation decisions, and budget usage.

v1.2.3: Now calls pack_context() internally to produce an accurate picture
of the complete LLM input, including system messages, repo context, chat
files, current messages, and user input — not just the history subset.

Usage:
    from aicoder.debug.context_trace import trace_context

    report = trace_context(coder, "act", "cot", user_input="fix the bug")
    print(report["summary"])
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..coders.base_coder import Coder


def trace_context(
    coder: "Coder",
    mode: str,
    runner_type: str,
    *,
    user_input: str = "",
) -> dict[str, Any]:
    """Produce a structured trace of context construction.

    Internally calls pack_context() to get the real final LLM input,
    then reports per-layer statistics from the packed output.

    Returns a dict with:
    - layers: per-layer message counts and token estimates
    - condensation: whether condensation was applied
    - budget: budget allocation
    - summary: human-readable one-line summary
    """
    report: dict[str, Any] = {
        "layers": {},
        "condensation": {},
        "budget": {},
    }

    # 1. Call pack_context() for the real final output
    from ..context.packer import pack_context
    packed = pack_context(coder, user_input, mode, runner_type)

    trace = packed._layer_trace
    session_id = getattr(coder, "session_id", "")
    root = getattr(coder, "root", "")

    # 2. System layer
    system_count = len(packed.system_messages)
    system_tokens = _approx_tokens(packed.system_messages)
    report["layers"]["system"] = {
        "count": system_count,
        "tokens": system_tokens,
    }

    # 3. Per-layer extraction from conversation_messages via trace offsets
    conv = packed.conversation_messages

    # Repo context
    repo_start = trace.get("repo_start", 0)
    repo_end = trace.get("repo_end", 0)
    repo_msgs = conv[repo_start:repo_end]
    report["layers"]["repo"] = {
        "count": len(repo_msgs),
        "tokens": _approx_tokens(repo_msgs),
    }

    # History
    hist_start = trace.get("history_start", 0)
    hist_end = trace.get("history_end", 0)
    hist_msgs = conv[hist_start:hist_end]
    report["layers"]["history"] = {
        "count": len(hist_msgs),
        "tokens": _approx_tokens(hist_msgs),
    }
    report["layers"]["history_source"] = _detect_history_source(coder, mode, runner_type)

    # Chat files
    cf_start = trace.get("chat_files_start", hist_end)
    cf_end = trace.get("chat_files_end", hist_end)
    cf_msgs = conv[cf_start:cf_end]
    report["layers"]["chat_files"] = {
        "count": len(cf_msgs),
        "tokens": _approx_tokens(cf_msgs),
    }

    # Current messages
    cur_start = trace.get("current_start", cf_end)
    cur_end = trace.get("current_end", cf_end)
    cur_msgs = conv[cur_start:cur_end]
    report["layers"]["current"] = {
        "count": len(cur_msgs),
        "tokens": _approx_tokens(cur_msgs),
    }

    # User input
    ui_start = trace.get("user_input_start", cur_end)
    ui_end = trace.get("user_input_end", cur_end)
    ui_msgs = conv[ui_start:ui_end]
    report["layers"]["user_input"] = {
        "count": len(ui_msgs),
        "tokens": _approx_tokens(ui_msgs),
    }

    # Total
    total_count = len(packed.all_messages)
    total_tokens = system_tokens + _approx_tokens(conv)
    report["layers"]["total"] = {
        "count": total_count,
        "tokens": total_tokens,
    }

    # 3b. Repo context details
    repo_selected = trace.get("repo_count", 0)
    repo_budget = trace.get("repo_budget_tokens", 0)
    repo_estimated = trace.get("repo_token_estimate", 0)
    report["repo"] = {
        "selected_count": repo_selected,
        "budget_tokens": repo_budget,
        "token_estimate": repo_estimated,
        "utilization": (
            f"{repo_estimated}/{repo_budget}" if repo_budget > 0 else "n/a"
        ),
        "top_reasons": _extract_repo_reasons(conv, repo_start, repo_end),
    }

    # 3c. Focused file budget details
    from ..context.policies import get_context_budget_for_mode
    budget = get_context_budget_for_mode(mode)

    ff_before = trace.get("focused_file_tokens_before", 0)
    ff_after = trace.get("focused_file_tokens_after", 0)
    report["focused_files"] = {
        "tokens_before_trim": ff_before,
        "tokens_after_trim": ff_after,
        "budget": budget.focused_file_tokens,
        "preference": trace.get("policy_focused_pref", ""),
        "trimmed": ff_after < ff_before,
    }

    # 4. Budget allocation
    report["budget"]["history_tokens"] = budget.history_tokens
    report["budget"]["tool_trace_tokens"] = budget.tool_trace_tokens
    report["budget"]["focused_file_tokens"] = budget.focused_file_tokens
    report["budget"]["repo_map_tokens"] = budget.repo_map_tokens

    hist_tokens = report["layers"]["history"]["tokens"]
    report["budget"]["history_utilization"] = (
        f"{hist_tokens}/{budget.history_tokens}"
        if budget.history_tokens > 0 else "unlimited"
    )

    # 5. Condensation analysis
    events = _get_events(coder)
    steps = _get_steps(coder)
    report["layers"]["event_count"] = len(events)
    report["layers"]["step_count"] = len(steps)

    from ..context.history_view import _CONDENSE_MIN_EVENTS
    report["condensation"]["threshold"] = _CONDENSE_MIN_EVENTS
    report["condensation"]["events_available"] = len(events)
    report["condensation"]["triggered"] = len(events) >= _CONDENSE_MIN_EVENTS

    # Check if condensed messages appear in the packed output
    condensed_msgs = [m for m in conv if isinstance(m, dict) and m.get("condensed")]
    report["condensation"]["applied"] = len(condensed_msgs) > 0

    if len(events) >= _CONDENSE_MIN_EVENTS:
        from ..context.condense import (
            prune_history_events,
            summarize_history_events,
        )
        pruned = prune_history_events(events, mode)
        block = summarize_history_events(pruned)
        report["condensation"]["summary_length"] = len(block.summary) if block else 0
        report["condensation"]["covered_event_ids"] = len(block.covered_event_ids) if block else 0
    else:
        report["condensation"]["summary_length"] = 0
        report["condensation"]["covered_event_ids"] = 0

    # 5b. Event source info
    from ..events.backend import InMemoryEventBackend
    from ..events.file_store import FileEventBackend
    event_source = "unknown"
    events_persisted = False
    try:
        from ..context.history_view import _get_runner
        runner = _get_runner(coder)
        if runner and hasattr(runner, "step_store") and runner.step_store:
            backend = runner.step_store.event_store.backend
            if isinstance(backend, FileEventBackend):
                event_source = "file"
                events_persisted = True
            elif isinstance(backend, InMemoryEventBackend):
                event_source = "memory"
    except Exception:
        pass
    report["event_source"] = {
        "type": event_source,
        "persisted": events_persisted,
        "event_count": len(events),
    }

    # 5c. Snapshot state (v1.5)
    snapshot_info: dict[str, Any] = {"available": False}
    if session_id and root:
        try:
            from ..context.summary_store import load_latest_snapshot
            from ..context.snapshot import snapshot_covers_events, count_uncovered_events
            snapshot = load_latest_snapshot(session_id, root)
            if snapshot is not None:
                snapshot_info = {
                    "available": True,
                    "snapshot_id": snapshot.snapshot_id,
                    "source_event_count": snapshot.source_event_count,
                    "block_count": len(snapshot.blocks),
                    "coverage": "full" if snapshot_covers_events(snapshot, events) else "partial",
                    "uncovered_event_count": count_uncovered_events(snapshot, events),
                }
        except Exception:
            pass
    report["snapshot"] = snapshot_info

    # 5d. Tool trace retention stats (v1.5)
    retention_info: dict[str, Any] = {"total_traces": 0}
    if events:
        try:
            from ..context.tool_trace_policy import decide_tool_trace_retention
            retention_report = decide_tool_trace_retention(events, mode)
            retention_info = {
                "total_traces": retention_report.total_traces,
                "must_keep": retention_report.must_keep,
                "summarize_only": retention_report.summarize_only,
                "trim_aggressively": retention_report.trim_aggressively,
                "retention_ratio": retention_report.retention_ratio,
            }
        except Exception:
            pass
    report["tool_trace_retention"] = retention_info

    # 5e. Verification and recovery metrics (v1.6)
    v_metrics: dict[str, Any] = {"task_count": 0, "pass_rate": 0.0, "recent_tasks": []}
    r_metrics: dict[str, Any] = {"total_decisions": 0, "last_action": ""}
    if events:
        try:
            from .dump_helpers import dump_verification_metrics, dump_recovery_metrics, dump_checkpoint_skip_metrics
            v_metrics = dump_verification_metrics(coder)
            r_metrics = dump_recovery_metrics(coder)

            # v1.6.1: recent verification tasks
            recent_tasks = list({
                ev.payload.get("task_id", "")
                for ev in events
                if ev.kind == "verification_result" and ev.payload.get("task_id")
            })
            v_metrics["recent_tasks"] = recent_tasks

            # v1.6.1: last recovery action
            last_recovery = None
            for ev in reversed(events):
                if ev.kind == "recovery_decision":
                    last_recovery = ev.payload
                    break
            r_metrics["last_action"] = last_recovery.get("action", "") if last_recovery else ""
        except Exception:
            pass
    report["verification"] = v_metrics
    report["recovery"] = r_metrics

    # 5f. Checkpoint skip info (v1.6.1)
    checkpoint_info: dict[str, Any] = {"last_skip": None}
    if events:
        try:
            from .dump_helpers import dump_checkpoint_skip_metrics
            skip_metrics = dump_checkpoint_skip_metrics(events)
            checkpoint_info["skip_count"] = skip_metrics["skipped_duplicate_tool_calls"]
            checkpoint_info["by_tool"] = skip_metrics["by_tool"]
            # Last skip event
            for ev in reversed(events):
                if ev.kind == "checkpoint_skip":
                    checkpoint_info["last_skip"] = ev.payload
                    break
        except Exception:
            pass
    report["checkpoint"] = checkpoint_info

    # 6. Summary
    condensed_status = "condensed" if report["condensation"]["applied"] else "full"
    snapshot_status = "snapshot=yes" if snapshot_info.get("available") else "snapshot=no"
    report["summary"] = (
        f"Packed context: {total_tokens} tokens in {total_count} messages "
        f"({condensed_status}), {snapshot_status}, "
        f"system={system_tokens} hist={hist_tokens} "
        f"repo={report['layers']['repo']['tokens']} "
        f"files={report['layers']['chat_files']['tokens']} "
        f"current={report['layers']['current']['tokens']} "
        f"user_input={report['layers']['user_input']['tokens']}"
    )

    return report


def _detect_history_source(coder: "Coder", mode: str, runner_type: str) -> str:
    """Detect what source the history view uses."""
    try:
        from ..context.history_view import _get_runner
        runner = _get_runner(coder)
        if runner and hasattr(runner, "build_history_messages"):
            return "runner.build_history_messages"
    except Exception:
        pass
    return "done_messages"


def _get_events(coder: "Coder") -> list:
    """Get event records from coder's runner."""
    try:
        from ..context.history_view import _get_event_records
        return _get_event_records(coder)
    except Exception:
        return []


def _get_steps(coder: "Coder") -> list:
    """Get step records from coder's runner."""
    try:
        from ..context.history_view import _get_step_records
        return _get_step_records(coder)
    except Exception:
        return []


def _approx_tokens(messages: list[dict]) -> int:
    """Rough token estimate."""
    total = 0
    for m in messages:
        content = m.get("content", "")
        if content:
            total += len(content)
    return total // 4


def _extract_repo_reasons(messages: list[dict], start: int, end: int) -> list[dict[str, str]]:
    """Extract top file reasons from repo context messages."""
    reasons: list[dict[str, str]] = []
    for msg in messages[start:end]:
        content = msg.get("content", "")
        for line in content.split("\n"):
            if line.startswith("- "):
                parts = line.split(" — ", 1)
                if len(parts) == 2:
                    reasons.append({"path": parts[0][2:], "reason": parts[1]})
    return reasons[:5]
