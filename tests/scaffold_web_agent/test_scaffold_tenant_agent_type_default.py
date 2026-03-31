from backend.agents.scaffold_web_agent.tenants import Tenant


def test_tenant_defaults_agent_type_to_scaffold():
    tenant = Tenant(
        tenant_id="tenant-a",
        widget_token="tok_123",
        inbox_email="hello@example.com",
        subject_prefix="[Scaffold]",
        allowed_origins=["https://example.com"],
    )

    assert tenant.agent_type == "scaffold_web_agent"
