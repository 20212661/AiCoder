"""History View — three separate views of agent execution history.

UI view:        verbose, includes lifecycle events, step metadata
Runtime view:   structured action/observation from step records
LLM view:       minimal, only what the model needs for the next call

The LLM view reuses existing v1.1 infrastructure (AgentHistoryRebuilder,
runner.build_history_messages()) rather than re-implementing FC/CoT logic.
Condensation (prune → summarize → replace) is applied ONLY to the LLM view.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..coders.base_coder import Coder


# -- Condensation threshold: only condense when history exceeds this many
#    events.  This prevents unnecessary work on short sessions.
_CONDENSE_MIN_EVENTS = 8


def build_ui_history_view(
    coder: "Coder",
    mode: str,
    runner_type: str,
) -> list[dict[str, Any]]:
    """Build a verbose history view for UI consumption.

    Includes step lifecycle events (step_started, step_finished),
    thoughts, observations, and metadata that the LLM does not need.
    No condensation is applied — the UI sees the full history.
    """
    events = _get_event_records(coder)
    steps = _get_step_records(coder)

    result: list[dict[str, Any]] = []

    # Start with base done_messages as text records
    for msg in coder.done_messages:
        result.append({
            "source": "done_messages",
            "role": msg.get("role", ""),
            "content": msg.get("content", ""),
        })

    if steps:
        result.extend(_ui_view_from_steps(steps, events))
    elif events:
        result.extend(_ui_view_from_events(events))

    return result


def _ui_view_from_steps(steps, events) -> list[dict[str, Any]]:
    """Build UI entries from AgentStep objects."""
    entries: list[dict[str, Any]] = []

    for step in steps:
        step_events = [e for e in events if e.payload.get("step_id") == step.id]
        if step.status == "created":
            continue

        entry: dict[str, Any] = {
            "source": "step",
            "iteration": step.iteration,
            "step_id": step.id,
            "mode": step.mode,
            "runner_type": step.runner_type,
            "status": step.status,
        }
        if step.thought:
            entry["thought"] = step.thought
        if step.action_name:
            entry["action_name"] = step.action_name
            entry["action_input"] = step.action_input
        if step.observation:
            entry["observation"] = step.observation
        if step.files:
            entry["files"] = step.files
        if step.error:
            entry["error"] = step.error
        if step.tool_meta:
            entry["tool_meta"] = step.tool_meta
        if step.final_answer:
            entry["final_answer"] = step.final_answer
        # Include lifecycle events for UI
        if step_events:
            entry["events"] = [
                {"kind": e.kind, "payload": e.payload}
                for e in step_events
            ]
        entries.append(entry)

    return entries


def _ui_view_from_events(events) -> list[dict[str, Any]]:
    """Build UI entries from replayed events (resume path)."""
    from ..events.replay import replay_runtime_view

    replayed = replay_runtime_view(events)
    entries: list[dict[str, Any]] = []

    for entry in replayed:
        ui_entry: dict[str, Any] = {
            "source": "step",
            "iteration": entry.get("iteration"),
            "step_id": entry.get("step_id"),
            "status": entry.get("status", ""),
            "mode": entry.get("mode", ""),
        }
        if entry.get("thought"):
            ui_entry["thought"] = entry["thought"]
        action = entry.get("action")
        if action:
            ui_entry["action_name"] = action.get("tool_name")
            ui_entry["action_input"] = action.get("tool_input")
        obs = entry.get("observation")
        if obs:
            ui_entry["observation"] = obs.get("output", "")
            if obs.get("files"):
                ui_entry["files"] = obs["files"]
            if obs.get("error"):
                ui_entry["error"] = obs["error"]
            ui_entry["tool_meta"] = {"success": obs.get("success", True)}
        if entry.get("final_answer"):
            ui_entry["final_answer"] = entry["final_answer"]
        entries.append(ui_entry)

    return entries


def build_runtime_history_view(
    coder: "Coder",
    mode: str,
    runner_type: str,
) -> list[dict[str, Any]]:
    """Build structured action/observation history for runtime consumers.

    Preserves structured action and observation data from step records,
    but does not include LLM-formatted messages or UI-level events.
    No condensation is applied — runtime sees the full structured data.
    """
    steps = _get_step_records(coder)

    if steps:
        return _runtime_view_from_steps(steps)

    # No step objects — try replay from persisted events
    events = _get_event_records(coder)
    if events:
        from ..events.replay import replay_runtime_view
        return replay_runtime_view(events)

    return []


def _runtime_view_from_steps(steps) -> list[dict[str, Any]]:
    """Build runtime view entries from AgentStep objects."""
    result: list[dict[str, Any]] = []

    for step in steps:
        if step.status == "created":
            continue

        entry: dict[str, Any] = {
            "iteration": step.iteration,
            "step_id": step.id,
            "status": step.status,
            "mode": step.mode,
        }

        if step.thought:
            entry["thought"] = step.thought

        # Structured action
        if step.action_name:
            entry["action"] = {
                "tool_name": step.action_name,
                "tool_input": step.action_input,
            }

        # Structured observation
        if step.status in ("observed", "error"):
            obs: dict[str, Any] = {}
            if step.observation:
                obs["output"] = step.observation
            if step.tool_meta:
                obs["tool_meta"] = step.tool_meta
            if step.files:
                obs["files"] = step.files
            if step.error:
                obs["error"] = step.error
            meta = step.tool_meta or {}
            obs["success"] = meta.get("success", step.status != "error")
            obs["rejected"] = meta.get("rejected", False)
            entry["observation"] = obs

        # FC structured records
        if step.tool_calls:
            entry["tool_calls"] = step.tool_calls
        if step.tool_results:
            entry["tool_results"] = step.tool_results

        if step.final_answer:
            entry["final_answer"] = step.final_answer

        result.append(entry)

    return result


def build_llm_history_view(
    coder: "Coder",
    mode: str,
    runner_type: str,
) -> list[dict[str, Any]]:
    """Build minimal history view for LLM consumption.

    v1.5: On the condensation path, checks for a persisted snapshot first.
    If a snapshot exists and covers the events (or is close enough), reuses
    it instead of recomputing condensation from scratch.

    Falls back to fresh condensation if no snapshot is available.
    """
    runner = _get_runner(coder)

    if runner is not None:
        messages = runner.build_history_messages()
    else:
        messages = list(coder.done_messages)

    # Apply condensation pipeline when events are sufficient
    events = _get_event_records(coder)
    if len(events) >= _CONDENSE_MIN_EVENTS:
        messages = _apply_condensation_with_snapshot(
            messages, events, mode, runner_type, coder,
        )

    return messages


# -- Condensation helper ----------------------------------------------------

def _apply_condensation(
    messages: list[dict[str, Any]],
    events: list[AgentEventRecord],
    mode: str,
) -> list[dict[str, Any]]:
    """Run prune → summarize → replace on the LLM history view.

    v1.5: Retention policy is enabled by default so that tool trace tiers
    (must_keep / summarize_only / trim_aggressively) affect real pruning.
    """
    from .condense import (
        prune_history_events,
        summarize_history_events,
        apply_condensation_to_history_view,
    )

    pruned = prune_history_events(events, mode, use_retention_policy=True)
    condensed = summarize_history_events(pruned)
    return apply_condensation_to_history_view(messages, condensed)


def _apply_condensation_with_snapshot(
    messages: list[dict[str, Any]],
    events: list[AgentEventRecord],
    mode: str,
    runner_type: str,
    coder: "Coder",
) -> list[dict[str, Any]]:
    """Apply condensation, preferring persisted snapshot when available.

    1. Check for a persisted snapshot for this session
    2. If snapshot covers events → reuse it (skip recomputation)
    3. If snapshot partially covers → merge snapshot + recent events
    4. If no snapshot → fall through to fresh condensation
    """
    session_id = getattr(coder, "session_id", "")
    root = getattr(coder, "root", "")

    if session_id and root:
        try:
            from .summary_store import load_latest_snapshot
            from .snapshot import (
                snapshot_covers_events,
                merge_snapshot_with_recent_events,
            )
            snapshot = load_latest_snapshot(session_id, root)
            if snapshot is not None:
                if snapshot_covers_events(snapshot, events):
                    # Full coverage — use snapshot + done_messages
                    return merge_snapshot_with_recent_events(
                        snapshot, events, runner_type,
                        done_messages=list(coder.done_messages),
                    )
                # Partial coverage — still try snapshot merge for old events
                from .snapshot import count_uncovered_events
                uncovered = count_uncovered_events(snapshot, events)
                if uncovered < len(events) // 2:
                    # Snapshot covers most events — use it
                    return merge_snapshot_with_recent_events(
                        snapshot, events, runner_type,
                        done_messages=list(coder.done_messages),
                    )
        except Exception:
            pass  # Graceful fallback to fresh condensation

    # Fresh condensation path
    result = _apply_condensation(messages, events, mode)

    # v1.5: Auto-generate and persist snapshot for future reuse
    _try_persist_snapshot(events, mode, session_id, root)

    return result


def _try_persist_snapshot(
    events: list[AgentEventRecord],
    mode: str,
    session_id: str,
    root: str,
) -> None:
    """Build and save a condensation snapshot. Never raises on failure."""
    if not session_id or not root:
        return
    try:
        from .condense import build_condensation_snapshot
        from .summary_store import save_snapshot

        snapshot = build_condensation_snapshot(events, mode, session_id=session_id)
        if snapshot is not None:
            save_snapshot(snapshot, root)
    except Exception:
        pass  # Graceful fallback — snapshot persistence must never crash the main chain


# -- Internal helpers -------------------------------------------------------

def _get_runner(coder: "Coder"):
    """Look up the registered runner for the coder's session."""
    try:
        from ..runners import get_runner
        session_id = getattr(coder, "session_id", "")
        runner = get_runner(session_id)
        if runner and hasattr(runner, "build_history_messages"):
            return runner
    except Exception:
        pass
    return None


def _get_step_records(coder: "Coder"):
    """Get AgentStep records from the runner's step store, if available."""
    runner = _get_runner(coder)
    if runner and hasattr(runner, "step_store") and runner.step_store:
        steps = runner.step_store.load_steps()
        if steps:
            return steps
    return []


def _get_event_records(coder: "Coder"):
    """Get event records from the step store's event store, if available."""
    runner = _get_runner(coder)
    if runner and hasattr(runner, "step_store") and runner.step_store:
        return runner.step_store.event_store.all_events()

    # Try to load events directly from file if no runner
    session_id = getattr(coder, "session_id", "")
    root = getattr(coder, "root", "")
    if session_id and root:
        try:
            from ..events.file_store import FileEventBackend
            file_backend = FileEventBackend(session_id=session_id, root=root)
            events = file_backend.all_events()
            if events:
                return events
        except Exception:
            pass

    return []


# Import AgentEventRecord for type annotation in _apply_condensation
from aicoder.events.types import AgentEventRecord
