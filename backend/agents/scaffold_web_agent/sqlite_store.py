from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from .domain import Category, SessionState, Status, Step, Urgency


def _db_path() -> Path:
    # same pattern as dental data folder
    return Path(__file__).resolve().parents[2] / "data" / "scaffold.db"


def _table_columns(con: sqlite3.Connection, table_name: str) -> list[str]:
    rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [r[1] for r in rows]


def _connect() -> sqlite3.Connection:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(p))

    # ---------- scaffold_sessions ----------
    session_cols = _table_columns(con, "scaffold_sessions")

    if not session_cols:
        con.execute(
            """
            CREATE TABLE scaffold_sessions (
                tenant_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, session_id)
            )
            """
        )
    elif "tenant_id" not in session_cols:
        con.execute("ALTER TABLE scaffold_sessions RENAME TO scaffold_sessions_old")
        con.execute(
            """
            CREATE TABLE scaffold_sessions (
                tenant_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, session_id)
            )
            """
        )
        con.execute(
            """
            INSERT INTO scaffold_sessions(tenant_id, session_id, state_json, updated_at)
            SELECT 'default', session_id, state_json, updated_at
            FROM scaffold_sessions_old
            """
        )
        con.execute("DROP TABLE scaffold_sessions_old")

    # ---------- scaffold_tenants ----------
    tenant_cols = _table_columns(con, "scaffold_tenants")

    if not tenant_cols:
        con.execute(
            """
            CREATE TABLE scaffold_tenants (
                tenant_id TEXT PRIMARY KEY,
                widget_token TEXT UNIQUE NOT NULL,
                inbox_email TEXT NOT NULL,
                subject_prefix TEXT NOT NULL,
                allowed_origins TEXT NOT NULL,
                agent_type TEXT NOT NULL DEFAULT 'scaffold_web_agent',
                knowledge_text TEXT NOT NULL DEFAULT ''
            )
            """
        )
        tenant_cols = _table_columns(con, "scaffold_tenants")

    if "allowed_origins" not in tenant_cols:
        con.execute(
            "ALTER TABLE scaffold_tenants ADD COLUMN allowed_origins TEXT NOT NULL DEFAULT ''"
        )
        tenant_cols = _table_columns(con, "scaffold_tenants")

    if "agent_type" not in tenant_cols:
        con.execute(
            "ALTER TABLE scaffold_tenants ADD COLUMN agent_type TEXT NOT NULL DEFAULT 'scaffold_web_agent'"
        )
        tenant_cols = _table_columns(con, "scaffold_tenants")

    if "knowledge_text" not in tenant_cols:
        con.execute(
            "ALTER TABLE scaffold_tenants ADD COLUMN knowledge_text TEXT NOT NULL DEFAULT ''"
        )

    # ---------- scaffold_rate_limits ----------
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS scaffold_rate_limits (
            tenant_id TEXT NOT NULL,
            ip TEXT NOT NULL,
            ts INTEGER NOT NULL
        )
        """
    )

    # ---------- scaffold_leads ----------
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS scaffold_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            email TEXT,
            topic TEXT,
            summary TEXT,
            created_at INTEGER NOT NULL
        )
        """
    )

    # ---------- scaffold_events ----------
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS scaffold_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_payload_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )

    con.commit()
    return con


def _serialize(state: SessionState) -> str:
    """
    Convierte un SessionState a JSON para guardarlo en SQLite.
    Los Enums se convierten a su valor string.
    El campo 'messages' (historial LLM) se incluye directamente como lista.
    """
    d = asdict(state)
    # Enums → valores string
    if d["step"]:
        d["step"] = state.step.value
    sd = d["data"]
    sd["status"] = state.data.status.value
    sd["category"] = state.data.category.value if state.data.category else None
    sd["urgency"] = state.data.urgency.value if state.data.urgency else None
    # 'messages' ya es una lista de dicts, asdict() la maneja correctamente
    return json.dumps(d, ensure_ascii=False)


def _deserialize(s: str) -> SessionState:
    """
    Reconstruye un SessionState desde JSON.
    Compatible hacia atrás: sesiones antiguas sin 'messages' reciben lista vacía.
    """
    d = json.loads(s)
    st = SessionState()
    st.step = Step(d.get("step", Step.START.value))

    data = d.get("data", {}) or {}
    st.data.contact_name = data.get("contact_name")
    st.data.company = data.get("company")
    st.data.email = data.get("email")
    st.data.phone = data.get("phone")
    st.data.country = data.get("country")

    cat = data.get("category")
    urg = data.get("urgency")
    st.data.category = Category(cat) if cat else None
    st.data.urgency = Urgency(urg) if urg else None

    st.data.topic = data.get("topic")
    st.data.details = data.get("details")
    st.data.attachments = data.get("attachments") or []

    st.data.summary = data.get("summary")
    st.data.status = Status(data.get("status", Status.COLLECTING.value))

    # Campo nuevo: historial de mensajes para el motor LLM
    # Si no existe en sesiones antiguas, devuelve lista vacía (compatible)
    st.messages = d.get("messages") or []

    return st


class SQLiteSessionStore:
    def get(self, tenant_id: str, session_id: str) -> SessionState:
        with _connect() as con:
            row = con.execute(
                "SELECT state_json FROM scaffold_sessions WHERE tenant_id = ? AND session_id = ?",
                (tenant_id, session_id),
            ).fetchone()
            if not row:
                return SessionState()
            return _deserialize(row[0])

    def set(self, tenant_id: str, session_id: str, state: SessionState) -> None:
        payload = _serialize(state)
        now = int(time.time())
        with _connect() as con:
            con.execute(
                """
                INSERT INTO scaffold_sessions(tenant_id, session_id, state_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id, session_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (tenant_id, session_id, payload, now),
            )
            con.commit()


def list_sessions_for_tenant(tenant_id: str, limit: int = 20):
    with _connect() as con:
        rows = con.execute(
            """
            SELECT session_id, state_json, updated_at
            FROM scaffold_sessions
            WHERE tenant_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (tenant_id, limit),
        ).fetchall()

    result = []
    for r in rows:
        result.append(
            {
                "session_id": r[0],
                "state_json": r[1],
                "updated_at": r[2],
            }
        )

    return result


def tenant_analytics(tenant_id: str) -> dict:
    with _connect() as con:
        rows = con.execute(
            """
            SELECT state_json
            FROM scaffold_sessions
            WHERE tenant_id = ?
            """,
            (tenant_id,),
        ).fetchall()

    total_sessions = 0
    done_sessions = 0
    confirm_sessions = 0
    sessions_with_email = 0

    for row in rows:
        total_sessions += 1
        raw = row[0]
        try:
            data = json.loads(raw)
        except Exception:
            continue

        step = data.get("step")
        payload = data.get("data", {}) or {}

        if step == "done":
            done_sessions += 1

        if step == "confirm":
            confirm_sessions += 1

        if payload.get("email"):
            sessions_with_email += 1

    return {
        "tenant_id": tenant_id,
        "total_sessions": total_sessions,
        "done_sessions": done_sessions,
        "confirm_sessions": confirm_sessions,
        "sessions_with_email": sessions_with_email,
    }


def insert_lead(
    tenant_id: str,
    session_id: str,
    email: str | None,
    topic: str | None,
    summary: str | None,
) -> None:
    now = int(time.time())

    with _connect() as con:
        con.execute(
            """
            INSERT INTO scaffold_leads(tenant_id, session_id, email, topic, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tenant_id, session_id, email, topic, summary, now),
        )
        con.commit()


def list_leads_for_tenant(tenant_id: str, limit: int = 50):
    with _connect() as con:
        rows = con.execute(
            """
            SELECT id, tenant_id, session_id, email, topic, summary, created_at
            FROM scaffold_leads
            WHERE tenant_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (tenant_id, limit),
        ).fetchall()

    result = []
    for r in rows:
        result.append(
            {
                "id": r[0],
                "tenant_id": r[1],
                "session_id": r[2],
                "email": r[3],
                "topic": r[4],
                "summary": r[5],
                "created_at": r[6],
            }
        )

    return result


def insert_event(
    tenant_id: str,
    session_id: str,
    event_type: str,
    event_payload: dict | None,
) -> None:
    now = int(time.time())
    payload_json = json.dumps(event_payload or {}, ensure_ascii=False)

    with _connect() as con:
        con.execute(
            """
            INSERT INTO scaffold_events(tenant_id, session_id, event_type, event_payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tenant_id, session_id, event_type, payload_json, now),
        )
        con.commit()


def list_events_for_tenant(tenant_id: str, limit: int = 100) -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            """
            SELECT id, tenant_id, session_id, event_type, event_payload_json, created_at
            FROM scaffold_events
            WHERE tenant_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (tenant_id, limit),
        ).fetchall()

    result = []
    for r in rows:
        result.append(
            {
                "id": r[0],
                "tenant_id": r[1],
                "session_id": r[2],
                "event_type": r[3],
                "event_payload_json": r[4],
                "created_at": r[5],
            }
        )

    return result
