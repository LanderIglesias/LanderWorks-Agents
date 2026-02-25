from uuid import uuid4

import backend.notify as notify
from backend.agent import respond
from backend.store import get_state, reset_state


def _set_settings(monkeypatch, **kwargs):
    # settings es un objeto; parcheamos atributos directamente
    for k, v in kwargs.items():
        monkeypatch.setattr(notify.settings, k, v, raising=False)


def test_send_handoff_email_disabled_if_missing_config(monkeypatch):
    _set_settings(
        monkeypatch,
        RESEND_API_KEY="",
        NOTIFY_EMAIL_TO="",
        EMAIL_FROM="",
    )

    ok = notify.send_handoff_email("subj", "body")
    assert ok is False


def test_handoff_flow_calls_email(monkeypatch):
    sender = f"scenario-email-handoff-{uuid4()}"
    reset_state(sender)

    called = {"n": 0, "subject": None, "body": None}

    def fake_send(subject: str, body: str) -> bool:
        called["n"] += 1
        called["subject"] = subject
        called["body"] = body
        return True

    monkeypatch.setattr(notify, "send_handoff_email", fake_send)

    respond("Quiero cita", sender=sender)
    respond("Lander Iglesias", sender=sender)
    respond("612345678", sender=sender)
    respond("Limpieza", sender=sender)
    respond("No es urgente", sender=sender)
    respond("Por la tarde", sender=sender)

    st = get_state(sender)
    assert st.step == "handoff"
    import time

    # Espera corta a que el thread de notificación ejecute el mock
    deadline = time.time() + 1.0  # 1 segundo máximo
    while called["n"] < 1 and time.time() < deadline:
        time.sleep(0.01)

    assert called["n"] >= 1
    assert "612345678" in (called["body"] or "")
