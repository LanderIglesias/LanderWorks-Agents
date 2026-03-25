from backend.apps.scaffold_web_agent.echo_runtime import EchoAgentRuntime
from backend.apps.scaffold_web_agent.runtime import RuntimeResult
from backend.apps.scaffold_web_agent.tenants import Tenant


def make_echo_tenant() -> Tenant:
    return Tenant(
        tenant_id="tenant-echo",
        widget_token="tok_echo",
        inbox_email="echo@example.com",
        subject_prefix="[Echo]",
        allowed_origins=["http://localhost"],
        agent_type="echo_web_agent",
    )


def test_echo_runtime_exposes_agent_name():
    runtime = EchoAgentRuntime()
    assert runtime.agent_name == "echo_web_agent"


def test_echo_runtime_returns_done_result():
    runtime = EchoAgentRuntime()
    tenant = make_echo_tenant()

    result = runtime.process_chat(
        tenant=tenant,
        client_ip="127.0.0.1",
        session_id="sess-echo-1",
        message="hola mundo",
        mailer=object(),
    )

    assert isinstance(result, RuntimeResult)
    assert result.reply == "[echo:tenant-echo] hola mundo"
    assert result.step == "done"
    assert result.is_done is True
