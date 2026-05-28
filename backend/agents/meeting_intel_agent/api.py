"""
api.py — Endpoints FastAPI del Meeting Intelligence Agent

Endpoints:
- POST /meeting-intel/analyze/stream  → análisis con progreso SSE
- POST /meeting-intel/ask             → pregunta sobre una reunión (RAG)
- GET  /meeting-intel/demo            → sirve la UI
"""

from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from .db.database import create_tables
from .frontend.index import demo_html
from .nodes.extractor_node import extractor_node
from .nodes.indexer_node import indexer_node, search_meeting
from .nodes.report_generator_node import report_generator_node
from .nodes.segmenter_node import segmenter_node
from .nodes.synthesizer_node import synthesizer_node
from .nodes.transcriber_node import transcriber_node

router = APIRouter(prefix="/meeting-intel", tags=["meeting-intel"])

# Creamos las tablas al cargar el módulo
try:
    create_tables()
except Exception as e:
    print(f"[API] Warning: could not create tables: {e}")


# ── Schemas ───────────────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    meeting_id: str
    question: str
    top_k: int = 5


# ── Endpoint SSE ──────────────────────────────────────────────────────────────


@router.post("/analyze/stream")
async def analyze_stream(
    file: UploadFile | None = File(default=None),  # noqa: B008
    raw_text: str | None = Form(default=None),
    meeting_title: str = Form(default="Untitled Meeting"),
    language: str = Form(default="auto"),
):
    """
    Analiza una reunión enviando progreso en tiempo real via SSE.
    Acepta audio (file) o texto directo (raw_text).
    """

    def event_stream():
        def send(step: str, message: str, progress: int, **kwargs) -> str:
            data = {"step": step, "message": message, "progress": progress, **kwargs}
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        audio_path = None

        try:
            # Guardamos el audio temporalmente si se subió un archivo
            if file and file.filename:
                import shutil
                import tempfile
                from pathlib import Path

                suffix = Path(file.filename).suffix
                tmp = tempfile.NamedTemporaryFile(
                    suffix=suffix, delete=False, prefix="meeting_upload_"
                )
                shutil.copyfileobj(file.file, tmp)
                tmp.close()
                audio_path = tmp.name

            # Estado inicial
            state = {
                "audio_path": audio_path,
                "raw_text": raw_text,
                "meeting_title": meeting_title,
                "language": language,
                "transcription": None,
                "transcription_language": None,
                "audio_duration_seconds": None,
                "segments": None,
                "decisions": None,
                "action_items": None,
                "open_questions": None,
                "pending_topics": None,
                "meeting_id": None,
                "chunks_indexed": None,
                "executive_summary": None,
                "key_topics": None,
                "report_markdown": None,
                "report_json": None,
                "error": None,
            }

            # Nodo 1 — Transcripción
            if audio_path:
                yield send("transcribing", "Transcribing audio with Whisper...", 10)
            else:
                yield send("transcribing", "Processing text input...", 10)
            state.update(transcriber_node(state))
            if state.get("error"):
                yield send("error", state["error"], 0, error=True)
                return
            chars = len(state.get("transcription", ""))
            yield send("transcribed", f"Transcription complete: {chars} characters", 20)

            # Nodo 2 — Segmentación
            yield send("segmenting", "Segmenting transcription into chunks...", 30)
            state.update(segmenter_node(state))
            if state.get("error"):
                yield send("error", state["error"], 0, error=True)
                return
            n_segs = len(state.get("segments", []))
            yield send("segmented", f"Segmented into {n_segs} chunks", 38)

            # Nodo 3 — Extracción
            yield send(
                "extracting",
                f"Claude extracting decisions and action items from {n_segs} segments...",
                45,
            )
            state.update(extractor_node(state))
            if state.get("error"):
                yield send("error", state["error"], 0, error=True)
                return
            n_items = len(state.get("action_items", []))
            n_dec = len(state.get("decisions", []))
            yield send("extracted", f"Extracted: {n_dec} decisions, {n_items} action items", 62)

            # Nodo 4 — Indexación
            yield send("indexing", "Indexing meeting in PostgreSQL + pgvector for RAG...", 70)
            state.update(indexer_node(state))
            if state.get("error"):
                yield send("error", state["error"], 0, error=True)
                return
            yield send("indexed", f"Meeting indexed: {state.get('chunks_indexed', 0)} chunks", 78)

            # Nodo 5 — Síntesis
            yield send("synthesizing", "Claude generating executive summary...", 85)
            state.update(synthesizer_node(state))
            if state.get("error"):
                yield send("error", state["error"], 0, error=True)
                return
            yield send("synthesized", "Executive summary ready", 92)

            # Nodo 6 — Informe
            yield send("generating", "Generating final report...", 96)
            state.update(report_generator_node(state))
            yield send("done", "Analysis complete!", 100, report=state.get("report_json"))

        except Exception as e:
            yield send("error", str(e), 0, error=True)
        finally:
            # Borramos el archivo de audio temporal
            if audio_path:
                import os

                if os.path.exists(audio_path):
                    os.remove(audio_path)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


# ── Endpoint RAG ──────────────────────────────────────────────────────────────


@router.post("/ask")
async def ask_meeting(payload: AskRequest):
    """
    Responde una pregunta sobre una reunión específica usando RAG.
    Busca los chunks más relevantes con pgvector y Claude genera la respuesta.
    """
    import os

    import anthropic

    # Buscamos chunks relevantes con búsqueda semántica
    chunks = search_meeting(
        meeting_id=payload.meeting_id,
        query=payload.question,
        top_k=payload.top_k,
    )

    if not chunks:
        return {"answer": "No relevant content found for this question in the meeting."}

    context = "\n\n---\n\n".join([c["content"] for c in chunks])

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system="You are a meeting assistant. Answer questions based ONLY on the provided meeting transcript context. If the answer is not in the context, say so clearly.",
        messages=[
            {
                "role": "user",
                "content": f"MEETING CONTEXT:\n{context}\n\nQUESTION: {payload.question}",
            }
        ],
    )

    return {
        "answer": response.content[0].text,
        "chunks_used": len(chunks),
        "meeting_id": payload.meeting_id,
    }


# ── Demo UI ───────────────────────────────────────────────────────────────────


@router.get("/demo", response_class=HTMLResponse)
def serve_demo():
    return HTMLResponse(content=demo_html())
