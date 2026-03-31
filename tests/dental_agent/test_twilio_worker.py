from backend.agents.dental_agent.twilio_worker import process_twilio_message


def test_twilio_worker_calls_send(monkeypatch):
    called = {}

    def fake_send(to, body):
        called["to"] = to
        called["body"] = body

    monkeypatch.setattr(
        "backend.agents.dental_agent.twilio_worker.send_whatsapp_message",
        fake_send,
    )

    form = {
        "From": "whatsapp:+34600000000",
        "Body": "Hola",
    }

    process_twilio_message(form)

    assert "to" in called
    assert called["to"] == "whatsapp:+34600000000"
