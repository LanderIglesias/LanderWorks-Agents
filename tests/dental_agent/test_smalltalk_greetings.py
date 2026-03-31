from uuid import uuid4

from backend.agents.dental_agent.agent import respond
from backend.agents.dental_agent.store import reset_state


def test_pure_greeting_in_basque_routes_to_smalltalk():
    sender = f"scenario-greeting-{uuid4()}"
    reset_state(sender)

    reply, _ = respond("Aupa", sender=sender)

    assert "¿En qué puedo ayudarte?" in reply
