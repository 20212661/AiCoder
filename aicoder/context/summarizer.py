"""Summarizer — deterministic and optional LLM summarization of events.

Produces structured SummaryBlock objects from event streams.
The deterministic summarizer is always available; LLM summarizer is
an optional enhancement layer.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .summary_types import SummaryBlock, CondensationSnapshot, _new_id

if TYPE_CHECKING:
    from ..events.types import AgentEventRecord
    pass


def summarize_events_deterministic(
    events: list[AgentEventRecord],
    mode: str = "act",
) -> SummaryBlock | None:
    """Build a structured SummaryBlock from events without LLM.

    Extracts goal, findings, actions_taken, failures, files_touched,
    next_steps directly from event payloads.

    Returns None if there are no meaningful events to summarize.
    """
    if not events:
        return None

    event_ids: list[str] = []
    iterations: list[int] = []
    goal = ""
    findings: list[str] = []
    actions_taken: list[str] = []
    failures: list[str] = []
    files_touched: list[str] = []
    next_steps: list[str] = []

    for ev in events:
        event_ids.append(ev.event_id)
        if ev.iteration not in iterations:
            iterations.append(ev.iteration)

        if ev.kind == "assistant_thought":
            thought = ev.payload.get("thought", "")
            if thought:
                goal = thought  # Latest thought as goal

        elif ev.kind == "tool_call":
            tool_name = ev.payload.get("tool_name", "unknown")
            tool_input = ev.payload.get("tool_input", {})
            if isinstance(tool_input, dict) and tool_input:
                args_preview = ", ".join(
                    f"{k}={v}" for k, v in list(tool_input.items())[:3]
                )
                actions_taken.append(f"{tool_name}({args_preview})")
            else:
                actions_taken.append(tool_name)

        elif ev.kind == "tool_result":
            meta = ev.payload.get("tool_meta", {})
            # Priority: payload.summary > tool_meta.summary > observation text
            finding = (
                ev.payload.get("summary")
                or meta.get("summary")
                or ev.payload.get("observation", "")
            )
            if finding:
                findings.append(finding[:200])
            # Collect files
            for f in ev.payload.get("files", []):
                if f not in files_touched:
                    files_touched.append(f)
            for f in meta.get("files", []):
                if f not in files_touched:
                    files_touched.append(f)

        elif ev.kind == "tool_error":
            meta = ev.payload.get("tool_meta", {})
            tool_name = meta.get("tool_name", "unknown")
            error_type = meta.get("error_type", "")
            summary = meta.get("summary") or ev.payload.get("summary")
            recommended = (
                meta.get("recommended_next")
                or ev.payload.get("recommended_next")
            )

            if summary:
                failures.append(summary)
            elif error_type:
                err_msg = ev.payload.get("error", "")
                failures.append(
                    f"{tool_name} ({error_type}): {err_msg}"
                    if err_msg else f"{tool_name} ({error_type})"
                )
            else:
                fail_text = (
                    ev.payload.get("error", "")
                    or ev.payload.get("observation", "")
                )
                if fail_text:
                    failures.append(f"{tool_name}: {fail_text}")

            if recommended and recommended not in next_steps:
                next_steps.append(recommended)

    # Nothing meaningful extracted
    if not any([goal, findings, actions_taken, failures, files_touched]):
        return None

    return SummaryBlock(
        summary_id=_new_id("sb-"),
        kind="deterministic",
        covered_event_ids=event_ids,
        covered_iterations=sorted(iterations),
        goal=goal,
        findings=findings,
        actions_taken=actions_taken,
        failures=failures,
        files_touched=files_touched,
        next_steps=next_steps,
        raw_text="",
    )


def summarize_events_with_llm(
    events: list[AgentEventRecord],
    coder,
    mode: str = "act",
) -> SummaryBlock | None:
    """Optional LLM-enhanced summarization.

    Currently falls back to deterministic. Can be upgraded later
    to use LLM for richer summaries. Deterministic fallback is
    always preserved.
    """
    # For now, delegate to deterministic
    # Future: call LLM to enrich the block
    return summarize_events_deterministic(events, mode)


def build_summary_block(
    events: list[AgentEventRecord],
    mode: str = "act",
    coder=None,
) -> SummaryBlock | None:
    """Build a SummaryBlock, preferring LLM if available.

    Guaranteed to produce deterministic output even without coder.
    """
    if coder is not None:
        return summarize_events_with_llm(events, coder, mode)
    return summarize_events_deterministic(events, mode)


def build_condensation_snapshot(
    events: list[AgentEventRecord],
    mode: str = "act",
    coder=None,
    session_id: str = "",
) -> CondensationSnapshot | None:
    """Build a full CondensationSnapshot from events.

    Returns None if no meaningful summary can be produced.
    """
    block = build_summary_block(events, mode, coder)
    if block is None:
        return None

    event_ids = [e.event_id for e in events] if events else []
    latest_id = event_ids[-1] if event_ids else ""

    return CondensationSnapshot(
        snapshot_id=_new_id("snap-"),
        session_id=session_id,
        source_event_count=len(events),
        latest_event_id=latest_id,
        blocks=[block],
        mode=mode,
    )
