from fastapi import HTTPException

from backend.agents.scaffold_web_agent.chat_service import ChatApplicationService
from backend.agents.scaffold_web_agent.domain import SessionState, Status, Step
from backend.agents.scaffold_web_agent.tenants import Tenant


def make_tenant() -> Tenant:
    return Tenant(
        tenant_id="tenant-a",
        widget_token="tok_123",
        inbox_email="hello@example.com",
        subject_prefix="[Scaffold]",
        allowed_origins=["http://localhost"],
        agent_type="scaffold_web_agent",
    )


class DummySessionService:
    def __init__(self, state=None):
        self.state = state or SessionState()
        self.saved = None

    def get_state(self, tenant_id: str, session_id: str):
        return self.state

    def save_state(self, tenant_id: str, session_id: str, state):
        self.saved = (tenant_id, session_id, state)


class DummyLeadService:
    def __init__(self):
        self.created = None

    def create_lead(self, tenant_id: str, session_id: str, email, topic, summary):
        self.created = {
            "tenant_id": tenant_id,
            "session_id": session_id,
            "email": email,
            "topic": topic,
            "summary": summary,
        }


class DummyMailer:
    def __init__(self):
        self.sent = None

    def send(self, to_email: str, subject: str, body: str) -> None:
        self.sent = {
            "to_email": to_email,
            "subject": subject,
            "body": body,
        }


class DummyDeliveryService:
    def __init__(self):
        self.delivered = None

    def deliver_lead(self, *, tenant, category_value, summary, mailer) -> None:
        self.delivered = {
            "tenant": tenant,
            "category_value": category_value,
            "summary": summary,
            "mailer": mailer,
        }


class DummyEventService:
    def __init__(self):
        self.events = []

    def record(self, *, tenant_id, session_id, event_type, event_payload=None) -> None:
        self.events.append(
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "event_type": event_type,
                "event_payload": event_payload or {},
            }
        )


def test_chat_service_processes_regular_message(monkeypatch):
    tenant = make_tenant()
    session_service = DummySessionService()
    lead_service = DummyLeadService()
    delivery_service = DummyDeliveryService()
    event_service = DummyEventService()

    service = ChatApplicationService(
        session_service=session_service,
        lead_service=lead_service,
        delivery_service=delivery_service,
        event_service=event_service,
    )

    def fake_is_rate_limited(tenant_id: str, client_ip: str) -> bool:
        assert tenant_id == "tenant-a"
        assert client_ip == "127.0.0.1"
        return False

    def fake_handle_user_message(state, message):
        assert message == "hola"
        new_state = SessionState()
        new_state.step = Step.CONFIRM
        return new_state, "respuesta"

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.chat_service.is_rate_limited",
        fake_is_rate_limited,
    )
    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.chat_service.handle_user_message",
        fake_handle_user_message,
    )

    result = service.process_chat(
        tenant=tenant,
        client_ip="127.0.0.1",
        session_id="sess-1",
        message="hola",
        mailer=DummyMailer(),
    )

    assert result.reply == "respuesta"
    assert result.step == Step.CONFIRM.value
    assert result.is_done is False
    assert session_service.saved is not None
    assert session_service.saved[0] == "tenant-a"
    assert session_service.saved[1] == "sess-1"
    assert session_service.saved[2].step == Step.CONFIRM
    assert lead_service.created is None


def test_chat_service_send_flow_sends_email_creates_lead_and_marks_done(monkeypatch):
    tenant = make_tenant()
    session_service = DummySessionService()
    lead_service = DummyLeadService()
    delivery_service = DummyDeliveryService()
    event_service = DummyEventService()
    mailer = DummyMailer()

    service = ChatApplicationService(
        session_service=session_service,
        lead_service=lead_service,
        delivery_service=delivery_service,
        event_service=event_service,
    )

    def fake_is_rate_limited(tenant_id: str, client_ip: str) -> bool:
        return False

    def fake_handle_user_message(state, message):
        new_state = SessionState()
        new_state.step = Step.SEND
        new_state.data.email = "lead@example.com"
        new_state.data.topic = "pricing"
        new_state.data.summary = "Lead summary"
        new_state.data.status = Status.READY_TO_SEND
        new_state.data.category = None
        return new_state, "sending"

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.chat_service.is_rate_limited",
        fake_is_rate_limited,
    )
    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.chat_service.handle_user_message",
        fake_handle_user_message,
    )

    service.process_chat(
        tenant=tenant,
        client_ip="127.0.0.1",
        session_id="sess-1",
        message="confirmar",
        mailer=mailer,
    )

    assert delivery_service.delivered is not None
    assert delivery_service.delivered["tenant"].tenant_id == "tenant-a"
    assert delivery_service.delivered["category_value"] is None
    assert delivery_service.delivered["summary"] == "Lead summary"
    assert delivery_service.delivered["mailer"] is mailer
    assert [event["event_type"] for event in event_service.events] == [
        "chat_requested",
        "chat_replied",
        "lead_delivery_requested",
        "lead_created",
        "lead_delivery_completed",
    ]


def test_chat_service_returns_429_when_rate_limited(monkeypatch):
    tenant = make_tenant()

    service = ChatApplicationService(
        session_service=DummySessionService(),
        lead_service=DummyLeadService(),
        delivery_service=DummyDeliveryService(),
        event_service=DummyEventService(),
    )

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.chat_service.is_rate_limited",
        lambda tenant_id, client_ip: True,
    )

    try:
        service.process_chat(
            tenant=tenant,
            client_ip="127.0.0.1",
            session_id="sess-1",
            message="hola",
            mailer=DummyMailer(),
        )
        raise AssertionError("Expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 429
