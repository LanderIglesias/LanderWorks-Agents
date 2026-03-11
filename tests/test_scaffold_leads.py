from fastapi.testclient import TestClient

from backend.apps.scaffold_web_agent.api import get_mailer, get_settings
from backend.apps.scaffold_web_agent.mailer import FakeMailer
from backend.apps.scaffold_web_agent.tenants import Tenant, upsert_tenant
from backend.main import app


def test_lead_inserted_after_send(monkeypatch, tmp_path):
    import backend.apps.scaffold_web_agent.sqlite_store as ss

    monkeypatch.setattr(ss, "_db_path", lambda: tmp_path / "scaffold_test.db")

    monkeypatch.setenv("ADMIN_TOKEN", "admintest")
    monkeypatch.setenv("SCAFFOLD_INBOX_EMAIL", "inbox@test.com")
    monkeypatch.setenv("SCAFFOLD_ENV", "prod")
    get_settings.cache_clear()

    upsert_tenant(
        Tenant(
            tenant_id="t1",
            widget_token="tok_test_123",
            inbox_email="inbox@test.com",
            subject_prefix="[Test]",
            allowed_origins=["https://client.example"],
        )
    )

    fake_mailer = FakeMailer()

    def _get_mailer_override():
        return fake_mailer

    app.dependency_overrides[get_mailer] = _get_mailer_override

    client = TestClient(app)
    headers = {
        "X-Widget-Token": "tok_test_123",
        "Origin": "https://client.example",
    }

    sid = "s1"

    client.post(
        "/scaffold-agent/chat", json={"session_id": sid, "message": "Hello"}, headers=headers
    )
    client.post(
        "/scaffold-agent/chat",
        json={"session_id": sid, "message": "buyer@company.com"},
        headers=headers,
    )
    client.post(
        "/scaffold-agent/chat",
        json={"session_id": sid, "message": "Need quotation FOB Ningbo"},
        headers=headers,
    )
    client.post(
        "/scaffold-agent/chat",
        json={"session_id": sid, "message": "Ringlock scaffolding 500 sqm delivery Bilbao Spain"},
        headers=headers,
    )
    client.post("/scaffold-agent/chat", json={"session_id": sid, "message": "YES"}, headers=headers)

    r = client.get(
        "/scaffold-agent/admin/leads/t1",
        headers={"X-Admin-Token": "admintest"},
    )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tenant_id"] == "t1"
    assert len(data["leads"]) == 1
    assert data["leads"][0]["email"] == "buyer@company.com"

    app.dependency_overrides = {}
