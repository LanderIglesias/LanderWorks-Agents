import backend.agents.dental_agent.notify as notify
from backend.agents.dental_agent.agent import respond
from backend.agents.dental_agent.store import get_state, reset_state


def test_handoff_flow_calls_email(monkeypatch):
    sender = "scenario-email-handoff"
    reset_state(sender)

    called = {"n": 0, "subject": None, "body": None}

    def fake_send(subject: str, body: str) -> bool:
        called["n"] += 1
        called["subject"] = subject
        called["body"] = body
        return True

    monkeypatch.setattr(notify, "send_handoff_email", fake_send)

    # Completa booking -> handoff
    respond("Quiero cita", sender=sender)
    respond("Lander Iglesias", sender=sender)
    respond("612345678", sender=sender)
    respond("Limpieza", sender=sender)
    respond("No es urgente", sender=sender)
    respond("Por la tarde", sender=sender)

    st = get_state(sender)
    assert st.step == "handoff"

    # Si esto falla (n==0), significa que no estás llamando al notify en tu flujo real.
    assert called["n"] >= 1
    assert "612345678" in (called["body"] or "")
