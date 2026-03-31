from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from .sqlite_store import _connect


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    widget_token: str
    inbox_email: str
    subject_prefix: str = "[Web Lead Agent]"
    allowed_origins: list[str] = field(default_factory=list)
    agent_type: str = "scaffold_web_agent"
    knowledge_text: str = ""


def ensure_tenants_table() -> None:
    with _connect():
        pass


def resolve_tenant_by_token(widget_token: str) -> Tenant | None:
    widget_token = (widget_token or "").strip()
    if not widget_token:
        return None

    ensure_tenants_table()

    with _connect() as con:
        row = con.execute(
            """
            SELECT tenant_id, widget_token, inbox_email, subject_prefix, allowed_origins, agent_type, knowledge_text
            FROM scaffold_tenants
            WHERE widget_token = ?
            """,
            (widget_token,),
        ).fetchone()

    if not row:
        return None

    allowed = [x.strip() for x in (row[4] or "").split(",") if x.strip()]
    return Tenant(
        tenant_id=row[0],
        widget_token=row[1],
        inbox_email=row[2],
        subject_prefix=row[3],
        allowed_origins=allowed,
        agent_type=row[5] or "scaffold_web_agent",
        knowledge_text=row[6] or "",
    )


def upsert_tenant(tenant: Tenant) -> None:
    ensure_tenants_table()
    allowed_csv = ",".join(tenant.allowed_origins or [])
    with _connect() as con:
        con.execute(
            """
            INSERT INTO scaffold_tenants(
                tenant_id,
                widget_token,
                inbox_email,
                subject_prefix,
                allowed_origins,
                agent_type,
                knowledge_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id) DO UPDATE SET
                widget_token=excluded.widget_token,
                inbox_email=excluded.inbox_email,
                subject_prefix=excluded.subject_prefix,
                allowed_origins=excluded.allowed_origins,
                agent_type=excluded.agent_type,
                knowledge_text=excluded.knowledge_text
            """,
            (
                tenant.tenant_id,
                tenant.widget_token,
                tenant.inbox_email,
                tenant.subject_prefix,
                allowed_csv,
                tenant.agent_type,
                tenant.knowledge_text,
            ),
        )
    con.commit()


def rotate_widget_token(tenant_id: str) -> str:
    new_token = "tok_" + secrets.token_urlsafe(24)

    with _connect() as con:
        con.execute(
            """
            UPDATE scaffold_tenants
            SET widget_token = ?
            WHERE tenant_id = ?
            """,
            (new_token, tenant_id),
        )
        con.commit()

    return new_token


def revoke_widget_token(tenant_id: str) -> None:
    with _connect() as con:
        con.execute(
            """
            UPDATE scaffold_tenants
            SET widget_token = ''
            WHERE tenant_id = ?
            """,
            (tenant_id,),
        )
        con.commit()


def list_tenants() -> list[dict]:
    ensure_tenants_table()

    with _connect() as con:
        rows = con.execute(
            """
            SELECT tenant_id, widget_token, inbox_email, subject_prefix, allowed_origins, agent_type, knowledge_text
            FROM scaffold_tenants
            ORDER BY tenant_id
            """
        ).fetchall()

    result = []
    for r in rows:
        result.append(
            {
                "tenant_id": r[0],
                "widget_token": r[1],
                "token_active": bool(r[1]),
                "inbox_email": r[2],
                "subject_prefix": r[3],
                "allowed_origins": [x for x in (r[4] or "").split(",") if x],
                "agent_type": r[5] or "scaffold_web_agent",
                "knowledge_text": r[6] or "",
            }
        )

    return result
