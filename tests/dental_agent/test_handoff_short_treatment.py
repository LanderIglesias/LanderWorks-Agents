from uuid import uuid4

from backend.agents.dental_agent.agent import respond
from backend.agents.dental_agent.store import get_state, reset_state, save_state


def test_handoff_short_treatment_is_not_treated_as_noise():
    sender = f"scenario-handoff-empaste-{uuid4()}"
    reset_state(sender)

    # Forzamos modo handoff
    st = get_state(sender)
    st.step = "handoff"
    st.status = "needs_human"
    save_state(sender, st)

    reply, _ = respond("Empaste", sender=sender)

    # No debe responder con el texto genérico de handoff
    assert "Si quieres añadir algún detalle útil para recepción" not in reply
