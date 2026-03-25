from backend.apps.scaffold_web_agent.runtime import RuntimeResult
from backend.apps.scaffold_web_agent.scaffold_runtime import ScaffoldAgentRuntime


def test_scaffold_runtime_process_chat_returns_runtime_result():
    class DummyChatService:
        def process_chat(self, **kwargs):
            class Result:
                reply = "reply"
                step = "done"
                is_done = True

            return Result()

    runtime = ScaffoldAgentRuntime(chat_service=DummyChatService())

    from backend.apps.scaffold_web_agent.tenants import Tenant

    tenant = Tenant(
        tenant_id="tenant-a",
        widget_token="tok_123",
        inbox_email="hello@example.com",
        subject_prefix="[Scaffold]",
        allowed_origins=["http://localhost"],
        agent_type="scaffold_web_agent",
    )

    result = runtime.process_chat(
        tenant=tenant,
        client_ip="127.0.0.1",
        session_id="sess-1",
        message="hola",
        mailer=object(),
    )

    assert isinstance(result, RuntimeResult)
    assert result.reply == "reply"
    assert result.step == "done"
    assert result.is_done is True
