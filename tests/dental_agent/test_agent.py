from backend.agents.dental_agent.agent import respond


def test_faq_flow():
    reply, sources = respond("Horario y sábados")
    # El formato puede variar: aceptamos 'lunes', 'sáb', 'sábado' o la abreviatura
    reply_lower = (reply or "").lower()
    assert any(tok in reply_lower for tok in ("l-v", "lunes", "sáb", "sabado", "sábado"))
    assert sources


def test_cita_flow():
    reply, sources = respond("Quiero una cita para limpieza mañana")
    assert "nombre y apellido" in (reply.lower())
    assert sources == []


def test_humano_flow():
    reply, _ = respond("Prefiero hablar con una persona")
    reply_lower = (reply or "").lower()
    assert any(
        tok in reply_lower for tok in ("recepción", "te paso", "te llamen", "nombre", "teléfono")
    )


def test_otro_flow():
    reply, _ = respond("hola")
    reply_lower = (reply or "").lower()
    assert "¿en qué puedo ayudarte" in reply_lower
    assert "solicitar una cita" in reply_lower
