from __future__ import annotations

import os
from functools import lru_cache

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from backend.agents.lead_capture_agent.domain import Step

from .admin_template import admin_html
from .agent_registry import AgentRegistry
from .analytics_service import AnalyticsService
from .chat_service import ChatApplicationService
from .delivery_service import DeliveryService
from .demo_template import demo_html
from .echo_runtime import EchoAgentRuntime
from .event_service import EventService
from .lead_service import LeadService
from .mailer import FakeMailer, Mailer, load_prod_mailer
from .scaffold_runtime import ScaffoldAgentRuntime
from .session_service import SessionService
from .settings import load_settings
from .tenant_service import TenantService
from .tenants import Tenant
from .widget_template import widget_js

router = APIRouter(prefix="/scaffold-agent", tags=["scaffold-agent"])

_session_service = SessionService()
_tenant_service = TenantService()
_lead_service = LeadService()
_delivery_service = DeliveryService()
_event_service = EventService()
_analytics_service = AnalyticsService()
_chat_service = ChatApplicationService(
    session_service=_session_service,
    lead_service=_lead_service,
    delivery_service=_delivery_service,
    event_service=_event_service,
)
_runtime = ScaffoldAgentRuntime(chat_service=_chat_service)
_echo_runtime = EchoAgentRuntime()

_registry = AgentRegistry()
_registry.register(_runtime)
_registry.register(_echo_runtime)


class ChatIn(BaseModel):
    session_id: str = Field(..., description="Client-generated stable session id")
    message: str


class ChatOut(BaseModel):
    reply: str
    step: str
    is_done: bool


@lru_cache(maxsize=1)
def get_settings():
    return load_settings()


def get_mailer() -> Mailer:
    if os.getenv("SCAFFOLD_ENV", "dev") == "dev":
        return FakeMailer()
    return load_prod_mailer()


@router.options("/chat")
def chat_options():
    return Response(status_code=204)


@router.post("/chat", response_model=ChatOut)
def chat(
    request: Request,
    payload: ChatIn,
    mailer: Mailer = Depends(get_mailer),  # noqa: B008
    x_widget_token: str = Header(default="", alias="X-Widget-Token"),
    token: str = Query(default=""),
) -> ChatOut:
    widget_token = x_widget_token or token
    client_ip = request.client.host if request.client else "unknown"

    tenant = _tenant_service.resolve_by_widget_token(widget_token)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Widget-Token")

    runtime = _registry.get(tenant.agent_type)

    result = runtime.process_chat(
        tenant=tenant,
        client_ip=client_ip,
        session_id=payload.session_id,
        message=payload.message,
        mailer=mailer,
    )

    return ChatOut(
        reply=result.reply,
        step=result.step,
        is_done=result.is_done,
    )


@router.post("/chat/stream")
def chat_stream(
    request: Request,
    payload: ChatIn,
    mailer: Mailer = Depends(get_mailer),  # noqa: B008
    x_widget_token: str = Header(default="", alias="X-Widget-Token"),
    token: str = Query(default=""),
):
    """
    Endpoint streaming con SSE.
    Devuelve la respuesta de Claude chunk a chunk mientras se genera.
    Solo disponible para tenants con knowledge_text (motor LLM).
    """
    widget_token = x_widget_token or token

    tenant = _tenant_service.resolve_by_widget_token(widget_token)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Widget-Token")

    if not tenant.knowledge_text:
        raise HTTPException(status_code=400, detail="Streaming only available for LLM tenants")

    state = _session_service.get_state(tenant.tenant_id, payload.session_id)

    from .llm_engine import stream_user_message_llm

    # El callback guarda el estado final cuando el stream termina
    def on_complete(new_state, clean_reply):
        _session_service.save_state(tenant.tenant_id, payload.session_id, new_state)

        # Procesamos el lead si corresponde — igual que en chat normal
        if new_state.step == Step.SEND:
            _delivery_service.deliver_lead(
                tenant=tenant,
                category_value=new_state.data.category.value if new_state.data.category else None,
                summary=new_state.data.summary,
                mailer=mailer,
            )
            _lead_service.create_lead(
                tenant_id=tenant.tenant_id,
                session_id=payload.session_id,
                email=new_state.data.email,
                topic=new_state.data.topic,
                summary=new_state.data.summary,
            )

    return StreamingResponse(
        stream_user_message_llm(
            state,
            payload.message,
            tenant.knowledge_text,
            on_complete=on_complete,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class TenantUpsertIn(BaseModel):
    tenant_id: str
    widget_token: str
    inbox_email: str
    subject_prefix: str = "[Web Lead Agent]"
    allowed_origins: list[str]
    agent_type: str = "scaffold_web_agent"
    knowledge_text: str = ""


@router.post("/admin/tenants/upsert")
def admin_upsert_tenant(
    payload: TenantUpsertIn,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    import os

    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    _tenant_service.upsert(
        Tenant(
            tenant_id=payload.tenant_id.strip(),
            widget_token=payload.widget_token.strip(),
            inbox_email=payload.inbox_email.strip(),
            subject_prefix=payload.subject_prefix.strip(),
            allowed_origins=payload.allowed_origins,
            agent_type=payload.agent_type.strip() or "scaffold_web_agent",
            knowledge_text=payload.knowledge_text.strip(),
        )
    )
    return {"ok": True}


@router.get("/widget.js")
def serve_widget_js():
    return Response(content=widget_js(), media_type="application/javascript; charset=utf-8")


@router.get("/demo", response_class=HTMLResponse)
def serve_demo_page(token: str = Query(default="")):
    return HTMLResponse(content=demo_html(token))


@router.get("/admin/page", response_class=HTMLResponse)
def serve_admin_page():
    return HTMLResponse(content=admin_html())


@router.post("/admin/tenants/{tenant_id}/rotate-token")
def admin_rotate_token(
    tenant_id: str,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    import os

    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    new_token = _tenant_service.rotate_token(tenant_id)

    return {
        "tenant_id": tenant_id,
        "new_widget_token": new_token,
    }


@router.post("/admin/tenants/{tenant_id}/revoke-token")
def admin_revoke_token(
    tenant_id: str,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    import os

    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    _tenant_service.revoke_token(tenant_id)

    return {
        "tenant_id": tenant_id,
        "status": "revoked",
    }


@router.get("/admin/tenants")
def admin_list_tenants(
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    import os

    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    return {
        "tenants": _tenant_service.list_all(),
    }


@router.get("/admin/knowledge/{tenant_id}")
def admin_get_tenant_knowledge(
    tenant_id: str,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    import os

    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    tenants = _tenant_service.list_all()
    for tenant in tenants:
        if tenant["tenant_id"] == tenant_id:
            return {
                "tenant_id": tenant_id,
                "agent_type": tenant.get("agent_type", "scaffold_web_agent"),
                "knowledge_text": tenant.get("knowledge_text", ""),
            }

    raise HTTPException(status_code=404, detail="Tenant not found")


@router.get("/admin/sessions/{tenant_id}")
def admin_list_sessions(
    tenant_id: str,
    limit: int = 20,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    import os

    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    return {
        "tenant_id": tenant_id,
        "sessions": _session_service.list_for_tenant(tenant_id, limit),
    }


@router.get("/admin/leads/{tenant_id}")
def admin_list_leads(
    tenant_id: str,
    limit: int = 50,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    import os

    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    return {
        "tenant_id": tenant_id,
        "leads": _lead_service.list_for_tenant(tenant_id, limit),
    }


@router.get("/admin/events/{tenant_id}")
def admin_list_events(
    tenant_id: str,
    limit: int = 100,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    import os

    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    return {
        "tenant_id": tenant_id,
        "events": _event_service.list_for_tenant(tenant_id, limit),
    }


@router.get("/admin/analytics/{tenant_id}")
def admin_tenant_analytics(
    tenant_id: str,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    import os

    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    return _analytics_service.tenant_summary(tenant_id)
