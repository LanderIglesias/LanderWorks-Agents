from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from unidecode import unidecode

DB_PATH = Path(__file__).resolve().parent / "data" / "leads.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Debe ser MAYOR que el TTL máximo de negocio (idle/handoff = 12h),
# o cleanup_sessions borrará sesiones antes de que respond() pueda resetearlas “bien”.
SESSION_TTL_MINUTES = 24 * 60  # 24h

_DEDUPE_WINDOW_SECONDS = 10 * 60  # 10 minutos


@dataclass
class LeadState:
    step: str = "idle"
    nombre: str | None = None
    telefono: str | None = None
    tratamiento: str | None = None
    urgencia: str | None = None
    preferencia: str | None = None

    # FAQ memory (DEDUP)
    last_faq_sig: str | None = None
    last_faq_sources: list[str] = field(default_factory=list)
    last_faq_at: str | None = None  # ISO string UTC

    last_neutral_step: str | None = None
    neutral_hits: int = 0

    faq_interrupts: int = 0
    phone_refusals: int = 0
    step_retries: int = 0

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))

    status: str = "active"


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _json_safe(x):
    # datetime -> iso
    if isinstance(x, datetime):
        return x.isoformat(timespec="seconds")
    # dict -> recurse
    if isinstance(x, dict):
        return {k: _json_safe(v) for k, v in x.items()}
    # list/tuple -> recurse
    if isinstance(x, list | tuple):
        return [_json_safe(v) for v in x]
    return x


def _state_to_json(st: LeadState) -> str:
    d = asdict(st)
    d = _json_safe(d)
    return json.dumps(d, ensure_ascii=False)


def _json_to_state(s: str) -> LeadState:
    st = LeadState()
    try:
        d = json.loads(s)
        for k, v in d.items():
            if not hasattr(st, k):
                continue
            if k in ("created_at", "last_seen") and isinstance(v, str):
                dtv = _parse_dt(v)
                if dtv:
                    setattr(st, k, dtv)
                continue
            setattr(st, k, v)
    except Exception:
        pass
    return st


def _table_cols(conn: sqlite3.Connection, table: str) -> dict[str, dict[str, Any]]:
    """
    Devuelve dict: {col_name: {"type": ..., "notnull": 0/1, "dflt": ..., "pk": 0/1}}
    """
    cur = conn.execute(f"PRAGMA table_info({table})")
    out: dict[str, dict[str, Any]] = {}
    for row in cur.fetchall():
        # row: (cid, name, type, notnull, dflt_value, pk)
        out[row[1]] = {"type": row[2], "notnull": row[3], "dflt": row[4], "pk": row[5]}
    return out


def _ensure_sessions_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            sender TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """
    )
    # Migración defensiva: si por lo que sea existe sessions sin state_json, la recreamos
    try:
        cols = _table_cols(conn, "sessions")
        if "state_json" not in cols:
            conn.execute("DROP TABLE IF EXISTS sessions")
            conn.execute(
                """
                CREATE TABLE sessions (
                    sender TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """
            )
    except Exception:
        conn.execute("DROP TABLE IF EXISTS sessions")
        conn.execute(
            """
            CREATE TABLE sessions (
                sender TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """
        )
    conn.commit()


def _ensure_handoffs_table(conn: sqlite3.Connection) -> None:
    """
    Esquema CANÓNICO:
      - message: NOT NULL (para sobrevivir a DBs viejas donde era obligatorio)
      - summary: opcional
      - status: default 'open'
      - meta_json: default '{}'
    Migra desde tablas previas que tengan:
      - solo summary
      - solo message
      - message NOT NULL sin summary
      - sin meta_json / sin status
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS handoffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            message TEXT NOT NULL DEFAULT '',
            summary TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    conn.commit()

    cols = _table_cols(conn, "handoffs")

    # 1) Asegurar columnas base (ALTER TABLE solo puede añadir con DEFAULT si quieres NOT NULL)
    if "message" not in cols:
        conn.execute("ALTER TABLE handoffs ADD COLUMN message TEXT NOT NULL DEFAULT ''")
    if "summary" not in cols:
        conn.execute("ALTER TABLE handoffs ADD COLUMN summary TEXT")
    if "status" not in cols:
        conn.execute("ALTER TABLE handoffs ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
    if "meta_json" not in cols:
        conn.execute("ALTER TABLE handoffs ADD COLUMN meta_json TEXT NOT NULL DEFAULT '{}'")

    conn.commit()

    # 2) Backfill para coherencia (evita NOT NULL constraint y asegura contenido)
    cols = _table_cols(conn, "handoffs")
    has_message = "message" in cols
    has_summary = "summary" in cols

    if has_message and has_summary:
        # Si summary está vacío y message tiene algo, copiar
        conn.execute(
            """
            UPDATE handoffs
            SET summary = COALESCE(NULLIF(summary, ''), message)
            WHERE (summary IS NULL OR summary = '') AND (message IS NOT NULL AND message != '')
        """
        )
        # Si message está vacío y summary tiene algo, copiar
        conn.execute(
            """
            UPDATE handoffs
            SET message = COALESCE(NULLIF(message, ''), summary, '')
            WHERE (message IS NULL OR message = '') AND (summary IS NOT NULL AND summary != '')
        """
        )
    conn.commit()

    # 3) Normalizar meta_json nulo
    conn.execute(
        """
        UPDATE handoffs
        SET meta_json = '{}'
        WHERE meta_json IS NULL OR meta_json = ''
    """
    )
    conn.commit()

    # 4) Normalizar status nulo
    conn.execute(
        """
        UPDATE handoffs
        SET status = 'open'
        WHERE status IS NULL OR status = ''
    """
    )
    conn.commit()


def _ensure_leads_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            telefono TEXT,
            tratamiento TEXT,
            urgencia TEXT,
            canal TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    conn.commit()


def _ensure_processed_messages_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_messages (
            sid TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def get_conn() -> sqlite3.Connection:
    # Si algún día migras a Postgres con psycopg, esto cambiará de librería.
    # PERO: hoy no vamos a reescribir todo. Hoy vamos a DESPLEGAR.
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    _ensure_leads_table(conn)
    _ensure_sessions_table(conn)
    _ensure_handoffs_table(conn)
    _ensure_processed_messages_table(conn)
    return conn


def get_state(sender: str) -> LeadState:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT state_json FROM sessions WHERE sender = ?", (sender,))
    row = cur.fetchone()

    if row and row["state_json"]:
        return _json_to_state(row["state_json"])
    return LeadState()


def save_state(sender: str, st: LeadState) -> None:
    conn = get_conn()
    cur = conn.cursor()

    # Si last_seen viene vacío, lo ponemos (pero NO lo machacamos siempre)
    if not getattr(st, "last_seen", None):
        st.last_seen = datetime.now(UTC)

    payload = _state_to_json(st)
    updated_at = st.last_seen.isoformat(timespec="seconds")

    cur.execute(
        """
        INSERT INTO sessions (sender, state_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(sender) DO UPDATE SET
            state_json = excluded.state_json,
            updated_at = excluded.updated_at
        """,
        (sender, payload, updated_at),
    )
    conn.commit()


def touch_state(sender: str, when: datetime | None = None) -> LeadState:
    st = get_state(sender)
    st.last_seen = when or datetime.now(UTC)
    save_state(sender, st)
    return st


def reset_state(sender: str):
    st = LeadState()  # estado NUEVO limpio
    st.step = "idle"
    st.status = ""
    st.last_seen = datetime.now(UTC)
    save_state(sender, st)


def cleanup_sessions() -> None:
    conn = get_conn()
    cutoff = datetime.now(UTC) - timedelta(minutes=SESSION_TTL_MINUTES)
    cutoff_iso = cutoff.isoformat(timespec="seconds")
    conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff_iso,))
    conn.commit()


def save_lead(nombre: str, telefono: str, tratamiento: str, urgencia: str, canal: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO leads (nombre, telefono, tratamiento, urgencia, canal)
           VALUES (?, ?, ?, ?, ?)""",
        (nombre, telefono, tratamiento, urgencia, canal),
    )
    conn.commit()
    return str(cur.lastrowid)


def _norm_for_dedupe(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = s.replace("\r", "\n")
    s = unidecode(s.lower())
    s = re.sub(r"\b(la|el|un|una|por|para|de|del|al|y)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[^\w\s]", "", s)
    return s


def _is_low_signal_message(s: str) -> bool:
    raw = (s or "").strip()
    n = _norm_for_dedupe(raw)
    if not n:
        return True

    # Si contiene dígitos (teléfono/hora/cantidad), normalmente aporta
    if re.search(r"\d", raw):
        return False

    # Si parece pregunta, aporta (aunque sea corta)
    if "?" in raw or "¿" in raw:
        return False

    # Palabras que suelen aportar (urgencia, síntomas, preferencias)
    informative_tokens = [
        "mañana",
        "manana",
        "tarde",
        "hoy",
        "lunes",
        "martes",
        "miercoles",
        "miércoles",
        "jueves",
        "viernes",
        "sabado",
        "sábado",
        "domingo",
        "urgente",
        "dolor",
        "sangrado",
        "hinchazon",
        "hinchazón",
        "flemon",
        "flemón",
        "inflamacion",
        "inflamación",
        "fiebre",
        "adeslas",
        "seguro",
        "mutua",
    ]
    if any(tok in n for tok in informative_tokens):
        return False

    # Confirmaciones típicas que no aportan nada
    low = {
        "ok",
        "vale",
        "perfecto",
        "genial",
        "bien",
        "de acuerdo",
        "gracias",
        "ok gracias",
        "vale gracias",
        "perfecto gracias",
        "okey",
        "listo",
        "hecho",
        "entendido",
    }
    if n in low:
        return True

    # Muy corto y sin señales informativas => ruido probable
    if len(n) < 4:
        return True

    return False


def enqueue_handoff(
    sender: str, message: str, summary: str | None = None, meta: dict | None = None
):
    """
    Inserta un handoff en DB con deduplicación.
    - Dedupe por último mensaje del mismo sender (contenido normalizado)
    - Ventana temporal: evita repetir lo mismo en X minutos
    - Si es ruido obvio, no insertes
    """
    import sqlite3

    from .config import settings  # si ahí tienes DB path

    if meta is None:
        meta = {}

    meta.setdefault("kind", "unknown")

    # Safety net: si es ruido, fuera (especialmente importante en modo handoff)
    if _is_low_signal_message(message) and meta.get("kind", "").startswith("followup"):
        return None

    msg_norm = _norm_for_dedupe(message)
    sum_norm = _norm_for_dedupe(summary or "")

    # Si no hay summary, por defecto usa message para el campo summary (opcional)
    if summary is None:
        summary = message

    now = datetime.now(UTC)

    conn = sqlite3.connect(settings.DB_PATH)
    try:
        cur = conn.cursor()

        # 1) Trae el último handoff del sender
        cur.execute(
            """
            SELECT id, message, summary, meta_json, created_at
            FROM handoffs
            WHERE sender = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (sender,),
        )
        row = cur.fetchone()

        if row:
            last_id, last_msg, last_sum, last_meta_json, last_created = row

            last_msg_norm = _norm_for_dedupe(last_msg or "")
            last_sum_norm = _norm_for_dedupe(last_sum or "")

            # Parse created_at (si lo guardas como "YYYY-MM-DD HH:MM:SS")
            last_dt = None
            try:
                # soporta formato típico sqlite
                last_dt = datetime.fromisoformat(str(last_created).replace(" ", "T"))
                # si viene naive, lo tratamos como UTC
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
            except Exception:
                last_dt = None

            # Parse meta kind
            last_kind = ""
            try:
                lm = json.loads(last_meta_json) if last_meta_json else {}
                last_kind = (lm.get("kind") or "").strip()
            except Exception:
                last_kind = ""

            this_kind = (meta.get("kind") or "").strip()

            # Dedupe duro: mismo mensaje + mismo kind
            if msg_norm and msg_norm == last_msg_norm and this_kind == last_kind:
                return None

            # Dedupe duro: mismo summary + mismo kind
            if sum_norm and sum_norm == last_sum_norm and this_kind == last_kind:
                return None

            # 3) Dedupe por ventana: mismo contenido dentro de X minutos
            if last_dt and (now - last_dt).total_seconds() <= _DEDUPE_WINDOW_SECONDS:
                if (
                    (msg_norm and msg_norm == last_msg_norm)
                    or (sum_norm and sum_norm == last_sum_norm)
                ) and this_kind == last_kind:
                    return None

        # 4) Insert
        meta_json = json.dumps(meta, ensure_ascii=False, default=str)
        created_at = now.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")

        cur.execute(
            """
            INSERT INTO handoffs (sender, message, summary, status, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sender, message, summary, "open", meta_json, created_at),
        )
        conn.commit()

        return cur.lastrowid

    finally:
        conn.close()


def list_handoffs(limit: int = 20, status: str = "open") -> list[dict[str, Any]]:
    conn = get_conn()
    _ensure_handoffs_table(conn)

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, sender, message, summary, status, meta_json, created_at
        FROM handoffs
        WHERE status = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (status, limit),
    )
    rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except Exception:
            meta = {}
        out.append(
            {
                "id": r["id"],
                "sender": r["sender"],
                "message": r["message"],
                "summary": r["summary"],
                "status": r["status"],
                "meta": meta,
                "created_at": r["created_at"],
            }
        )
    return out


def close_handoff(handoff_id: int) -> bool:
    conn = get_conn()
    _ensure_handoffs_table(conn)

    cur = conn.cursor()
    cur.execute("UPDATE handoffs SET status='closed' WHERE id = ?", (handoff_id,))
    conn.commit()
    return cur.rowcount > 0


def mark_message_processed(message_sid: str) -> bool:
    """
    Devuelve True si este MessageSid es nuevo.
    False si ya lo vimos (dedupe).
    """
    sid = (message_sid or "").strip()
    if not sid:
        return True

    now = datetime.now(UTC).isoformat(timespec="seconds")

    conn = get_conn()  # <-- usa tu función real de conexión
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO processed_messages (sid, created_at) VALUES (?, ?)",
        (sid, now),
    )
    conn.commit()
    return cur.rowcount == 1
