from __future__ import annotations

from twilio.rest import Client

from .config import settings

_client: Client | None = None


def _as_whatsapp(addr: str) -> str:
    a = (addr or "").strip()
    if not a:
        return a
    return a if a.startswith("whatsapp:") else f"whatsapp:{a}"


def _get_client() -> Client | None:
    global _client

    sid = (settings.TWILIO_ACCOUNT_SID or "").strip()
    token = (settings.TWILIO_AUTH_TOKEN or "").strip()

    if not sid or not token:
        return None

    if _client is None:
        _client = Client(sid, token)

    return _client


def send_whatsapp_message(to: str, body: str) -> bool:
    """
    Envia WhatsApp vía Twilio REST.
    Devuelve True si lo intenta y Twilio acepta la request; False si está deshabilitado o falla.
    NUNCA debe lanzar KeyError por config faltante.
    """
    from_whatsapp = _as_whatsapp(settings.TWILIO_WHATSAPP_FROM or "")
    to_whatsapp = _as_whatsapp(to)
    if not from_whatsapp:
        print("[TWILIO_SEND] disabled: missing TWILIO_WHATSAPP_FROM")
        return False

    client = _get_client()
    if client is None:
        print("[TWILIO_SEND] disabled: missing TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN")
        return False

    try:
        client.messages.create(
            from_=from_whatsapp,
            to=to_whatsapp,
            body=body,
        )
        return True
    except Exception as e:
        print(f"[TWILIO_SEND] ERROR: {type(e).__name__}: {e}")
        return False
