from backend.agents.scaffold_web_agent.tenants import (
    Tenant,
    list_tenants,
    resolve_tenant_by_token,
    upsert_tenant,
)


def test_tenant_agent_type_is_persisted_and_resolved(test_db):
    upsert_tenant(
        Tenant(
            tenant_id="tenant-agent-type-001",
            widget_token="tok_agent_type_001",
            inbox_email="hello@example.com",
            subject_prefix="[Scaffold]",
            allowed_origins=["https://example.com"],
            agent_type="scaffold_web_agent",
        )
    )

    tenant = resolve_tenant_by_token("tok_agent_type_001")
    assert tenant is not None
    assert tenant.tenant_id == "tenant-agent-type-001"
    assert tenant.agent_type == "scaffold_web_agent"

    tenants = list_tenants()
    matching = [item for item in tenants if item["tenant_id"] == "tenant-agent-type-001"]

    assert matching
    assert matching[0]["agent_type"] == "scaffold_web_agent"


def test_tenant_with_echo_agent_type_is_persisted_and_resolved(test_db):
    upsert_tenant(
        Tenant(
            tenant_id="tenant-echo-001",
            widget_token="tok_echo_001",
            inbox_email="echo@example.com",
            subject_prefix="[Echo]",
            allowed_origins=["https://example.com"],
            agent_type="echo_web_agent",
        )
    )

    tenant = resolve_tenant_by_token("tok_echo_001")
    assert tenant is not None
    assert tenant.tenant_id == "tenant-echo-001"
    assert tenant.agent_type == "echo_web_agent"
