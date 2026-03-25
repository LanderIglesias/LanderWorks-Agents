import pytest

from backend.apps.scaffold_web_agent.agent_registry import AgentRegistry


class DummyRuntime:
    def __init__(self, name):
        self.agent_name = name


def test_registry_register_and_get():
    registry = AgentRegistry()
    runtime = DummyRuntime("agent-a")

    registry.register(runtime)

    assert registry.get("agent-a") is runtime


def test_registry_get_default_returns_first():
    registry = AgentRegistry()

    r1 = DummyRuntime("a")
    r2 = DummyRuntime("b")

    registry.register(r1)
    registry.register(r2)

    assert registry.get_default() is r1


def test_registry_get_raises_for_unknown():
    registry = AgentRegistry()

    with pytest.raises(ValueError):
        registry.get("unknown")


def test_registry_get_default_raises_if_empty():
    registry = AgentRegistry()

    with pytest.raises(ValueError):
        registry.get_default()


def test_registry_can_hold_multiple_runtimes():
    from backend.apps.scaffold_web_agent.echo_runtime import EchoAgentRuntime
    from backend.apps.scaffold_web_agent.scaffold_runtime import ScaffoldAgentRuntime

    class DummyChatService:
        def process_chat(self, **kwargs):
            class Result:
                reply = "ok"
                step = "confirm"
                is_done = False

            return Result()

    registry = AgentRegistry()
    scaffold_runtime = ScaffoldAgentRuntime(chat_service=DummyChatService())
    echo_runtime = EchoAgentRuntime()

    registry.register(scaffold_runtime)
    registry.register(echo_runtime)

    assert registry.get("scaffold_web_agent") is scaffold_runtime
    assert registry.get("echo_web_agent") is echo_runtime
