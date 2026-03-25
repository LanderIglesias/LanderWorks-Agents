from backend.apps.scaffold_web_agent.tenants import (
    Tenant,
    list_tenants,
    resolve_tenant_by_token,
    upsert_tenant,
)


def test_tenant_knowledge_is_persisted_and_resolved(test_db):
    upsert_tenant(
        Tenant(
            tenant_id="tenant-knowledge-001",
            widget_token="tok_knowledge_001",
            inbox_email="hello@example.com",
            subject_prefix="[Scaffold]",
            allowed_origins=["https://example.com"],
            agent_type="scaffold_web_agent",
            knowledge_text="Horario: L-V 9:00-18:00. Servicio principal: implantes.",
        )
    )

    tenant = resolve_tenant_by_token("tok_knowledge_001")
    assert tenant is not None
    assert tenant.tenant_id == "tenant-knowledge-001"
    assert "Horario" in tenant.knowledge_text

    tenants = list_tenants()
    matching = [item for item in tenants if item["tenant_id"] == "tenant-knowledge-001"]

    assert matching
    assert "implantes" in matching[0]["knowledge_text"]
