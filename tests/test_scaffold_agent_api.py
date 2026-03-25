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


def test_admin_tenant_analytics_uses_analytics_service(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)

    class DummyAnalyticsService:
        def tenant_summary(self, tenant_id: str) -> dict:
            assert tenant_id == "tenant-a"
            return {
                "tenant_id": tenant_id,
                "total_sessions": 5,
                "done_sessions": 2,
                "confirm_sessions": 3,
                "sessions_with_email": 4,
                "total_events": 9,
                "chat_requested_count": 5,
                "chat_replied_count": 5,
                "lead_delivery_requested_count": 2,
                "lead_created_count": 2,
                "lead_delivery_completed_count": 2,
                "lead_creation_rate": 0.4,
                "delivery_completion_rate": 1.0,
                "unique_sessions_with_chat_requested": 4,
                "unique_sessions_with_chat_replied": 4,
                "unique_sessions_with_lead_delivery_requested": 2,
                "unique_sessions_with_lead_created": 2,
                "unique_sessions_with_lead_delivery_completed": 2,
                "session_reply_rate": 1.0,
                "session_lead_creation_rate": 0.5,
                "session_delivery_completion_rate": 1.0,
            }

    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.api._analytics_service",
        DummyAnalyticsService(),
    )
    monkeypatch.setenv("ADMIN_TOKEN", "admin-secret")

    response = client.get(
        "/scaffold-agent/admin/analytics/tenant-a",
        headers={"X-Admin-Token": "admin-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": "tenant-a",
        "total_sessions": 5,
        "done_sessions": 2,
        "confirm_sessions": 3,
        "sessions_with_email": 4,
        "total_events": 9,
        "chat_requested_count": 5,
        "chat_replied_count": 5,
        "lead_delivery_requested_count": 2,
        "lead_created_count": 2,
        "lead_delivery_completed_count": 2,
        "lead_creation_rate": 0.4,
        "delivery_completion_rate": 1.0,
        "unique_sessions_with_chat_requested": 4,
        "unique_sessions_with_chat_replied": 4,
        "unique_sessions_with_lead_delivery_requested": 2,
        "unique_sessions_with_lead_created": 2,
        "unique_sessions_with_lead_delivery_completed": 2,
        "session_reply_rate": 1.0,
        "session_lead_creation_rate": 0.5,
        "session_delivery_completion_rate": 1.0,
    }


def test_scaffold_chat_endpoint_uses_runtime(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.apps.scaffold_web_agent.tenants import Tenant
    from backend.main import app

    client = TestClient(app)

    class DummyTenantService:
        def resolve_by_widget_token(self, widget_token: str):
            assert widget_token == "tok_test"
            return Tenant(
                tenant_id="tenant-a",
                widget_token="tok_test",
                inbox_email="hello@example.com",
                subject_prefix="[Scaffold]",
                allowed_origins=["http://localhost"],
                agent_type="scaffold_web_agent",
            )

    class DummyRuntime:
        def process_chat(self, *, tenant, client_ip, session_id, message, mailer):
            assert tenant.tenant_id == "tenant-a"
            assert tenant.agent_type == "scaffold_web_agent"
            assert session_id == "sess-1"
            assert message == "hola"

            class Result:
                reply = "respuesta desde runtime"
                step = "confirm"
                is_done = False

            return Result()

    class DummyRegistry:
        def get(self, agent_name: str):
            assert agent_name == "scaffold_web_agent"
            return DummyRuntime()

    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.api._tenant_service",
        DummyTenantService(),
    )
    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.api._registry",
        DummyRegistry(),
    )

    response = client.post(
        "/scaffold-agent/chat",
        headers={"X-Widget-Token": "tok_test"},
        json={"session_id": "sess-1", "message": "hola"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "respuesta desde runtime",
        "step": "confirm",
        "is_done": False,
    }


def test_admin_list_events_uses_event_service(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)

    class DummyEventService:
        def list_for_tenant(self, tenant_id: str, limit: int = 100) -> list[dict]:
            assert tenant_id == "tenant-a"
            assert limit == 7
            return [
                {
                    "id": 1,
                    "tenant_id": "tenant-a",
                    "session_id": "sess-1",
                    "event_type": "chat_requested",
                    "event_payload_json": '{"message_length": 4}',
                    "created_at": 123456,
                }
            ]

    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.api._event_service",
        DummyEventService(),
    )
    monkeypatch.setenv("ADMIN_TOKEN", "admin-secret")

    response = client.get(
        "/scaffold-agent/admin/events/tenant-a?limit=7",
        headers={"X-Admin-Token": "admin-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": "tenant-a",
        "events": [
            {
                "id": 1,
                "tenant_id": "tenant-a",
                "session_id": "sess-1",
                "event_type": "chat_requested",
                "event_payload_json": '{"message_length": 4}',
                "created_at": 123456,
            }
        ],
    }


def test_admin_list_events_requires_admin_token(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    monkeypatch.setenv("ADMIN_TOKEN", "admin-secret")

    response = client.get("/scaffold-agent/admin/events/tenant-a")

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


def test_scaffold_chat_endpoint_uses_runtime_from_tenant_agent_type(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.apps.scaffold_web_agent.tenants import Tenant
    from backend.main import app

    client = TestClient(app)

    class DummyTenantService:
        def resolve_by_widget_token(self, widget_token: str):
            assert widget_token == "tok_test"
            return Tenant(
                tenant_id="tenant-a",
                widget_token="tok_test",
                inbox_email="hello@example.com",
                subject_prefix="[Scaffold]",
                allowed_origins=["http://localhost"],
                agent_type="special-agent",
            )

    class DummyRuntime:
        def process_chat(self, *, tenant, client_ip, session_id, message, mailer):
            assert tenant.agent_type == "special-agent"
            assert session_id == "sess-1"
            assert message == "hola"

            class Result:
                reply = "respuesta desde runtime especifico"
                step = "confirm"
                is_done = False

            return Result()

    class DummyRegistry:
        def get(self, agent_name: str):
            assert agent_name == "special-agent"
            return DummyRuntime()

    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.api._tenant_service",
        DummyTenantService(),
    )
    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.api._registry",
        DummyRegistry(),
    )

    response = client.post(
        "/scaffold-agent/chat",
        headers={"X-Widget-Token": "tok_test"},
        json={"session_id": "sess-1", "message": "hola"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "respuesta desde runtime especifico",
        "step": "confirm",
        "is_done": False,
    }


def test_scaffold_chat_endpoint_routes_to_echo_runtime_by_tenant_agent_type(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.apps.scaffold_web_agent.tenants import Tenant
    from backend.main import app

    client = TestClient(app)

    class DummyTenantService:
        def resolve_by_widget_token(self, widget_token: str):
            assert widget_token == "tok_echo"
            return Tenant(
                tenant_id="tenant-echo",
                widget_token="tok_echo",
                inbox_email="echo@example.com",
                subject_prefix="[Echo]",
                allowed_origins=["http://localhost"],
                agent_type="echo_web_agent",
            )

    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.api._tenant_service",
        DummyTenantService(),
    )

    response = client.post(
        "/scaffold-agent/chat",
        headers={"X-Widget-Token": "tok_echo"},
        json={"session_id": "sess-echo-1", "message": "hola echo"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "[echo:tenant-echo] hola echo",
        "step": "done",
        "is_done": True,
    }


def test_admin_get_tenant_knowledge(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)

    class DummyTenantService:
        def list_all(self):
            return [
                {
                    "tenant_id": "tenant-a",
                    "agent_type": "scaffold_web_agent",
                    "knowledge_text": "Horario: L-V 9:00-18:00",
                }
            ]

    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.api._tenant_service",
        DummyTenantService(),
    )
    monkeypatch.setenv("ADMIN_TOKEN", "admin-secret")

    response = client.get(
        "/scaffold-agent/admin/knowledge/tenant-a",
        headers={"X-Admin-Token": "admin-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": "tenant-a",
        "agent_type": "scaffold_web_agent",
        "knowledge_text": "Horario: L-V 9:00-18:00",
    }
