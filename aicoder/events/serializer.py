"""Event serialization — stable dict conversion for persistence.

Round-trip: event_to_dict(event) -> dict -> event_from_dict(dict) -> event
All fields preserved: event_id, session_id, iteration, kind, payload, created_at.
"""
from __future__ import annotations

from aicoder.events.types import AgentEventRecord, EventKind


def event_to_dict(event: AgentEventRecord) -> dict:
    """Convert an AgentEventRecord to a JSON-serializable dict."""
    return {
        "event_id": event.event_id,
        "session_id": event.session_id,
        "iteration": event.iteration,
        "kind": event.kind,
        "payload": event.payload,
        "created_at": event.created_at,
    }


def event_from_dict(data: dict) -> AgentEventRecord:
    """Reconstruct an AgentEventRecord from a dict.

    Raises KeyError if required fields are missing.
    """
    return AgentEventRecord(
        event_id=data["event_id"],
        session_id=data["session_id"],
        iteration=data["iteration"],
        kind=data["kind"],
        payload=data.get("payload", {}),
        created_at=data.get("created_at", 0.0),
    )
