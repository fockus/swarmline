"""Sessions module - agent session management."""

from swarmline.session.backends import (
    InMemorySessionBackend,
    MemoryScope,
    SessionBackend,
    SqliteSessionBackend,
    scoped_key,
)
from swarmline.session.manager import InMemorySessionManager
from swarmline.session.rehydrator import DefaultSessionRehydrator
from swarmline.session.task_session_store import (
    InMemoryTaskSessionStore,
    SqliteTaskSessionStore,
    TaskSessionStore,
)
from swarmline.session.task_session_types import TaskSessionParams
from swarmline.session.types import SessionKey, SessionState

__all__ = [
    "DefaultSessionRehydrator",
    "InMemorySessionBackend",
    "InMemorySessionManager",
    "InMemoryTaskSessionStore",
    "MemoryScope",
    "SessionBackend",
    "SessionKey",
    "SessionState",
    "SqliteSessionBackend",
    "SqliteTaskSessionStore",
    "TaskSessionParams",
    "TaskSessionStore",
    "scoped_key",
]
