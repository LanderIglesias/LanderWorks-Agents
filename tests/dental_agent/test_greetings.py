from uuid import uuid4

from backend.agents.dental_agent.agent import respond
from backend.agents.dental_agent.store import reset_state


def test_buenos_dias_is_smalltalk():
    sender = f"scenario-greet-{uuid4()}"
    reset_state(sender)

    reply, _ = respond("Buenos días", sender=sender)
    assert "¿En qué puedo ayudarte?" in reply


def test_buenos_dias_with_exclamation_is_smalltalk():
    sender = f"scenario-greet2-{uuid4()}"
    reset_state(sender)

    reply, _ = respond("¡Buenos días!", sender=sender)
    assert "¿En qué puedo ayudarte?" in reply
