"""AgentStep data model and AgentStepStore for tracking agent execution iterations.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §7
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from aicoder.events.store import AgentEventStore


@dataclass
class AgentStep:
    """Unified model for one agent execution iteration (think-act-observe cycle)."""

    id: str
    session_id: str
    iteration: int
    mode: str  # sniff | plan | act
    runner_type: Literal["cot", "function-calling"]
    phase: str = "created"
    thought: str = ""
    action_name: str | None = None
    action_input: dict | str | None = None
    action_raw: str | None = None
    observation: str = ""
    final_answer: str = ""
    tool_meta: dict = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    error: str = ""
    status: Literal["created", "parsed", "observed", "final", "error"] = "created"
    # v1.1: enriched step data for better failure feedback
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    summary: str = ""


class AgentStepStore:
    """In-memory store for AgentStep records within a session.

    Composes an AgentEventStore to emit structured events at each lifecycle
    transition. The event_store is accessible for downstream consumers
    (history view, condensation pipeline, etc.).
    """

    def __init__(
        self,
        session_id: str,
        event_store: "AgentEventStore | None" = None,
    ) -> None:
        self._session_id = session_id
        self._steps: list[AgentStep] = []
        # v1.2: compose event store — create one if not provided
        if event_store is not None:
            self._event_store = event_store
        else:
            from aicoder.events.store import AgentEventStore

            self._event_store = AgentEventStore(session_id=session_id)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def event_store(self) -> "AgentEventStore":
        return self._event_store

    def create_step(
        self,
        *,
        iteration: int,
        mode: str,
        runner_type: Literal["cot", "function-calling"],
    ) -> AgentStep:
        step = AgentStep(
            id=str(uuid.uuid4()),
            session_id=self._session_id,
            iteration=iteration,
            mode=mode,
            runner_type=runner_type,
        )
        self._steps.append(step)
        self._event_store.append(
            iteration=iteration,
            kind="step_started",
            payload={"step_id": step.id, "mode": mode, "runner_type": runner_type},
        )
        return step

    def update_step_after_parse(
        self,
        step: AgentStep,
        *,
        thought: str = "",
        action_name: str | None = None,
        action_input: dict | str | None = None,
        action_raw: str | None = None,
    ) -> None:
        step.thought = thought
        step.action_name = action_name
        step.action_input = action_input
        step.action_raw = action_raw
        step.phase = "parsed"
        step.status = "parsed"
        # Emit structured parse events
        if thought:
            self._event_store.append(
                iteration=step.iteration,
                kind="assistant_thought",
                payload={"step_id": step.id, "thought": thought},
            )
        if action_name:
            self._event_store.append(
                iteration=step.iteration,
                kind="tool_call",
                payload={
                    "step_id": step.id,
                    "tool_name": action_name,
                    "tool_input": action_input if isinstance(action_input, dict) else {"raw": action_input},
                },
            )

    def update_step_after_tool(
        self,
        step: AgentStep,
        *,
        observation: str = "",
        tool_meta: dict | None = None,
        files: list[str] | None = None,
        tool_error: bool = False,
    ) -> None:
        step.observation = observation
        if tool_meta is not None:
            step.tool_meta = tool_meta
        if files is not None:
            step.files = files
        step.phase = "observed"
        step.status = "observed"
        # Emit tool_result or tool_error event
        event_kind = "tool_error" if tool_error else "tool_result"
        payload: dict = {"step_id": step.id, "observation": observation}
        if tool_meta:
            payload["tool_meta"] = tool_meta
        if files:
            payload["files"] = files
        self._event_store.append(
            iteration=step.iteration,
            kind=event_kind,
            payload=payload,
        )

    def finalize_step(self, step: AgentStep, *, final_answer: str = "") -> None:
        step.final_answer = final_answer
        step.phase = "final"
        step.status = "final"
        self._event_store.append(
            iteration=step.iteration,
            kind="step_finished",
            payload={"step_id": step.id, "final_answer": final_answer},
        )

    def mark_error(self, step: AgentStep, *, error: str) -> None:
        step.error = error
        step.phase = "error"
        step.status = "error"
        self._event_store.append(
            iteration=step.iteration,
            kind="tool_error",
            payload={
                "step_id": step.id,
                "error": error,
                "tool_meta": {
                    "success": False,
                    "tool_name": step.action_name or "unknown",
                    "error_type": "step_error",
                    "summary": f"Step failed: {error}",
                    "recommended_next": "Inspect the failure and retry or choose a different approach.",
                    "files": list(step.files) if step.files else [],
                },
            },
        )

    def load_steps(self) -> list[AgentStep]:
        return list(self._steps)

    def steps_for_iteration(self, iteration: int) -> list[AgentStep]:
        return [s for s in self._steps if s.iteration == iteration]

    def last_step(self) -> AgentStep | None:
        return self._steps[-1] if self._steps else None

    # -- Factory --------------------------------------------------------------

    @classmethod
    def for_session(
        cls,
        session_id: str,
        *,
        persist: bool = False,
        root: str = "",
    ) -> "AgentStepStore":
        """Create an AgentStepStore, optionally with file-persisted events.

        Args:
            session_id: Session identifier.
            persist: If True, events persist to JSONL file.
            root: Project root (required when persist=True).
        """
        from aicoder.events.store import AgentEventStore
        event_store = AgentEventStore.for_session(
            session_id, persist=persist, root=root,
        )
        return cls(session_id=session_id, event_store=event_store)
