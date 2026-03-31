from __future__ import annotations

from .sqlite_store import insert_lead, list_leads_for_tenant


class LeadService:
    def create_lead(
        self,
        tenant_id: str,
        session_id: str,
        email: str | None,
        topic: str | None,
        summary: str | None,
    ) -> None:
        insert_lead(
            tenant_id=tenant_id,
            session_id=session_id,
            email=email,
            topic=topic,
            summary=summary,
        )

    def list_for_tenant(self, tenant_id: str, limit: int = 50) -> list[dict]:
        return list_leads_for_tenant(tenant_id, limit)
