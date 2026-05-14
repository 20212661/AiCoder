"""Session persistence helper for LangChain runtime."""

from __future__ import annotations

from typing import Any


def persist_langchain_turn(coder: Any, user_text: str, assistant_text: str) -> None:
    """Append a completed user/assistant turn to session history and save."""
    if not coder.session_id:
        return
    coder.cur_messages.append(dict(role="user", content=user_text))
    if not coder._first_user_message:
        coder._first_user_message = user_text
    coder.cur_messages.append(dict(role="assistant", content=assistant_text or ""))
    coder.done_messages.extend(coder.cur_messages)
    coder.cur_messages = []
    coder._save_session()
