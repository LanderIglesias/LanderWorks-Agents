"""
state.py — Estado compartido del Meeting Intelligence Agent

El estado fluye por todos los nodos del grafo LangGraph.
Cada nodo lee lo que necesita y escribe sus resultados.
LangGraph hace el merge automáticamente entre nodos.

TypedDict en vez de clase normal porque LangGraph trata
el estado como un diccionario — el merge entre nodos
funciona con dicts, no con objetos de clase.
"""

from __future__ import annotations

from typing import TypedDict


class MeetingState(TypedDict):
    # ── Input del usuario ─────────────────────────────────────────────────────
    audio_path: str | None  # ruta al archivo de audio (MP3, WAV, etc.)
    raw_text: str | None  # texto directo si el usuario no sube audio
    meeting_title: str  # título de la reunión (opcional, tiene default)
    language: str  # idioma del audio ("es", "en", "auto")

    # ── Nodo 1 — Transcriber ──────────────────────────────────────────────────
    transcription: str | None  # texto completo de la reunión
    transcription_language: str | None  # idioma detectado por faster-whisper
    audio_duration_seconds: float | None  # duración del audio en segundos

    # ── Nodo 2 — Segmenter ────────────────────────────────────────────────────
    segments: list[dict] | None  # lista de segmentos temáticos
    # Cada segmento: {"title": str, "text": str, "start_idx": int, "end_idx": int}

    # ── Nodo 3 — Extractor ────────────────────────────────────────────────────
    decisions: list[dict] | None  # decisiones tomadas en la reunión
    # Cada decisión: {"text": str, "context": str}

    action_items: list[dict] | None  # tareas asignadas
    # Cada action item: {"task": str, "owner": str, "deadline": str, "priority": str}

    open_questions: list[dict] | None  # preguntas sin responder
    # Cada pregunta: {"question": str, "context": str}

    pending_topics: list[dict] | None  # temas que quedaron pendientes
    # Cada tema: {"topic": str, "reason": str}

    # ── Nodo 4 — Indexer ─────────────────────────────────────────────────────
    meeting_id: str | None  # UUID de la reunión en PostgreSQL
    chunks_indexed: int | None  # número de chunks guardados en pgvector

    # ── Nodo 5 — Synthesizer ─────────────────────────────────────────────────
    executive_summary: str | None  # resumen ejecutivo de 3-5 frases
    key_topics: list[str] | None  # temas principales tratados

    # ── Nodo 6 — Report Generator ─────────────────────────────────────────────
    report_markdown: str | None  # informe completo en markdown
    report_json: dict | None  # informe estructurado para el frontend

    # ── Control de errores ────────────────────────────────────────────────────
    error: str | None  # mensaje de error si algo falla
