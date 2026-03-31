from fastapi.testclient import TestClient

import backend.main as mainmod

client = TestClient(mainmod.app)


def test_twilio_webhook_dedupes_same_message_sid(monkeypatch):
    called = {"n": 0}

    def fake_process(form: dict):
        called["n"] += 1

    monkeypatch.setattr(mainmod, "process_twilio_message", fake_process)

    data = {"Body": "Hola", "From": "whatsapp:+34600000000", "MessageSid": "SM_DUP_1"}

    r1 = client.post("/webhook/twilio", data=data)
    r2 = client.post("/webhook/twilio", data=data)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert called["n"] == 1
