"""AgentRuntime: adapter between existing Coder and LangGraph workflow.

Delegates to AgentAppRunner for runner selection and execution.
"""
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

        try:
            from .agent_app_runner import AgentAppRunner
            app_runner = AgentAppRunner()
            return app_runner.run_user_turn(
                self.coder, user_input, self.graph, self.checkpointer,
            )
        except LLMError as err:
            self.coder.io.tool_error(
                f"LLM API FAILURE: {err}\n"
                f"  Check: API key, network, model availability.\n"
                f"  Tip: try /model to switch models."
            )
            self._finalize_on_error()
            return None
        except Exception as err:
            self.coder.io.tool_error(f"Runtime error: {err}")
            self._finalize_on_error()
            return None
        finally:
            unregister_coder(self._session_id)

    def _finalize_on_error(self) -> None:
        """Emergency finalization for error/exception paths."""
        coder = self.coder
        coder.done_messages.extend(coder.cur_messages)
        coder.cur_messages = []
        coder._save_session()


def _create_runtime(coder):
    """Factory: build AgentRuntime with optional checkpointer from env."""
    use_checkpoint = os.environ.get("AICODER_LANGGRAPH_CHECKPOINT") == "1"
    checkpointer = None
    if use_checkpoint:
        from .graph.checkpointer import get_checkpointer
        checkpointer = get_checkpointer()
    return AgentRuntime(coder, checkpointer=checkpointer)
