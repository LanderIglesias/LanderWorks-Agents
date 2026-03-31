from backend.agents.dental_agent import tools


def test_replace_placeholders_address_and_contact():
    tools._CFG = {
        "address": "C/ Falsa 123, Bilbao",
        "phone": "+34 600000000",
        "email": "hola@example.com",
        "map_url": "https://maps.example.com/clinic",
    }
    assert "C/ Falsa 123" in tools.replace_placeholders("Visítanos en [tu direccion]")
    assert "C/ Falsa 123" in tools.replace_placeholders("Dirección: [direccion]")
    assert "+34" in tools.replace_placeholders("Tel: [telefono]")
    assert "hola@example.com" in tools.replace_placeholders("Email: [email]")
    assert "maps.example.com" in tools.replace_placeholders("Mapa: [mapa]")


def test_get_contact_fallback_md():
    tools._CFG = {"address": "[tu direccion]"}  # placeholder en config -> fallback a MD
    reply = tools.get_contact()
    assert isinstance(reply, str) and reply != ""
