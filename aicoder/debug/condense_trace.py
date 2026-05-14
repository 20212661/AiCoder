"""Condensation diagnostics — trace condensation pipeline decisions.

Reports on event counts, pruning decisions, summary quality,
and whether condensation is helping or hurting context quality.

Usage:
    from aicoder.debug.condense_trace import trace_condensation

    report = trace_condensation(coder, "act")
    print(report["summary"])
    for issue in report.get("warnings", []):
        print(f"WARNING: {issue}")
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..coders.base_coder import Coder


def trace_condensation(
    coder: "Coder",
    mode: str,
) -> dict[str, Any]:
    """Produce a structured diagnostic of the condensation pipeline.

    Returns a dict with:
    - events: event statistics (counts by kind)
    - pruning: how many events were pruned, how many truncated
    - summary: condensation summary quality metrics
    - warnings: list of potential issues
    """
    report: dict[str, Any] = {
        "events": {},
        "pruning": {},
        "summary": {},
        "warnings": [],
    }

    # 1. Gather events
    events = _get_events(coder)
    if not events:
        report["summary_text"] = "No events to analyze."
        return report

    # 2. Event statistics by kind
    kind_counts: dict[str, int] = {}
    for ev in events:
        kind_counts[ev.kind] = kind_counts.get(ev.kind, 0) + 1
    report["events"]["total"] = len(events)
    report["events"]["by_kind"] = kind_counts

    # 3. Pruning analysis
    from ..context.condense import prune_history_events, _PRUNE_OBSERVATION_MAX
    pruned = prune_history_events(events, mode)

    truncated_count = 0
    for ev in pruned:
        if ev.payload.get("observation_truncated"):
            truncated_count += 1

    report["pruning"]["total_events"] = len(events)
    report["pruning"]["pruned_events"] = len(pruned)
    report["pruning"]["truncated_observations"] = truncated_count
    report["pruning"]["max_observation_chars"] = _PRUNE_OBSERVATION_MAX

    if truncated_count > 0:
        report["warnings"].append(
            f"{truncated_count} observation(s) truncated to {_PRUNE_OBSERVATION_MAX} chars"
        )

    # 4. Summarization analysis
    from ..context.condense import summarize_history_events, _KEEP_RECENT_COUNT
    block = summarize_history_events(pruned)

    if block is None:
        report["summary"]["produced"] = False
        report["summary"]["reason"] = "No actionable events to summarize"
        report["summary_text"] = f"{len(events)} events, no condensation produced."
        return report

    report["summary"]["produced"] = True
    report["summary"]["length_chars"] = len(block.summary)
    report["summary"]["covered_events"] = len(block.covered_event_ids)
    report["summary"]["keep_recent_count"] = _KEEP_RECENT_COUNT

    # Check summary quality
    summary = block.summary
    sections = []
    if "Goal:" in summary:
        sections.append("Goal")
    if "Actions taken:" in summary:
        sections.append("Actions")
    if "Findings:" in summary:
        sections.append("Findings")
    if "Failures:" in summary:
        sections.append("Failures")
    if "Next steps:" in summary:
        sections.append("Next steps")
    if "Files touched:" in summary:
        sections.append("Files")
    if "Conclusion:" in summary:
        sections.append("Conclusion")

    report["summary"]["sections_present"] = sections
    report["summary"]["sections_count"] = len(sections)

    # Quality warnings
    if len(sections) < 2:
        report["warnings"].append(
            f"Summary only has {len(sections)} section(s) — may be incomplete"
        )

    if len(summary) < 50:
        report["warnings"].append("Summary is very short — may lack useful detail")

    if len(summary) > 5000:
        report["warnings"].append(
            f"Summary is {len(summary)} chars — may consume too many tokens"
        )

    # 5. Coverage check
    covered_ratio = len(block.covered_event_ids) / max(len(events), 1)
    report["summary"]["coverage_ratio"] = round(covered_ratio, 2)
    if covered_ratio < 0.5:
        report["warnings"].append(
            f"Condensation only covers {covered_ratio:.0%} of events"
        )

    # 6. Final summary
    report["summary_text"] = (
        f"Condensation: {len(events)} events → {len(block.summary)} chars, "
        f"{len(sections)} sections, {covered_ratio:.0%} coverage, "
        f"{truncated_count} truncated"
    )

    return report


def _get_events(coder: "Coder") -> list:
    """Get event records from coder's runner."""
    try:
        from ..context.history_view import _get_event_records
        return _get_event_records(coder)
    except Exception:
        return []
