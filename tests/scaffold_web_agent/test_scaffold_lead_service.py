from backend.agents.scaffold_web_agent.lead_service import LeadService


def test_lead_service_create_lead_delegates(monkeypatch):
    service = LeadService()
    called = {}

    def fake_insert_lead(
        tenant_id: str,
        session_id: str,
        email: str | None,
        topic: str | None,
        summary: str | None,
    ) -> None:
        called["tenant_id"] = tenant_id
        called["session_id"] = session_id
        called["email"] = email
        called["topic"] = topic
        called["summary"] = summary

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.lead_service.insert_lead",
        fake_insert_lead,
    )

    service.create_lead(
        tenant_id="tenant-a",
        session_id="sess-1",
        email="hello@example.com",
        topic="pricing",
        summary="Lead summary",
    )

    assert called == {
        "tenant_id": "tenant-a",
        "session_id": "sess-1",
        "email": "hello@example.com",
        "topic": "pricing",
        "summary": "Lead summary",
    }


def test_lead_service_list_for_tenant_delegates(monkeypatch):
    service = LeadService()
    expected = [
        {
            "id": 1,
            "tenant_id": "tenant-a",
            "session_id": "sess-1",
            "email": "hello@example.com",
            "topic": "pricing",
            "summary": "Lead summary",
            "created_at": 123456,
        }
    ]

    def fake_list_leads_for_tenant(tenant_id: str, limit: int = 50):
        assert tenant_id == "tenant-a"
        assert limit == 7
        return expected

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.lead_service.list_leads_for_tenant",
        fake_list_leads_for_tenant,
    )

    result = service.list_for_tenant("tenant-a", 7)

    assert result == expected
