"""Tool Trace Retention Policy — fine-grained control over trace pruning.

Instead of a blanket "truncate old observations" approach, this module
classifies each tool trace event into retention tiers:

- must_keep: recent calls, errors, permission denied, critical file ops
- summarize_only: old but valuable results (keep summary, trim body)
- trim_aggressively: stale, repetitive, bulky outputs

The policy is deterministic and fully testable without LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aicoder.events.types import AgentEventRecord


class RetentionTier(Enum):
    MUST_KEEP = "must_keep"
    SUMMARIZE_ONLY = "summarize_only"
    TRIM_AGGRESSIVELY = "trim_aggressively"


@dataclass
class ToolTraceDecision:
    """Retention decision for a single tool trace event."""
    event_id: str
    tier: RetentionTier
    reason: str = ""
    max_output_chars: int = 0  # 0 = keep full


@dataclass
class ToolTraceRetentionReport:
    """Summary of retention decisions across all trace events."""
    total_traces: int = 0
    must_keep: int = 0
    summarize_only: int = 0
    trim_aggressively: int = 0
    decisions: list[ToolTraceDecision] = field(default_factory=list)

    @property
    def retention_ratio(self) -> str:
        if self.total_traces == 0:
            return "n/a"
        kept = self.must_keep + self.summarize_only
        return f"{kept}/{self.total_traces}"


# -- Critical tool names that always get higher retention --
_CRITICAL_TOOLS = frozenset({
    "edit_file", "write_file", "run_shell",
})

# -- Tools that typically produce bulky output --
_BULKY_TOOLS = frozenset({
    "list_files", "search_files", "list_code_defs",
})

# Default thresholds
_DEFAULT_RECENT_ITERATIONS = 2
_DEFAULT_SUMMARIZE_MAX_CHARS = 200
_DEFAULT_TRIM_MAX_CHARS = 50


def decide_tool_trace_retention(
    events: list[AgentEventRecord],
    mode: str = "act",
    budget_tokens: int = 0,
    recent_iterations: int = _DEFAULT_RECENT_ITERATIONS,
) -> ToolTraceRetentionReport:
    """Classify each tool trace event into a retention tier.

    Args:
        events: all events in the session
        mode: current agent mode
        budget_tokens: optional token budget hint (unused in v1.5, reserved)
        recent_iterations: how many recent iterations to consider "recent"

    Returns:
        ToolTraceRetentionReport with per-event decisions
    """
    # Find the max iteration to determine recency
    max_iter = 0
    for ev in events:
        if ev.iteration > max_iter:
            max_iter = ev.iteration

    report = ToolTraceRetentionReport()

    for ev in events:
        if ev.kind not in ("tool_result", "tool_error"):
            continue

        report.total_traces += 1
        decision = _classify_event(ev, max_iter, recent_iterations, mode)
        report.decisions.append(decision)

        if decision.tier == RetentionTier.MUST_KEEP:
            report.must_keep += 1
        elif decision.tier == RetentionTier.SUMMARIZE_ONLY:
            report.summarize_only += 1
        else:
            report.trim_aggressively += 1

    return report


def _classify_event(
    ev: AgentEventRecord,
    max_iter: int,
    recent_iterations: int,
    mode: str,
) -> ToolTraceDecision:
    """Classify a single tool trace event."""
    payload = ev.payload
    tool_name = payload.get("tool_name", "") or payload.get("tool_meta", {}).get("tool_name", "")
    is_error = ev.kind == "tool_error"
    obs = payload.get("observation", "")
    obs_len = len(obs)

    # Tier 1: MUST_KEEP — errors, recent, critical tools
    if is_error:
        return ToolTraceDecision(
            event_id=ev.event_id,
            tier=RetentionTier.MUST_KEEP,
            reason="error event",
            max_output_chars=0,
        )

    is_recent = ev.iteration > max_iter - recent_iterations

    if is_recent:
        return ToolTraceDecision(
            event_id=ev.event_id,
            tier=RetentionTier.MUST_KEEP,
            reason=f"recent (iteration {ev.iteration})",
            max_output_chars=0,
        )

    if tool_name in _CRITICAL_TOOLS:
        return ToolTraceDecision(
            event_id=ev.event_id,
            tier=RetentionTier.MUST_KEEP,
            reason=f"critical tool: {tool_name}",
            max_output_chars=0,
        )

    # Check for permission denied in payload
    err = payload.get("error", "")
    if "permission denied" in err.lower():
        return ToolTraceDecision(
            event_id=ev.event_id,
            tier=RetentionTier.MUST_KEEP,
            reason="permission denied",
            max_output_chars=0,
        )

    # Tier 2: SUMMARIZE_ONLY — old but has valuable content
    has_summary = payload.get("summary") or payload.get("tool_meta", {}).get("summary")
    if has_summary:
        return ToolTraceDecision(
            event_id=ev.event_id,
            tier=RetentionTier.SUMMARIZE_ONLY,
            reason="has structured summary",
            max_output_chars=_DEFAULT_SUMMARIZE_MAX_CHARS,
        )

    if obs_len > 500:
        return ToolTraceDecision(
            event_id=ev.event_id,
            tier=RetentionTier.SUMMARIZE_ONLY,
            reason=f"long output ({obs_len} chars)",
            max_output_chars=_DEFAULT_SUMMARIZE_MAX_CHARS,
        )

    if tool_name in _BULKY_TOOLS:
        return ToolTraceDecision(
            event_id=ev.event_id,
            tier=RetentionTier.SUMMARIZE_ONLY,
            reason=f"bulky tool: {tool_name}",
            max_output_chars=_DEFAULT_SUMMARIZE_MAX_CHARS,
        )

    # Tier 3: TRIM_AGGRESSIVELY — old, short, non-critical
    return ToolTraceDecision(
        event_id=ev.event_id,
        tier=RetentionTier.TRIM_AGGRESSIVELY,
        reason="old, non-critical, short output",
        max_output_chars=_DEFAULT_TRIM_MAX_CHARS,
    )


def apply_retention_to_events(
    events: list[AgentEventRecord],
    report: ToolTraceRetentionReport,
) -> list[AgentEventRecord]:
    """Apply retention decisions to produce pruned events.

    - must_keep: kept as-is
    - summarize_only: observation trimmed to max_output_chars
    - trim_aggressively: observation trimmed to max_output_chars

    Returns a new list — input is not mutated.
    """
    decision_map = {d.event_id: d for d in report.decisions}

    result: list[AgentEventRecord] = []
    for ev in events:
        if ev.kind not in ("tool_result", "tool_error"):
            result.append(ev)
            continue

        decision = decision_map.get(ev.event_id)
        if decision is None or decision.tier == RetentionTier.MUST_KEEP:
            result.append(ev)
            continue

        # Trim observation
        trimmed_payload = dict(ev.payload)
        obs = trimmed_payload.get("observation", "")
        if obs and decision.max_output_chars > 0 and len(obs) > decision.max_output_chars:
            trimmed_payload["observation"] = obs[:decision.max_output_chars] + "..."
            trimmed_payload["observation_truncated"] = True
            trimmed_payload["retention_tier"] = decision.tier.value

        result.append(AgentEventRecord(
            event_id=ev.event_id,
            session_id=ev.session_id,
            iteration=ev.iteration,
            kind=ev.kind,
            payload=trimmed_payload,
            created_at=ev.created_at,
        ))

    return result
