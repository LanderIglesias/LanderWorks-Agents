from __future__ import annotations

from .tenants import (
    Tenant,
    list_tenants,
    resolve_tenant_by_token,
    revoke_widget_token,
    rotate_widget_token,
    upsert_tenant,
)


class TenantService:
    def resolve_by_widget_token(self, widget_token: str) -> Tenant | None:
        return resolve_tenant_by_token(widget_token)

    def upsert(self, tenant: Tenant) -> None:
        upsert_tenant(tenant)

    def list_all(self) -> list[dict]:
        return list_tenants()

    def rotate_token(self, tenant_id: str) -> str:
        return rotate_widget_token(tenant_id)

    def revoke_token(self, tenant_id: str) -> None:
        revoke_widget_token(tenant_id)
