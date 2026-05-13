"""Base runner and StepResult — common infrastructure for all runner strategies.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §6.2
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aicoder.agent_events import StepEvent, emit_step_event
from aicoder.agent_step_store import AgentStep, AgentStepStore
from aicoder.tools.result import ToolCall, ToolResult

if TYPE_CHECKING:
    from aicoder.coders.base_coder import Coder
    from aicoder.tools.registry import ToolRegistry


@dataclass
class StepResult:
    """Result of a single runner step — one LLM call + parse cycle."""

    thought: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_ids: list[str] = field(default_factory=list)
    failed_observations: list[ToolResult] = field(default_factory=list)
    final_answer: str = ""
    clean_text: str = ""
    raw_response: str = ""
    step: AgentStep | None = None


class BaseAgentRunner(ABC):
    """Abstract base for all runner strategies.

    Holds common infrastructure: step tracking, event emission,
    last-round tool disabling.
    """

    def __init__(
        self,
        coder: "Coder",
        session_id: str,
        mode: str,
        tool_registry: "ToolRegistry",
        step_store: AgentStepStore,
    ) -> None:
        self.coder = coder
        self.session_id = session_id
        self.mode = mode
        self.model = coder.main_model
        self.tool_registry = tool_registry
        self.tool_executor = coder.tool_executor
        self.step_store = step_store

    @abstractmethod
    def run_step(
        self,
        messages: list[dict],
        iteration: int,
        max_iterations: int,
    ) -> StepResult:
        """Execute one step: call LLM, parse output, return structured result."""
        ...

    # -- Step lifecycle -----------------------------------------------------

    def _create_step(self, iteration: int) -> AgentStep:
        runner_type = self._runner_type()
        step = self.step_store.create_step(
            iteration=iteration,
            mode=self.mode,
            runner_type=runner_type,
        )
        self._emit_step_event("agent.step.created", step)
        return step

    def _update_step_after_parse(
        self,
        step: AgentStep,
        *,
        thought: str = "",
        action_name: str | None = None,
        action_input: dict | str | None = None,
        action_raw: str | None = None,
    ) -> None:
        self.step_store.update_step_after_parse(
            step,
            thought=thought,
            action_name=action_name,
            action_input=action_input,
            action_raw=action_raw,
        )
        if thought:
            self._emit_step_event("agent.step.thought", step, {"thought": thought})
        if action_name:
            self._emit_step_event(
                "agent.step.action", step,
                {"action_name": action_name, "action_input": action_input},
            )

    def _update_step_after_tool(
        self,
        step: AgentStep,
        *,
        observation: str = "",
        tool_meta: dict | None = None,
        files: list[str] | None = None,
        tool_error: bool = False,
    ) -> None:
        self.step_store.update_step_after_tool(
            step, observation=observation, tool_meta=tool_meta, files=files,
            tool_error=tool_error,
        )
        self._emit_step_event("agent.step.observation", step, {"observation": observation})

    def _finalize_step(self, step: AgentStep, *, final_answer: str = "") -> None:
        self.step_store.finalize_step(step, final_answer=final_answer)
        if final_answer:
            self._emit_step_event("agent.step.final", step, {"final_answer": final_answer})

    def _mark_step_error(self, step: AgentStep, *, error: str) -> None:
        self.step_store.mark_error(step, error=error)
        self._emit_step_event("agent.step.error", step, {"error": error})

    # -- Event emission -----------------------------------------------------

    def _emit_step_event(
        self,
        event_type: str,
        step: AgentStep,
        data: dict | None = None,
    ) -> None:
        event = StepEvent(
            type=event_type,
            step_id=step.id,
            iteration=step.iteration,
            data=data or {},
        )
        emit_step_event(self.coder.io, event)

    # -- Helpers ------------------------------------------------------------

    def _should_disable_tools(self, iteration: int, max_iterations: int) -> bool:
        """Per §14.3: disable tools on the last iteration to force a final answer."""
        return iteration >= max_iterations - 1

    def _runner_type(self) -> str:
        name = type(self).__name__
        if "Function" in name:
            return "function-calling"
        return "cot"

    # -- History (§9) -------------------------------------------------------

    def build_history_messages(self) -> list[dict]:
        """Rebuild prompt history from done_messages + step records.

        Uses AgentHistoryRebuilder for step-aware reconstruction.
        Falls back to replay from persisted events when no steps are in
        memory (e.g. after session resume).
        """
        from aicoder.agent_history_rebuilder import AgentHistoryRebuilder

        steps = self.step_store.load_steps()
        done_messages = list(self.coder.done_messages)

        if not steps:
            # No in-memory steps — try replay from persisted events
            events = self.step_store.event_store.all_events()
            if events:
                from aicoder.events.replay import replay_llm_view
                return replay_llm_view(
                    events, done_messages, runner_type=self._runner_type(),
                )
            return done_messages

        if self._runner_type() == "function-calling":
            return AgentHistoryRebuilder.build_for_fc(done_messages, steps)
        return AgentHistoryRebuilder.build_for_cot(done_messages, steps)

    def truncate_history_messages(
        self,
        messages: list[dict],
        max_tokens: int | None = None,
    ) -> list[dict]:
        """Truncate history by complete iteration boundaries.

        Uses AgentHistoryTruncator for step-boundary-aware truncation.
        """
        from aicoder.agent_history_truncator import AgentHistoryTruncator

        if max_tokens is None:
            max_tokens = getattr(self.model, "max_input_tokens", 128000)
            max_tokens = max(1024, max_tokens - 4096)

        token_fn = getattr(self.model, "token_count", None)
        if token_fn is None:
            return messages

        return AgentHistoryTruncator.truncate(messages, max_tokens, token_fn)
