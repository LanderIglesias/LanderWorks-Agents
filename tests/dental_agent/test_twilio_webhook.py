from fastapi.testclient import TestClient

import backend.main as mainmod
from backend.agents.dental_agent.store import reset_state

client = TestClient(mainmod.app)


def test_twilio_webhook_returns_200_and_enqueues_processing(monkeypatch):
    sender = "whatsapp:+34600000000"
    reset_state(sender)

    called = {"n": 0, "form": None}

    def fake_process(form: dict):
        called["n"] += 1
        called["form"] = form

    monkeypatch.setattr(mainmod, "process_twilio_message", fake_process)

    r = client.post(
        "/webhook/twilio",
        data={"Body": "Quiero cita", "From": sender, "MessageSid": "SM_TEST_1"},
    )

    assert r.status_code == 200
    assert called["n"] == 1
    assert called["form"]["Body"] == "Quiero cita"
    assert called["form"]["From"] == sender
