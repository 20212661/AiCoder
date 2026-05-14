"""Snapshot helpers — check coverage and merge snapshot with recent events.

Used by the resume path in build_llm_history_view() to reuse a previously
persisted CondensationSnapshot instead of recomputing from scratch.
"""
from __future__ import annotations

from typing import Any

from .summary_types import CondensationSnapshot


def snapshot_covers_events(
    snapshot: CondensationSnapshot,
    events: list,
) -> bool:
    """Check if snapshot covers all the given events.

    A snapshot "covers" events if its latest_event_id matches the last
    event in the list, meaning all events up to that point were included
    in the condensation pass.

    Returns True if fully covered, False if there are newer events.
    """
    if not events:
        return True

    last_event_id = events[-1].event_id
    return snapshot.latest_event_id == last_event_id


def count_uncovered_events(
    snapshot: CondensationSnapshot,
    events: list,
) -> int:
    """Count how many events are newer than the snapshot's coverage.

    Returns the number of events after the snapshot's latest_event_id.
    """
    if not events:
        return 0

    latest_id = snapshot.latest_event_id
    for i, ev in enumerate(events):
        if ev.event_id == latest_id:
            return len(events) - i - 1

    # Snapshot's latest not found — all events are uncovered
    return len(events)


def get_uncovered_events(
    snapshot: CondensationSnapshot,
    events: list,
) -> list:
    """Get events that are newer than the snapshot's coverage."""
    if not events:
        return []

    latest_id = snapshot.latest_event_id
    for i, ev in enumerate(events):
        if ev.event_id == latest_id:
            return events[i + 1:]

    return events


def merge_snapshot_with_recent_events(
    snapshot: CondensationSnapshot,
    events: list,
    runner_type: str = "cot",
    done_messages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge a persisted snapshot with recent uncovered events.

    Produces an LLM-format message list:
    1. done_messages (from earlier conversation)
    2. Summary message pair (from snapshot blocks)
    3. Recent events replayed as LLM messages

    Falls back to returning done_messages if snapshot has no blocks.
    """
    done_messages = list(done_messages or [])
    if not snapshot.blocks:
        return done_messages

    messages = list(done_messages)

    # Build summary message pair from snapshot blocks
    block = snapshot.blocks[0]  # Primary block
    summary_text = block.format_text() if block.format_text() else block.raw_text

    messages.append({
        "role": "user",
        "content": "[Previous conversation condensed]",
    })
    summary_msg: dict[str, Any] = {
        "role": "assistant",
        "content": summary_text,
        "condensed": True,
        "covered_event_ids": block.covered_event_ids,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_source": "persisted",
    }
    # Include structured metadata
    if block.goal:
        summary_msg["goal"] = block.goal
    if block.findings:
        summary_msg["findings"] = block.findings
    if block.actions_taken:
        summary_msg["actions_taken"] = block.actions_taken
    if block.failures:
        summary_msg["failures"] = block.failures
    if block.files_touched:
        summary_msg["files_touched"] = block.files_touched
    if block.next_steps:
        summary_msg["next_steps"] = block.next_steps
    messages.append(summary_msg)

    # Replay recent uncovered events
    uncovered = get_uncovered_events(snapshot, events)
    if uncovered:
        from ..events.replay import replay_llm_view
        recent_msgs = replay_llm_view(uncovered, [], runner_type=runner_type)
        messages.extend(recent_msgs)

    return messages
