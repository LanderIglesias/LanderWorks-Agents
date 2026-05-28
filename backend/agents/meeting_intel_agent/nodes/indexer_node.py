"""
indexer_node.py — Nodo 4 del Meeting Intelligence Agent

Responsabilidad: guardar la reunión y sus chunks en PostgreSQL.

Hace dos cosas:
1. Guarda los metadatos de la reunión y las extracciones en PostgreSQL
2. Convierte cada segmento en vector con OpenAI y lo guarda con pgvector

Después de este nodo el usuario puede hacer preguntas sobre la reunión
usando búsqueda semántica sobre los chunks indexados.
"""

from __future__ import annotations

import json
import os
import uuid

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import text

from ..db.database import get_connection
from ..state import MeetingState

load_dotenv(override=False)

EMBEDDING_MODEL = "text-embedding-3-small"
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def indexer_node(state: MeetingState) -> dict:
    """
    Nodo 4: guarda la reunión y sus chunks en PostgreSQL + pgvector.

    Returns:
        dict con:
        - meeting_id: UUID de la reunión guardada
        - chunks_indexed: número de chunks indexados
    """
    print("[IndexerNode] Iniciando...")

    if state.get("error"):
        return {}

    segments = state.get("segments")
    if not segments:
        return {"error": "No segments to index"}

    meeting_id = str(uuid.uuid4())

    try:
        with get_connection() as conn:

            # ── 1. Guardar metadatos de la reunión ────────────────────────────
            conn.execute(
                text(
                    """
                INSERT INTO meetings (
                    id, title, language, duration_seconds, transcription
                ) VALUES (
                    :id, :title, :language, :duration, :transcription
                )
            """
                ),
                {
                    "id": meeting_id,
                    "title": state.get("meeting_title", "Untitled Meeting"),
                    "language": state.get("transcription_language", "es"),
                    "duration": state.get("audio_duration_seconds"),
                    "transcription": state.get("transcription"),
                },
            )

            # ── 2. Guardar extracciones estructuradas ─────────────────────────
            conn.execute(
                text(
                    """
                INSERT INTO meeting_extractions (
                    meeting_id, decisions, action_items,
                    open_questions, pending_topics
                ) VALUES (
                    :meeting_id, :decisions, :action_items,
                    :open_questions, :pending_topics
                )
            """
                ),
                {
                    "meeting_id": meeting_id,
                    "decisions": json.dumps(state.get("decisions", [])),
                    "action_items": json.dumps(state.get("action_items", [])),
                    "open_questions": json.dumps(state.get("open_questions", [])),
                    "pending_topics": json.dumps(state.get("pending_topics", [])),
                },
            )

            # ── 3. Indexar chunks con embeddings ──────────────────────────────
            chunks_indexed = 0
            for segment in segments:
                # Generamos el embedding del chunk con OpenAI
                embedding = _get_embedding(segment["text"])

                # Guardamos chunk + vector en PostgreSQL
                conn.execute(
                    text(
                        """
                    INSERT INTO meeting_chunks (
                        meeting_id, chunk_index, content, embedding
                    ) VALUES (
                        :meeting_id, :chunk_index, :content, :embedding
                    )
                """
                    ),
                    {
                        "meeting_id": meeting_id,
                        "chunk_index": segment["index"],
                        "content": segment["text"],
                        # pgvector espera el vector como string "[n1, n2, ...]"
                        "embedding": str(embedding),
                    },
                )
                chunks_indexed += 1

        print(
            f"[IndexerNode] Reunión {meeting_id} guardada. " f"{chunks_indexed} chunks indexados."
        )

        return {
            "meeting_id": meeting_id,
            "chunks_indexed": chunks_indexed,
        }

    except Exception as e:
        return {"error": f"Failed to index meeting: {e}"}


def _get_embedding(text_content: str) -> list[float]:
    """
    Genera el vector de embeddings para un texto usando OpenAI.
    Devuelve una lista de 1536 floats.
    """
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text_content,
    )
    return response.data[0].embedding


def search_meeting(meeting_id: str, query: str, top_k: int = 5) -> list[dict]:
    """
    Busca los chunks más relevantes de una reunión para una pregunta.
    Usa búsqueda semántica con cosine similarity via pgvector.

    Args:
        meeting_id: UUID de la reunión
        query: pregunta del usuario
        top_k: número de chunks a devolver

    Returns:
        lista de chunks ordenados por relevancia
    """
    # Convertimos la pregunta a vector
    query_embedding = _get_embedding(query)

    with get_connection() as conn:
        result = conn.execute(
            text(
                """
            SELECT
                content,
                chunk_index,
                1 - (embedding <=> :query_embedding) AS similarity
            FROM meeting_chunks
            WHERE meeting_id = :meeting_id
            ORDER BY embedding <=> :query_embedding
            LIMIT :top_k
        """
            ),
            {
                "meeting_id": meeting_id,
                "query_embedding": str(query_embedding),
                "top_k": top_k,
            },
        )

        return [
            {
                "content": row[0],
                "chunk_index": row[1],
                "similarity": round(float(row[2]), 3),
            }
            for row in result.fetchall()
        ]
