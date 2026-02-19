import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from .agent import respond, route_message
from .config import settings
from .metrics import snapshot
from .notify import send_handoff_email
from .rag import ingest_markdown
from .schemas import ChatIn
from .store import close_handoff, get_state, list_handoffs
from .tools import _cfg, _norm_q, validate_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        n = ingest_markdown()
        print(f"[RAG] Ingeridas {n} secciones")
    except Exception as e:
        print("[RAG] fallo de ingesta:", e)

    try:
        errs = validate_config()
        if errs:
            print("[CONFIG] Errores de configuración:")
            for e in errs:
                print(" -", e)
        else:
            print("[CONFIG] clinic_config.yaml OK")
    except Exception as e:
        print("[CONFIG] fallo validando config:", e)

    yield


app = FastAPI(title="Dental Agent", lifespan=lifespan)


@app.post("/chat")
def chat(inp: ChatIn):
    print("DEBUG ChatIn:", inp.model_dump())
    reply, sources = respond(inp.user, sender=inp.sender)
    print("DEBUG respond:", reply, sources, type(sources))
    return {"reply": reply, "sources": sources}


@app.post("/admin/reload-config")
def reload_config():
    # invalidar caché leyendo una vez
    from importlib import reload

    import backend.tools as tools

    reload(tools)
    return {"ok": True}


def _validate_twilio(request: Request, form: dict) -> bool:
    """
    Valida que el POST viene de Twilio.
    - Si TWILIO_VALIDATE_SIGNATURE=False => no valida (tests/dev).
    - Si True => requiere token + signature válida.
    """
    if not getattr(settings, "TWILIO_VALIDATE_SIGNATURE", True):
        return True

    token = (getattr(settings, "TWILIO_AUTH_TOKEN", "") or "").strip()
    if not token:
        return False  # si quieres obligar en prod: sin token, no aceptes

    sig = request.headers.get("X-Twilio-Signature", "")
    if not sig:
        return False

    url = str(request.url)
    validator = RequestValidator(token)
    return validator.validate(url, form, sig)


@app.post("/webhook/twilio")
async def twilio_webhook(request: Request):
    form = await request.form()
    body = str(form.get("Body", "")).strip()
    sender = str(form.get("From", "twilio")).strip()

    try:
        reply, _sources = respond(body, sender=sender)
    except Exception as e:
        print(f"[TWILIO] ERROR respond(): {type(e).__name__}: {e}")
        reply = "Perdona, ha habido un problema técnico. ¿Puedes repetir el mensaje?"

    if not reply or not str(reply).strip():
        reply = "Perdona, no te he leído bien. ¿Puedes repetirlo?"

    twiml = MessagingResponse()
    twiml.message(str(reply))

    return Response(content=str(twiml), media_type="application/xml")


@app.get("/admin/metrics")
def metrics():
    return snapshot()


@app.get("/", include_in_schema=False)
def root():
    return HTMLResponse('<h3>Dental Agent</h3><p><a href="/docs">/docs</a></p>')


@app.get("/admin/handoffs")
def admin_handoffs(status: str = "open", limit: int = 20):
    return {"handoffs": list_handoffs(limit=limit, status=status)}


@app.post("/admin/handoffs/{handoff_id}/close")
def admin_close_handoff(handoff_id: int):
    ok = close_handoff(handoff_id)
    return {"ok": ok, "id": handoff_id}


@app.post("/admin/reindex")
def reindex():
    md_path = Path(__file__).resolve().parent / "data" / "dental_faq.md"
    n = ingest_markdown(str(md_path))
    return {"ok": True, "chunks": n, "source": str(md_path)}


@app.get("/admin/config")
def show_config():
    c = _cfg().copy()
    c["address"] = c.get("address", "")
    return {"address": c.get("address"), "map_url": c.get("map_url")}


@app.get("/admin/routes")
def admin_routes():
    return sorted(
        [{"path": r.path, "methods": sorted(list(r.methods or []))} for r in app.routes],
        key=lambda x: x["path"],
    )


@app.post("/admin/test-email")
def admin_test_email():
    subject = "[TEST] Dental Agent – Email OK"
    body = (
        "Este es un email de prueba del Dental Agent.\n\n"
        "Si estás leyendo esto, el envío SMTP funciona correctamente."
    )

    ok = send_handoff_email(subject, body)

    return {"ok": ok}


@app.get("/admin/debug-route")
def debug_route(q: str):
    sender = "debug"
    st = get_state(sender)  # importa get_state arriba si no lo tienes
    decision = route_message(sender, q, st)

    return JSONResponse(
        {
            "raw": q,
            "norm": _norm_q(q) if "_norm_q" in globals() else None,
            "decision": {
                "name": decision.name,
                "reason": decision.reason,
                "faq_keys": getattr(decision, "faq_keys", None),
            },
            "render_commit": os.getenv("RENDER_GIT_COMMIT"),
        }
    )
