from backend.agents.scaffold_web_agent.runtime import RuntimeResult
from backend.agents.scaffold_web_agent.scaffold_runtime import ScaffoldAgentRuntime
from backend.agents.scaffold_web_agent.tenants import Tenant


class DummyChatService:
    def __init__(self):
        self.called_with = None

    def process_chat(
        self,
        *,
        tenant,
        client_ip: str,
        session_id: str,
        message: str,
        mailer,
    ):
        self.called_with = {
            "tenant": tenant,
            "client_ip": client_ip,
            "session_id": session_id,
            "message": message,
            "mailer": mailer,
        }

        class Result:
            reply = "ok"
            step = "confirm"
            is_done = False

        return Result()


class DummyMailer:
    pass


def make_tenant() -> Tenant:
    return Tenant(
        tenant_id="tenant-a",
        widget_token="tok_123",
        inbox_email="hello@example.com",
        subject_prefix="[Scaffold]",
        allowed_origins=["http://localhost"],
        agent_type="scaffold_web_agent",
    )


def test_scaffold_runtime_exposes_agent_name():
    runtime = ScaffoldAgentRuntime(chat_service=DummyChatService())
    assert runtime.agent_name == "scaffold_web_agent"


def test_scaffold_runtime_delegates_to_chat_service():
    chat_service = DummyChatService()
    runtime = ScaffoldAgentRuntime(chat_service=chat_service)
    mailer = DummyMailer()

    tenant = make_tenant()

    result = runtime.process_chat(
        tenant=tenant,
        client_ip="127.0.0.1",
        session_id="sess-1",
        message="hola",
        mailer=mailer,
    )

    assert isinstance(result, RuntimeResult)
    assert result.reply == "ok"
    assert result.step == "confirm"
    assert result.is_done is False
    assert chat_service.called_with == {
        "tenant": tenant,
        "client_ip": "127.0.0.1",
        "session_id": "sess-1",
        "message": "hola",
        "mailer": mailer,
    }
