from uuid import uuid4

from backend.agent import respond
from backend.store import reset_state


def test_question_like_never_falls_back_to_booking_pitch():
    sender = f"scenario-q-never-fallback-{uuid4()}"
    reset_state(sender)

    reply, _ = respond("Qué horarios tenéis?", sender=sender)

    assert "Puedo ayudarte a solicitar una cita" not in reply
