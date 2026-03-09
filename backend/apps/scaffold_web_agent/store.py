from __future__ import annotations

from .domain import SessionState


class InMemorySessionStore:
    def __init__(self) -> None:
        self._db: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        return self._db.get(session_id, SessionState())

    def set(self, session_id: str, state: SessionState) -> None:
        self._db[session_id] = state
