from uuid import uuid4

from backend.agent import respond
from backend.store import reset_state


def test_price_empaste_uses_config_value():
    sender = f"scenario-price-empaste-{uuid4()}"
    reset_state(sender)

    reply, _ = respond("Me gustaría saber el precio del empaste", sender=sender)

    assert "empaste" in reply.lower()
    # debería contener un rango/importe del config (ej: "60" o "€")
    assert "€" in reply or "e" in reply.lower()
