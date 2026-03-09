from __future__ import annotations

import os
from functools import lru_cache

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from backend.config import settings as global_settings

from .admin_template import admin_html
from .demo_template import demo_html
from .domain import Status, Step
from .engine import handle_user_message
from .mailer import FakeMailer, Mailer, load_prod_mailer
from .rate_limit import is_rate_limited
from .settings import ScaffoldAgentSettings, load_settings
from .sqlite_store import SQLiteSessionStore, list_sessions_for_tenant, tenant_analytics
from .tenants import (
    Tenant,
    list_tenants,
    resolve_tenant_by_token,
    revoke_widget_token,
    rotate_widget_token,
    upsert_tenant,
)
from .widget_template import widget_js

router = APIRouter(prefix="/scaffold-agent", tags=["scaffold-agent"])

_store = SQLiteSessionStore()


class ChatIn(BaseModel):
    session_id: str = Field(..., description="Client-generated stable session id")
    message: str


class ChatOut(BaseModel):
    reply: str
    step: str
    is_done: bool


@lru_cache(maxsize=1)
def get_settings() -> ScaffoldAgentSettings:
    return load_settings()


def get_mailer(settings: ScaffoldAgentSettings = Depends(get_settings)) -> Mailer:  # noqa: B008
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
    settings: ScaffoldAgentSettings = Depends(get_settings),  # noqa: B008
    mailer: Mailer = Depends(get_mailer),  # noqa: B008
    x_widget_token: str = Header(default="", alias="X-Widget-Token"),
    token: str = Query(default=""),
) -> ChatOut:
    widget_token = x_widget_token or token

    tenant = resolve_tenant_by_token(widget_token)

    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Widget-Token")

    client_ip = request.client.host if request.client else "unknown"

    if is_rate_limited(tenant.tenant_id, client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    state = _store.get(tenant.tenant_id, payload.session_id)
    new_state, reply = handle_user_message(state, payload.message)

    # If we just entered SEND, actually send the email once and move to DONE
    if new_state.step == Step.SEND:
        if not new_state.data.summary or new_state.data.status.value != "ready_to_send":
            raise HTTPException(
                status_code=500, detail="Invariant violated: tried to send without ready summary."
            )
        subject = f"{tenant.subject_prefix} {new_state.data.category.value if new_state.data.category else 'inquiry'}"

        mailer.send(tenant.inbox_email, subject, new_state.data.summary)
        new_state.step = Step.DONE
        new_state.data.status = Status.SENT

    _store.set(tenant.tenant_id, payload.session_id, new_state)
    return ChatOut(reply=reply, step=new_state.step.value, is_done=(new_state.step == Step.DONE))


class TenantUpsertIn(BaseModel):
    tenant_id: str
    widget_token: str
    inbox_email: str
    subject_prefix: str = "[Scaffold Web Agent]"
    allowed_origins: list[str]


@router.post("/admin/tenants/upsert")
def admin_upsert_tenant(
    payload: TenantUpsertIn,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    # uses the same ADMIN_TOKEN you already have in Render

    if x_admin_token != (getattr(global_settings, "ADMIN_TOKEN", "") or ""):
        raise HTTPException(status_code=403, detail="Forbidden")

    upsert_tenant(
        Tenant(
            tenant_id=payload.tenant_id.strip(),
            widget_token=payload.widget_token.strip(),
            inbox_email=payload.inbox_email.strip(),
            subject_prefix=payload.subject_prefix.strip(),
            allowed_origins=payload.allowed_origins,
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

    new_token = rotate_widget_token(tenant_id)

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

    revoke_widget_token(tenant_id)

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
        "tenants": list_tenants(),
    }


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
        "sessions": list_sessions_for_tenant(tenant_id, limit),
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

    return tenant_analytics(tenant_id)
