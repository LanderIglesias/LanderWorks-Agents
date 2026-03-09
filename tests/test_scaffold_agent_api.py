from fastapi.testclient import TestClient

from backend.apps.scaffold_web_agent.api import get_mailer, get_settings
from backend.apps.scaffold_web_agent.mailer import FakeMailer
from backend.apps.scaffold_web_agent.tenants import Tenant, upsert_tenant
from backend.main import app


def test_cors_preflight_allows_tenant_origin(monkeypatch, tmp_path):
    import backend.apps.scaffold_web_agent.sqlite_store as ss

    monkeypatch.setattr(ss, "_db_path", lambda: tmp_path / "scaffold_test.db")

    from backend.apps.scaffold_web_agent.tenants import Tenant, upsert_tenant

    upsert_tenant(
        Tenant(
            tenant_id="t1",
            widget_token="tok_test_123",
            inbox_email="inbox@scaffold.com",
            subject_prefix="[Scaffold Web Agent]",
            allowed_origins=["https://client.example"],
        )
    )

    client = TestClient(app)
    r = client.options(
        "/scaffold-agent/chat?token=tok_test_123",
        headers={
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-widget-token",
        },
    )
    assert r.status_code == 204
    assert r.headers.get("access-control-allow-origin") == "https://client.example"


def test_api_sends_email_on_yes(monkeypatch, tmp_path):
    # 1) env vars so settings validates
    monkeypatch.setenv("SCAFFOLD_INBOX_EMAIL", "autochurches@gmail.com")
    monkeypatch.setenv("SCAFFOLD_ENV", "prod")

    # 2) clear settings cache
    get_settings.cache_clear()

    # 3) IMPORTANT: isolate scaffold sqlite DB to tmp path
    import backend.apps.scaffold_web_agent.sqlite_store as ss

    monkeypatch.setattr(ss, "_db_path", lambda: tmp_path / "scaffold_test.db")

    upsert_tenant(
        Tenant(
            tenant_id="t1",
            widget_token="tok_test_123",
            inbox_email="inbox@scaffold.com",
            subject_prefix="[Scaffold Web Agent]",
            allowed_origins=["https://client.example"],
        )
    )

    headers = {
        "X-Widget-Token": "tok_test_123",
        "Origin": "https://client.example",
    }

    # 4) override mailer dependency with a stable instance
    fake_mailer = FakeMailer()

    def _get_mailer_override():
        return fake_mailer

    app.dependency_overrides[get_mailer] = _get_mailer_override

    client = TestClient(app)
    sid = "session-1"

    r1 = client.post(
        "/scaffold-agent/chat",
        json={"session_id": sid, "message": "Hello"},
        headers=headers,
    )
    assert r1.status_code == 200, r1.text
    data = r1.json()
    assert data["step"] == "collect_contact"

    r2 = client.post(
        "/scaffold-agent/chat",
        json={"session_id": sid, "message": "buyer@company.com"},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["step"] == "collect_case"

    r3 = client.post(
        "/scaffold-agent/chat",
        json={"session_id": sid, "message": "Need quotation FOB Ningbo, MOQ?"},
        headers=headers,
    )
    assert r3.status_code == 200, r3.text
    data = r3.json()
    assert data["step"] == "collect_case"

    r4 = client.post(
        "/scaffold-agent/chat",
        json={
            "session_id": sid,
            "message": "Ringlock, 500 sqm, delivery to Bilbao, Spain. Need in 2 weeks.",
        },
        headers=headers,
    )
    assert r4.status_code == 200, r4.text
    data = r4.json()
    assert data["step"] == "confirm"

    r5 = client.post(
        "/scaffold-agent/chat",
        json={"session_id": sid, "message": "YES"},
        headers=headers,
    )
    assert r5.status_code == 200, r5.text
    data = r5.json()
    assert data["is_done"] is True
    assert data["step"] == "done"

    assert len(fake_mailer.sent) == 1

    to, subject, body = fake_mailer.sent[0]
    assert to == "inbox@scaffold.com"
    assert "Scaffold Web Agent" in subject
    assert "New web inquiry" in body

    app.dependency_overrides = {}
