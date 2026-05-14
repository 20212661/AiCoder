"""Condensation Pipeline — prune, summarize, replace for long histories.

v1.5: Upgraded to produce structured SummaryBlock objects via the
summarizer module. The legacy CondensedBlock is retained for backward
compatibility but is no longer the primary output.

Key constraint: condensation generates a *derived view* — it never mutates
the original event store or step store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING, Union

from aicoder.events.types import AgentEventRecord

if TYPE_CHECKING:
    pass


# Legacy type — retained for backward compatibility with existing consumers.
@dataclass
class CondensedBlock:
    """A summary block that replaces a span of older events in the LLM view."""

    summary: str
    covered_event_ids: list[str]
    kind: str = "summary_block"


# Type alias for functions that accept either old or new block types
CondensedLike = Union[CondensedBlock, "SummaryBlock"]


def _has_structured_fields(obj) -> bool:
    """Check if obj is a SummaryBlock (has .goal etc)."""
    return hasattr(obj, "goal")


# ---------------------------------------------------------------------------
# Prune: slim down old tool_result bodies
# ---------------------------------------------------------------------------

# Keys to preserve from tool_result / tool_error payloads when pruning
_PRUNE_KEEP_KEYS = frozenset({
    "tool_name", "tool_input", "success", "files",
    "summary", "recommended_next", "error", "tool_meta",
})

# Max chars for observation text after pruning
_PRUNE_OBSERVATION_MAX = 200


def prune_history_events(
    events: list[AgentEventRecord],
    mode: str,
    *,
    use_retention_policy: bool = False,
) -> list[AgentEventRecord]:
    """Prune old tool_result/tool_error events by slimming their payloads.

    Keeps tool_name, success/failure, summary, files, recommended_next.
    Truncates long observation text. Does NOT delete entire records.

    When use_retention_policy=True, applies tier-based retention policy
    for finer-grained trimming instead of uniform character limits.

    Returns a new list — the input list is not mutated.
    """
    if use_retention_policy:
        from .tool_trace_policy import (
            decide_tool_trace_retention,
            apply_retention_to_events,
        )
        report = decide_tool_trace_retention(events, mode)
        # First apply basic field filtering to all events
        basic_pruned = []
        for ev in events:
            if ev.kind in ("tool_result", "tool_error"):
                basic_pruned.append(AgentEventRecord(
                    event_id=ev.event_id,
                    session_id=ev.session_id,
                    iteration=ev.iteration,
                    kind=ev.kind,
                    payload=_prune_tool_payload(ev.payload),
                    created_at=ev.created_at,
                ))
            else:
                basic_pruned.append(ev)
        # Then apply retention-based trimming on top
        return apply_retention_to_events(basic_pruned, report)

    pruned: list[AgentEventRecord] = []
    for ev in events:
        if ev.kind in ("tool_result", "tool_error"):
            pruned_payload = _prune_tool_payload(ev.payload)
            pruned.append(AgentEventRecord(
                event_id=ev.event_id,
                session_id=ev.session_id,
                iteration=ev.iteration,
                kind=ev.kind,
                payload=pruned_payload,
                created_at=ev.created_at,
            ))
        else:
            pruned.append(ev)
    return pruned


def _prune_tool_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Slim down a tool result/error payload, keeping only essential fields."""
    result: dict[str, Any] = {}

    for key in _PRUNE_KEEP_KEYS:
        if key in payload:
            result[key] = payload[key]

    # Truncate observation text if present
    obs = payload.get("observation", "")
    if obs:
        if len(obs) > _PRUNE_OBSERVATION_MAX:
            result["observation"] = obs[:_PRUNE_OBSERVATION_MAX] + "..."
            result["observation_truncated"] = True
        else:
            result["observation"] = obs

    return result


# ---------------------------------------------------------------------------
# Summarize: produce structured SummaryBlock from events
# ---------------------------------------------------------------------------

def summarize_history_events(
    events: list[AgentEventRecord],
    coder: Any = None,
) -> CondensedLike | None:
    """Generate a structured summary of a span of events.

    v1.5: Delegates to the summarizer module which produces SummaryBlock
    objects with structured fields (goal, findings, actions, failures, etc).

    The returned SummaryBlock has a `.summary` property that returns rendered
    text, maintaining backward compatibility with CondensedBlock consumers.

    Returns None if there are no events to summarize.
    """
    if not events:
        return None

    from .summarizer import build_summary_block

    mode = "act"  # default mode for direct calls
    block = build_summary_block(events, mode, coder)
    if block is not None:
        return block

    # Fallback: if summarizer returns None but there are events,
    # produce a legacy CondensedBlock
    event_ids = [e.event_id for e in events]
    return CondensedBlock(
        summary=f"({len(events)} events)",
        covered_event_ids=event_ids,
    )


def build_condensation_snapshot(
    events: list[AgentEventRecord],
    mode: str = "act",
    coder: Any = None,
    session_id: str = "",
) -> Any | None:
    """Build a full CondensationSnapshot from events.

    Returns None if no meaningful summary can be produced.
    """
    from .summarizer import build_condensation_snapshot as _build
    return _build(events, mode, coder, session_id)


# ---------------------------------------------------------------------------
# Apply: replace old events in history view with summary block
# ---------------------------------------------------------------------------

# Minimum number of recent events to keep un-condensed
_KEEP_RECENT_COUNT = 4  # at least 2 most recent iterations of events


def apply_condensation_to_history_view(
    history_view: list[dict[str, Any]],
    condensed: CondensedLike | None,
) -> list[dict[str, Any]]:
    """Replace older events in the LLM history view with a condensed summary.

    Accepts both legacy CondensedBlock and new SummaryBlock.
    - Inserts the summary as a user/assistant message pair near the start
      of the conversation portion.
    - Preserves the most recent messages untouched.
    - Returns a new list — the input is not mutated.

    If condensed is None, returns the history_view unchanged.
    """
    if condensed is None or not history_view:
        return list(history_view)

    # Don't condense if the view is too short
    if len(history_view) <= _KEEP_RECENT_COUNT:
        return list(history_view)

    # Split: older messages get replaced, recent ones stay
    split_point = len(history_view) - _KEEP_RECENT_COUNT
    recent = history_view[split_point:]

    # Build the summary message pair — duck-typed: both have .summary and .covered_event_ids
    summary_user = {
        "role": "user",
        "content": "[Previous conversation condensed]",
    }
    summary_assistant = {
        "role": "assistant",
        "content": condensed.summary,
        "condensed": True,
        "covered_event_ids": condensed.covered_event_ids,
    }

    # Include structured metadata if available (SummaryBlock)
    if _has_structured_fields(condensed):
        summary_assistant["summary_block_id"] = condensed.summary_id
        summary_assistant["goal"] = condensed.goal
        summary_assistant["findings"] = condensed.findings
        summary_assistant["actions_taken"] = condensed.actions_taken
        summary_assistant["failures"] = condensed.failures
        summary_assistant["files_touched"] = condensed.files_touched
        summary_assistant["next_steps"] = condensed.next_steps

    return [summary_user, summary_assistant] + recent
