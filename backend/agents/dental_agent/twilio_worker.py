from .agent import respond
from .twilio_client import send_whatsapp_message


def process_twilio_message(form: dict) -> None:
    body = str(form.get("Body", "")).strip()
    sender = str(form.get("From", "")).strip()

    try:
        reply, _ = respond(body, sender=sender)
        if not reply or not str(reply).strip():
            reply = "Perdona, no te he leído bien. ¿Puedes repetirlo?"
    except Exception as e:
        print(f"[TWILIO_WORKER] ERROR: {type(e).__name__}: {e}")
        reply = "Perdona, ha habido un problema técnico. ¿Puedes repetir el mensaje?"

    ok = send_whatsapp_message(sender, reply)
    if not ok:
        print("[TWILIO_SEND] send skipped/failed")
