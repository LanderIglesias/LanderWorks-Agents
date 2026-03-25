from __future__ import annotations

from .domain import SessionState
from .sqlite_store import SQLiteSessionStore, list_sessions_for_tenant


class SessionService:
    def __init__(self, store: SQLiteSessionStore | None = None) -> None:
        self._store = store or SQLiteSessionStore()

    def get_state(self, tenant_id: str, session_id: str) -> SessionState:
        return self._store.get(tenant_id, session_id)

    def save_state(self, tenant_id: str, session_id: str, state: SessionState) -> None:
        self._store.set(tenant_id, session_id, state)

    def list_for_tenant(self, tenant_id: str, limit: int = 20) -> list[dict]:
        return list_sessions_for_tenant(tenant_id, limit)
