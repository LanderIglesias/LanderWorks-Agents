from uuid import uuid4

from backend.agents.dental_agent.agent import respond
from backend.agents.dental_agent.store import get_state, reset_state


def test_booking_asks_name_and_surname_and_requires_two_words():
    sender = f"scenario-name-surname-{uuid4()}"
    reset_state(sender)

    r1, _ = respond("Quiero cita", sender=sender)
    assert "nombre y apellido" in r1.lower()

    r2, _ = respond("Lander", sender=sender)
    # Debe repreguntar (solo nombre)
    assert "nombre y apellido" in r2.lower()

    r3, _ = respond("Lander Iglesias", sender=sender)
    # Debe agradecer SOLO con el nombre
    assert "gracias, lander." in r3.lower()

    st = get_state(sender)
    assert st.step == "phone"
    assert (st.nombre or "").lower() == "lander iglesias"
