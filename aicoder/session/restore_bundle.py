"""Cross-session restore bundle builder.

Aggregates context from linked sessions in a TaskThread to produce a
RestoreBundle — the structured input for context packing in a new session.

The bundle selects the most recent N sessions (per FederationPolicy),
extracts their latest condensation snapshots, and assembles:
  goals, constraints, decisions, open_loops, critical_files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .federation import (
    FederationPolicy,
    load_task_thread,
    list_linked_sessions,
)


@dataclass
class RestoreBundle:
    """Structured restore context assembled from linked sessions."""

    task_thread_id: str
    goals: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    open_loops: list[str] = field(default_factory=list)
    critical_files: list[str] = field(default_factory=list)
    sessions_used: list[str] = field(default_factory=list)
    sessions_skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_thread_id": self.task_thread_id,
            "goals": self.goals,
            "constraints": self.constraints,
            "decisions": self.decisions,
            "open_loops": self.open_loops,
            "critical_files": self.critical_files,
            "sessions_used": self.sessions_used,
            "sessions_skipped": self.sessions_skipped,
        }


def build_restore_bundle(
    task_thread_id: str,
    root: str = "",
    policy: FederationPolicy | None = None,
) -> RestoreBundle:
    """Build a RestoreBundle by aggregating snapshots from linked sessions.

    Selects up to ``policy.max_restore_sessions`` sessions (most recent first),
    loads their latest condensation snapshot, and extracts structured fields.
    """
    if policy is None:
        policy = FederationPolicy()

    bundle = RestoreBundle(task_thread_id=task_thread_id)

    if not root:
        return bundle

    tt = load_task_thread(task_thread_id, root=root)
    if tt is None:
        return bundle

    links = list_linked_sessions(task_thread_id, root=root)

    # Select the N most recent sessions (sorted by linked_at desc)
    candidates = sorted(links, key=lambda l: l.linked_at, reverse=True)
    selected = candidates[: policy.max_restore_sessions]
    skipped_ids = [l.session_id for l in candidates[policy.max_restore_sessions:]]
    bundle.sessions_skipped = skipped_ids

    from ..context.summary_store import load_latest_snapshot

    seen_files: set[str] = set()

    for link in selected:
        snapshot = load_latest_snapshot(link.session_id, root)
        if snapshot is None:
            continue

        bundle.sessions_used.append(link.session_id)

        for block in snapshot.blocks:
            if block.goal:
                bundle.goals.append(f"[{link.session_id}] {block.goal}")

            bundle.decisions.extend(
                f"[{link.session_id}] {a}" for a in block.actions_taken
            )

            bundle.open_loops.extend(
                f"[{link.session_id}] {s}" for s in block.next_steps
            )

            for f in block.files_touched:
                if f not in seen_files:
                    seen_files.add(f)
                    bundle.critical_files.append(f)

            # Failures become constraints
            for fail in block.failures:
                bundle.constraints.append(f"[{link.session_id}] Avoid: {fail}")

    return bundle
