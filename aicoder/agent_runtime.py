"""AgentRuntime: adapter between existing Coder and LangGraph workflow."""
from __future__ import annotations

import os
from typing import Any

from .exceptions import LLMError
from .graph.state import register_coder, unregister_coder
from .graph.workflow import build_agent_graph


class AgentRuntime:
    def __init__(self, coder, checkpointer=None):
        self.coder = coder
        self.checkpointer = checkpointer
        self.graph = build_agent_graph(checkpointer=checkpointer)
        self._session_id = coder.session_id or "default"

    def run_user_turn(self, user_input: str) -> str | None:
        # Register coder so nodes can access it via session_id lookup
        register_coder(self._session_id, self.coder)

        config = self._build_config()

        try:
            # If checkpointer is active, try to resume a pending interrupt first
            if self.checkpointer is not None and self._has_pending_interrupt(config):
                return self._resume_interrupt(config)

            # Normal flow: start a new turn
            state = self._initial_state(user_input)
            result = self.graph.invoke(state, config=config)
            return result.get("final_response")
        except LLMError as err:
            self.coder.io.tool_error(
                f"LLM API FAILURE: {err}\n"
                f"  Check: API key, network, model availability.\n"
                f"  Tip: try /model to switch models."
            )
            self.coder.done_messages.extend(self.coder.cur_messages)
            self.coder.cur_messages = []
            return None
        except Exception as err:
            self.coder.io.tool_error(f"Runtime error: {err}")
            return None

    def _has_pending_interrupt(self, config: dict) -> bool:
        """Check if there's a pending interrupt from a previous run."""
        try:
            state_snapshot = self.graph.get_state(config)
            if state_snapshot and state_snapshot.tasks:
                for task in state_snapshot.tasks:
                    if task.interrupts:
                        return True
        except Exception:
            pass
        return False

    def _resume_interrupt(self, config: dict) -> str | None:
        """Resume a graph that was interrupted (e.g., pending approval)."""
        try:
            from langgraph.types import Command

            self.coder.io.tool_output("Resuming from saved checkpoint...")
            result = self.graph.invoke(Command(resume=True), config=config)
            final = result.get("final_response")
            self._finalize_coder(result)
            return final
        except Exception as err:
            self.coder.io.tool_error(f"Failed to resume checkpoint: {err}")
            return None

    def _finalize_coder(self, result: dict) -> None:
        """Persist coder state after graph completes."""
        coder = self.coder
        edited = coder.tool_exec_state.had_file_edits
        if edited and coder.auto_commits and coder.repo:
            coder.auto_commit()
        coder.done_messages.extend(coder.cur_messages)
        coder.cur_messages = []
        coder._save_session()

    def _build_config(self) -> dict[str, Any] | None:
        if self.checkpointer is None:
            return None
        return {"configurable": {"thread_id": self._session_id}}

    def _initial_state(self, user_input: str) -> dict[str, Any]:
        return {
            "session_id": self._session_id,
            "user_input": user_input,
            "messages": [],
            "mode": self.coder.tool_exec_state.mode,
            "phase": "idle",
            "root": self.coder.root,
            "pending_tool_calls": [],
            "tool_observations": [],
            "loop_count": 0,
            "max_loops": 5,
        }


def _create_runtime(coder):
    """Factory: build AgentRuntime with optional checkpointer from env."""
    use_checkpoint = os.environ.get("AICODER_LANGGRAPH_CHECKPOINT") == "1"
    checkpointer = None
    if use_checkpoint:
        from .graph.checkpointer import get_checkpointer
        checkpointer = get_checkpointer()
    return AgentRuntime(coder, checkpointer=checkpointer)
