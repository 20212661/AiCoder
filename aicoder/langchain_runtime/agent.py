from __future__ import annotations

import inspect
import logging
from typing import Any

from langgraph.prebuilt import create_react_agent

from .middleware import build_middleware
from .model import build_chat_model
from .schemas import AICoderResponse
from .tools import build_langchain_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are AiCoder, an AI pair programming agent.

You can inspect code, search files, edit files, and run commands.
All file, git, shell, and workspace operations must be performed through tools.
Do not claim that a tool succeeded unless the tool result confirms success.
If a tool call is rejected or blocked, explain the limitation and choose a safer alternative.
"""


def _agent_accepts_kwarg(kwarg_name: str) -> bool:
    """Check whether create_react_agent accepts a given keyword argument."""
    sig = inspect.signature(create_react_agent)
    return kwarg_name in sig.parameters


def build_langchain_agent(coder: Any):
    model = build_chat_model(coder.main_model.name)
    tools = build_langchain_tools(coder)
    middleware = build_middleware()

    tool_names = [t.name for t in tools]
    logger.info("LangChain runtime tools registered: %s", tool_names)

    kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools,
        "prompt": SYSTEM_PROMPT,
    }

    structured_enabled = False
    if _agent_accepts_kwarg("response_format"):
        kwargs["response_format"] = AICoderResponse
        structured_enabled = True

    if _agent_accepts_kwarg("middleware") and middleware:
        kwargs["middleware"] = middleware

    logger.info(
        "LangChain runtime config: structured_response=%s, middleware_count=%d",
        structured_enabled,
        len(middleware),
    )

    return create_react_agent(**kwargs)


def _message_content(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", "")
    if isinstance(content, list):
        return "\n".join(str(item) for item in content)
    return str(content or "")


def extract_langchain_response_text(result: dict) -> str:
    """Extract display text from a LangChain agent result.

    Priority:
      1. structured_response.summary (if AICoderResponse or dict)
      2. Last message content
    """
    structured = result.get("structured_response")

    if structured is not None:
        if isinstance(structured, AICoderResponse):
            if structured.summary:
                return structured.summary
        elif isinstance(structured, dict):
            summary = structured.get("summary", "")
            if summary:
                return str(summary)

    messages = result.get("messages", [])
    if not messages:
        return ""
    return _message_content(messages[-1])


RECURSION_LIMIT = 25


def run_langchain_agent(coder: Any, user_message: str) -> str:
    agent = build_langchain_agent(coder)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": user_message}]},
        config={"recursion_limit": RECURSION_LIMIT},
    )
    return extract_langchain_response_text(result)
