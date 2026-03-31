from backend.agents.scaffold_web_agent.tenants import Tenant


def test_tenant_can_store_knowledge_text():
    tenant = Tenant(
        tenant_id="tenant-a",
        widget_token="tok_123",
        inbox_email="hello@example.com",
        subject_prefix="[Web Lead Agent]",
        allowed_origins=["https://example.com"],
        agent_type="scaffold_web_agent",
        knowledge_text="Scaffolding supplier knowledge",
    )

    assert tenant.knowledge_text == "Scaffolding supplier knowledge"
