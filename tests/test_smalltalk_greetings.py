from uuid import uuid4

from backend.agent import respond
from backend.store import reset_state


def test_pure_greeting_in_basque_routes_to_smalltalk():
    sender = f"scenario-greeting-{uuid4()}"
    reset_state(sender)

    reply, _ = respond("Aupa", sender=sender)

    assert "¿En qué puedo ayudarte?" in reply
