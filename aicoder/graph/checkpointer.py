"""SQLite-backed LangGraph checkpointer for session state persistence."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_DIR = Path.home() / ".aicoder" / "langgraph"
DEFAULT_DB_NAME = "checkpoints.sqlite"


def get_checkpointer(db_path: str | Path | None = None):
    """Create or return a SqliteSaver checkpointer.

    Args:
        db_path: Path to the SQLite database file. Defaults to
                 ``~/.aicoder/langgraph/checkpoints.sqlite``.

    Returns:
        A ``SqliteSaver`` instance ready to pass to ``graph.compile()``.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    if db_path is None:
        db_path = DEFAULT_DB_DIR / DEFAULT_DB_NAME

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn)


def get_thread_config(session_id: str) -> dict[str, Any]:
    """Build a LangGraph thread config bound to a session ID.

    Returns:
        ``{"configurable": {"thread_id": session_id}}``
    """
    return {"configurable": {"thread_id": session_id}}
