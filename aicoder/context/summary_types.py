"""Structured summary and snapshot types for advanced condensation.

SummaryBlock replaces the old CondensedBlock (plain text) with structured
fields: goal, findings, actions_taken, failures, files_touched, next_steps.

CondensationSnapshot bundles one or more SummaryBlocks with metadata about
the source events, enabling persistence and later reuse during resume.

Both types are fully serializable (to_dict / from_dict) for JSON storage.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _new_id(prefix: str = "") -> str:
    short = uuid.uuid4().hex[:12]
    return f"{prefix}{short}" if prefix else short


@dataclass
class SummaryBlock:
    """Structured summary of a span of agent events.

    Produced by the condensation pipeline and consumed by:
    - LLM history view (as condensed context)
    - Summary store (for persistence)
    - Debug / dump / trace (for diagnostics)
    """

    summary_id: str
    kind: str = "summary_block"
    covered_event_ids: list[str] = field(default_factory=list)
    covered_iterations: list[int] = field(default_factory=list)

    # Structured fields extracted from events
    goal: str = ""
    findings: list[str] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    # Fallback raw text for display / legacy compatibility
    raw_text: str = ""

    @property
    def summary(self) -> str:
        """Rendered text — backward compat with CondensedBlock.summary."""
        return self.format_text()

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "kind": self.kind,
            "covered_event_ids": self.covered_event_ids,
            "covered_iterations": self.covered_iterations,
            "goal": self.goal,
            "findings": self.findings,
            "actions_taken": self.actions_taken,
            "failures": self.failures,
            "files_touched": self.files_touched,
            "next_steps": self.next_steps,
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SummaryBlock:
        return cls(
            summary_id=data["summary_id"],
            kind=data.get("kind", "summary_block"),
            covered_event_ids=data.get("covered_event_ids", []),
            covered_iterations=data.get("covered_iterations", []),
            goal=data.get("goal", ""),
            findings=data.get("findings", []),
            actions_taken=data.get("actions_taken", []),
            failures=data.get("failures", []),
            files_touched=data.get("files_touched", []),
            next_steps=data.get("next_steps", []),
            raw_text=data.get("raw_text", ""),
        )

    def format_text(self) -> str:
        """Render structured fields into a human-readable summary text."""
        sections: list[str] = []
        if self.goal:
            sections.append(f"Goal: {self.goal}")
        if self.actions_taken:
            lines = "\n".join(f"  - {a}" for a in self.actions_taken)
            sections.append(f"Actions taken:\n{lines}")
        if self.findings:
            lines = "\n".join(f"  - {f}" for f in self.findings[:6])
            sections.append(f"Findings:\n{lines}")
        if self.failures:
            lines = "\n".join(f"  - {f}" for f in self.failures)
            sections.append(f"Failures:\n{lines}")
        if self.next_steps:
            lines = "\n".join(f"  - {s}" for s in self.next_steps[:3])
            sections.append(f"Next steps:\n{lines}")
        if self.files_touched:
            sections.append("Files touched: " + ", ".join(self.files_touched))
        return "\n\n".join(sections) if sections else self.raw_text


@dataclass
class CondensationSnapshot:
    """Bundled snapshot of condensation results for a session.

    Persists the output of a condensation pass so that resume can reuse
    it instead of recomputing from scratch.
    """

    snapshot_id: str
    session_id: str
    source_event_count: int
    latest_event_id: str
    blocks: list[SummaryBlock] = field(default_factory=list)
    created_at: str = ""
    mode: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "session_id": self.session_id,
            "source_event_count": self.source_event_count,
            "latest_event_id": self.latest_event_id,
            "blocks": [b.to_dict() for b in self.blocks],
            "created_at": self.created_at,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CondensationSnapshot:
        blocks = [
            SummaryBlock.from_dict(b) for b in data.get("blocks", [])
        ]
        return cls(
            snapshot_id=data["snapshot_id"],
            session_id=data["session_id"],
            source_event_count=data["source_event_count"],
            latest_event_id=data["latest_event_id"],
            blocks=blocks,
            created_at=data.get("created_at", ""),
            mode=data.get("mode", ""),
        )

    @property
    def covered_event_ids(self) -> list[str]:
        ids: list[str] = []
        for b in self.blocks:
            ids.extend(b.covered_event_ids)
        return ids

    @property
    def covered_iterations(self) -> list[int]:
        iters: set[int] = set()
        for b in self.blocks:
            iters.update(b.covered_iterations)
        return sorted(iters)
