from backend.agents.scaffold_web_agent.tenant_service import TenantService
from backend.agents.scaffold_web_agent.tenants import Tenant


def test_tenant_service_resolve_by_widget_token_delegates(monkeypatch):
    service = TenantService()
    expected = Tenant(
        tenant_id="tenant-a",
        widget_token="tok_123",
        inbox_email="hello@example.com",
        subject_prefix="[Scaffold]",
        allowed_origins=["https://example.com"],
        agent_type="scaffold_web_agent",
    )

    def fake_resolve(widget_token: str):
        assert widget_token == "tok_123"
        return expected

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.tenant_service.resolve_tenant_by_token",
        fake_resolve,
    )

    result = service.resolve_by_widget_token("tok_123")

    assert result == expected


def test_tenant_service_upsert_delegates(monkeypatch):
    service = TenantService()
    tenant = Tenant(
        tenant_id="tenant-a",
        widget_token="tok_123",
        inbox_email="hello@example.com",
        subject_prefix="[Scaffold]",
        allowed_origins=["https://example.com"],
        agent_type="scaffold_web_agent",
    )

    called = {"tenant": None}

    def fake_upsert(value: Tenant):
        called["tenant"] = value

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.tenant_service.upsert_tenant",
        fake_upsert,
    )

    service.upsert(tenant)

    assert called["tenant"] == tenant


def test_tenant_service_list_all_delegates(monkeypatch):
    service = TenantService()
    expected = [
        {
            "tenant_id": "tenant-a",
            "widget_token": "tok_123",
            "token_active": True,
            "inbox_email": "hello@example.com",
            "subject_prefix": "[Scaffold]",
            "allowed_origins": ["https://example.com"],
            "agent_type": "scaffold_web_agent",
        }
    ]

    def fake_list():
        return expected

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.tenant_service.list_tenants",
        fake_list,
    )

    result = service.list_all()

    assert result == expected


def test_tenant_service_rotate_token_delegates(monkeypatch):
    service = TenantService()

    def fake_rotate(tenant_id: str) -> str:
        assert tenant_id == "tenant-a"
        return "tok_new"

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.tenant_service.rotate_widget_token",
        fake_rotate,
    )

    result = service.rotate_token("tenant-a")

    assert result == "tok_new"


def test_tenant_service_revoke_token_delegates(monkeypatch):
    service = TenantService()
    called = {"tenant_id": None}

    def fake_revoke(tenant_id: str) -> None:
        called["tenant_id"] = tenant_id

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.tenant_service.revoke_widget_token",
        fake_revoke,
    )

    service.revoke_token("tenant-a")

    assert called["tenant_id"] == "tenant-a"
