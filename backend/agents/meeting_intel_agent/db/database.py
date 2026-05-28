"""
database.py — Conexión a PostgreSQL y definición de tablas

Tablas:
- meetings           → metadatos de cada reunión analizada
- meeting_extractions → decisions, action items, questions, topics (JSON)
- meeting_chunks     → chunks de transcripción + vectores pgvector para RAG

Usa SQLAlchemy Core (no ORM) para mantener las queries simples y legibles.
La extensión pgvector se activa al crear las tablas si no existe ya.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

load_dotenv(override=False)

# ── Conexión ──────────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("MEETING_DATABASE_URL")

# NullPool: no reutilizamos conexiones entre peticiones
# Más seguro en entornos con múltiples workers
engine = create_engine(DATABASE_URL, poolclass=NullPool)


@contextmanager
def get_connection():
    """
    Context manager que abre y cierra la conexión automáticamente.

    Uso:
        with get_connection() as conn:
            conn.execute(text("SELECT 1"))

    Si algo falla dentro del bloque, el rollback es automático.
    """
    with engine.connect() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# ── Creación de tablas ────────────────────────────────────────────────────────


def create_tables() -> None:
    """
    Crea todas las tablas necesarias si no existen.
    Se llama al arrancar la aplicación.

    También activa la extensión pgvector y uuid-ossp si no están activas.
    """
    with get_connection() as conn:

        # Activamos pgvector para almacenar vectores de embeddings
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        # Activamos uuid-ossp para generar UUIDs únicos automáticamente
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))

        # ── Tabla 1: meetings ─────────────────────────────────────────────────
        # Guarda los metadatos de cada reunión analizada
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS meetings (
                id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                title           TEXT NOT NULL,
                language        TEXT NOT NULL DEFAULT 'es',
                duration_seconds FLOAT,
                created_at      TIMESTAMP DEFAULT NOW(),
                transcription   TEXT,           -- texto completo de la reunión
                executive_summary TEXT,         -- resumen ejecutivo generado por Claude
                key_topics      JSONB           -- lista de temas principales
            )
        """
            )
        )

        # ── Tabla 2: meeting_extractions ──────────────────────────────────────
        # Guarda las extracciones estructuradas de cada reunión
        # Usamos JSONB para cada categoría — flexible y consultable con SQL
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS meeting_extractions (
                id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                meeting_id      UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                decisions       JSONB DEFAULT '[]',     -- decisiones tomadas
                action_items    JSONB DEFAULT '[]',     -- tareas asignadas
                open_questions  JSONB DEFAULT '[]',     -- preguntas sin responder
                pending_topics  JSONB DEFAULT '[]',     -- temas pendientes
                created_at      TIMESTAMP DEFAULT NOW()
            )
        """
            )
        )

        # ── Tabla 3: meeting_chunks ───────────────────────────────────────────
        # Guarda los chunks de transcripción con sus vectores para RAG
        # El vector(1536) es para OpenAI text-embedding-3-small
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS meeting_chunks (
                id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                meeting_id      UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                chunk_index     INTEGER NOT NULL,       -- posición del chunk en la transcripción
                content         TEXT NOT NULL,          -- texto del chunk
                embedding       vector(1536),           -- vector de embeddings (pgvector)
                created_at      TIMESTAMP DEFAULT NOW()
            )
        """
            )
        )

        # Índice para búsqueda por similitud coseno (ivfflat)
        # ivfflat es más rápido que el índice exacto para datasets grandes
        # lists=100 es el número de centroides — ajustar según el volumen de datos
        conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS meeting_chunks_embedding_idx
            ON meeting_chunks
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """
            )
        )

        # Índice para filtrar chunks por meeting_id rápidamente
        conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS meeting_chunks_meeting_id_idx
            ON meeting_chunks (meeting_id)
        """
            )
        )

    print("[DB] Tablas creadas correctamente")
