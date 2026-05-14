"""Middleware builder for LangChain runtime.

Builds a list of AgentMiddleware instances for use with create_react_agent.
All imports are guarded — if the installed LangChain version does not expose
the expected classes, this module degrades gracefully and returns an empty list.
Legacy runtime imports are never affected.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def format_tool_error_message(error: Exception) -> str:
    """Format a tool error into a model-friendly message.

    Preserves semantic error categories (rejection, safety block, permission)
    so the model can reason about what went wrong.
    """
    error_text = str(error)
    lower = error_text.lower()

    if "reject" in lower:
        category = "User rejected"
    elif "block" in lower or "denied" in lower or "permission" in lower:
        category = "Safety/policy blocked"
    else:
        category = "Execution failed"

    return (
        f"Tool error: {category}. Reason: {error_text}. "
        f"Check the arguments, respect aiCoder safety policy, or choose a safer alternative."
    )


def _build_handle_tool_errors():
    """Build handle_tool_errors middleware if wrap_tool_call is available."""
    try:
        from langchain.agents.middleware import wrap_tool_call
        from langchain.messages import ToolMessage

        @wrap_tool_call
        def handle_tool_errors(request, handler):
            try:
                return handler(request)
            except Exception as e:
                return ToolMessage(
                    content=format_tool_error_message(e),
                    tool_call_id=request.tool_call["id"],
                )

        return handle_tool_errors
    except ImportError:
        logger.debug("wrap_tool_call not available — handle_tool_errors skipped")
        return None


def build_middleware() -> list:
    """Build a list of LangChain middleware instances.

    Attempts to import and configure:
      - handle_tool_errors (wrap_tool_call based)
      - ModelCallLimitMiddleware
      - ToolCallLimitMiddleware
      - ModelRetryMiddleware
      - ToolRetryMiddleware

    Returns an empty list when middleware classes are not available.
    """
    middleware: list = []

    # Tool error handling — highest priority
    error_handler = _build_handle_tool_errors()
    if error_handler is not None:
        middleware.append(error_handler)

    # Rate limiting and retry middleware
    try:
        from langchain.middleware import (
            ModelCallLimitMiddleware,
            ModelRetryMiddleware,
            ToolCallLimitMiddleware,
            ToolRetryMiddleware,
        )

        middleware.append(
            ModelCallLimitMiddleware(run_limit=8, thread_limit=40, exit_behavior="end")
        )
        middleware.append(ToolCallLimitMiddleware(run_limit=20, thread_limit=80))
        middleware.append(ModelRetryMiddleware(max_retries=2, backoff_factor=2.0))
        middleware.append(ToolRetryMiddleware(max_retries=1, backoff_factor=2.0))
    except ImportError:
        pass

    logger.info("build_middleware: %d middleware(s) available", len(middleware))
    return middleware
