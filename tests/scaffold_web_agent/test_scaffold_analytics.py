from fastapi.testclient import TestClient

from backend.agents.scaffold_web_agent.tenants import Tenant, upsert_tenant
from backend.main import app


def test_tenant_analytics(monkeypatch, tmp_path):
    import backend.agents.scaffold_web_agent.sqlite_store as ss

    monkeypatch.setattr(ss, "_db_path", lambda: tmp_path / "scaffold_test.db")

    monkeypatch.setenv("ADMIN_TOKEN", "admintest")
    monkeypatch.setenv("SCAFFOLD_INBOX_EMAIL", "inbox@test.com")
    monkeypatch.setenv("SCAFFOLD_ENV", "dev")

    upsert_tenant(
        Tenant(
            tenant_id="t1",
            widget_token="tok_test_123",
            inbox_email="inbox@test.com",
            subject_prefix="[Test]",
            allowed_origins=["https://client.example"],
        )
    )

    client = TestClient(app)
    headers = {
        "X-Widget-Token": "tok_test_123",
        "Origin": "https://client.example",
    }

    # create one session that reaches confirm
    client.post(
        "/scaffold-agent/chat", json={"session_id": "s1", "message": "Hello"}, headers=headers
    )
    client.post(
        "/scaffold-agent/chat",
        json={"session_id": "s1", "message": "buyer@company.com"},
        headers=headers,
    )
    client.post(
        "/scaffold-agent/chat",
        json={"session_id": "s1", "message": "Need quotation FOB Ningbo, MOQ?"},
        headers=headers,
    )
    client.post(
        "/scaffold-agent/chat",
        json={
            "session_id": "s1",
            "message": "Ringlock, 500 sqm, delivery to Bilbao, Spain. Need in 2 weeks.",
        },
        headers=headers,
    )

    r = client.get(
        "/scaffold-agent/admin/analytics/t1",
        headers={"X-Admin-Token": "admintest"},
    )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tenant_id"] == "t1"
    assert data["total_sessions"] == 1
    assert data["confirm_sessions"] == 1
    assert data["sessions_with_email"] == 1
