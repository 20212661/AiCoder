"""AgentAppRunner — entry-level orchestrator that selects and wires the runner.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §6.1
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aicoder.agent_step_store import AgentStepStore
from aicoder.recovery.checkpoint_guard import CheckpointGuard, register_guard, unregister_guard
from aicoder.runners import register_runner, unregister_runner
from aicoder.runners.cot_agent_runner import CotAgentRunner
from aicoder.runners.function_calling_agent_runner import FunctionCallingAgentRunner

if TYPE_CHECKING:
    from aicoder.coders.base_coder import Coder


_REASONER_MODEL_PREFIXES = ("deepseek-reasoner", "machao-pro")


class AgentAppRunner:
    """Selects the appropriate runner strategy and delegates execution."""

    def run_user_turn(
        self,
        coder: "Coder",
        user_input: str,
        graph: Any,
        checkpointer: Any = None,
        task_thread_id: str = "",
    ) -> str | None:
        session_id = coder.session_id
        mode = coder.tool_exec_state.mode

        # Select runner strategy based on model capability, not mode
        # v1.4: persist events to file when root is available
        root = getattr(coder, "root", "")
        step_store = AgentStepStore.for_session(
            session_id, persist=bool(root), root=root,
        )
        runner = self._create_runner(coder, session_id, mode, step_store)

        # Register runner so graph nodes can access it
        register_runner(session_id, runner)

        # Build checkpoint guard for crash-recovery idempotency
        guard = self._build_guard(step_store, session_id, bool(checkpointer))
        register_guard(session_id, guard)

        try:
            # v1.7: Load federation restore bundle if task_thread_id is configured
            fed_result = load_federation_restore_bundle(
                task_thread_id=task_thread_id,
                root=getattr(coder, "root", ""),
            )

            # Build initial state
            initial_state = {
                "session_id": session_id,
                "user_input": user_input,
                "messages": [],
                "mode": mode,
                "phase": "idle",
                "root": coder.root,
                "pending_tool_calls": [],
                "tool_observations": [],
                "loop_count": 0,
                "max_loops": 5,
                "runner_type": runner._runner_type(),
            }

            # v1.7: Inject federation context when available
            if fed_result is not None:
                initial_state["task_thread_id"] = task_thread_id
                initial_state["federation_context"] = fed_result["context_text"]
                initial_state["federation_trace"] = fed_result["trace"]

            # Build config for checkpointer
            config = None
            if checkpointer:
                from aicoder.graph.checkpointer import get_thread_config
                config = get_thread_config(session_id)

                # Check for pending interrupt to resume
                if self._has_pending_interrupt(graph, config):
                    from langgraph.types import Command
                    result = graph.invoke(Command(resume=True), config=config)
                    return result.get("final_response")

            # Invoke graph
            result = graph.invoke(initial_state, config=config)
            return result.get("final_response")

        finally:
            unregister_runner(session_id)
            unregister_guard(session_id)

    def _create_runner(self, coder, session_id, mode, step_store):
        model = coder.main_model
        if (
            model.capabilities.supports_tools
            and not self._is_reasoner_model(model.name)
        ):
            return FunctionCallingAgentRunner(
                coder=coder,
                session_id=session_id,
                mode=mode,
                tool_registry=coder.tool_registry,
                step_store=step_store,
            )
        return CotAgentRunner(
            coder=coder,
            session_id=session_id,
            mode=mode,
            tool_registry=coder.tool_registry,
            step_store=step_store,
        )

    @staticmethod
    def _is_reasoner_model(model_name: str) -> bool:
        return any(model_name.startswith(p) for p in _REASONER_MODEL_PREFIXES)

    @staticmethod
    def _has_pending_interrupt(graph, config) -> bool:
        try:
            state = graph.get_state(config)
            return bool(state.tasks)
        except Exception:
            return False

    @staticmethod
    def _build_guard(step_store: AgentStepStore, session_id: str, is_resume: bool) -> CheckpointGuard:
        """Build a CheckpointGuard from persisted events on crash-resume.

        On a fresh run, returns an empty guard so execute_tool_node can
        safely call get_guard() without a None-check.
        """
        if not is_resume:
            return CheckpointGuard()

        events = step_store.event_store.all_events()
        if events:
            return CheckpointGuard.from_events(events)
        return CheckpointGuard()


def load_federation_restore_bundle(
    task_thread_id: str,
    root: str = "",
) -> dict[str, Any] | None:
    """Load and trim a federation restore bundle for a task thread.

    Returns None if task_thread_id is empty or thread not found (v1.6.1 compat).
    Returns dict with keys: bundle, context_text, trace.
    """
    if not task_thread_id or not root:
        return None

    from aicoder.session.federation import FederationPolicy, load_task_thread
    from aicoder.session.restore_bundle import build_restore_bundle
    from aicoder.context.packer import trim_federation_context

    tt = load_task_thread(task_thread_id, root=root)
    if tt is None:
        return None

    policy = FederationPolicy()
    bundle = build_restore_bundle(task_thread_id, root=root, policy=policy)

    if not bundle.sessions_used:
        return None

    context_text = trim_federation_context(bundle, max_tokens=policy.federation_tokens)

    trace = {
        "task_thread_id": task_thread_id,
        "sessions_used": bundle.sessions_used,
        "sessions_skipped": bundle.sessions_skipped,
        "goals_count": len(bundle.goals),
        "decisions_count": len(bundle.decisions),
        "open_loops_count": len(bundle.open_loops),
        "files_count": len(bundle.critical_files),
    }

    return {
        "bundle": bundle,
        "context_text": context_text,
        "trace": trace,
    }
