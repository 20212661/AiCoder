"""Session management package — session lifecycle and federation."""
from .core import (  # noqa: F401
    SessionMeta,
    delete_session,
    list_sessions,
    load_session,
    new_session_id,
    save_session,
    session_count,
)
