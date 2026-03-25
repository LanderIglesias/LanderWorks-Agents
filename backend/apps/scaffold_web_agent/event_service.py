from __future__ import annotations

from .sqlite_store import insert_event, list_events_for_tenant


class EventService:
    def record(
        self,
        *,
        tenant_id: str,
        session_id: str,
        event_type: str,
        event_payload: dict | None = None,
    ) -> None:
        insert_event(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type=event_type,
            event_payload=event_payload,
        )

    def list_for_tenant(self, tenant_id: str, limit: int = 100) -> list[dict]:
        return list_events_for_tenant(tenant_id, limit)
