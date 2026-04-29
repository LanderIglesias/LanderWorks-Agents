"""
engine.py — Orquestador del Document Intelligence Agent.

Cambios:
- answer_question() devuelve chunks_text con el texto exacto de cada chunk usado
- Nueva función compare_documents() que lanza la misma pregunta contra todos
  los documentos indexados y devuelve una respuesta por documento
"""

from __future__ import annotations

import logging
import os

import anthropic
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from .database import (
    delete_document,
    get_all_documents,
    save_chunks,
    search_similar_chunks,
)
from .document_processor import process_pdf
from .storage import delete_pdf, get_presigned_url, upload_pdf

load_dotenv(override=False)
logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

SYSTEM_PROMPT = """You are a document intelligence assistant. You answer questions based exclusively on the provided document chunks.

RULES:
1. Answer ONLY based on the provided context chunks. Never use outside knowledge.
2. If the answer is not in the chunks, say "I couldn't find information about that in this document."
3. Always cite which document and page number the information comes from.
4. Be concise and direct. Lead with the answer, then add context if needed.
5. If multiple chunks contain relevant information, synthesize them into a single answer.
6. Respond in the same language as the question.
"""


# ── Indexar documento ────────────────────────────────────────────────────────


def index_document(db: Session, pdf_bytes: bytes, filename: str) -> dict:
    """Sube a R2, procesa chunks + embeddings, guarda en PostgreSQL."""
    logger.info(f"[Engine] Indexing: {filename}")

    r2_key = upload_pdf(pdf_bytes, filename)

    try:
        chunks = process_pdf(pdf_bytes)
    except Exception:
        try:
            delete_pdf(r2_key)
        except Exception:
            pass
        raise

    chunk_count = save_chunks(db, filename, chunks, r2_key=r2_key)
    pages = list({c["page_number"] for c in chunks if c.get("page_number")})

    return {
        "filename": filename,
        "r2_key": r2_key,
        "chunk_count": chunk_count,
        "pages_processed": len(pages),
    }


# ── Responder pregunta ───────────────────────────────────────────────────────


def answer_question(
    db: Session,
    question: str,
    filename: str | None = None,
    top_k: int = 5,
) -> dict:
    """
    Responde una pregunta buscando en los documentos indexados.
    Devuelve la respuesta, las fuentes y el texto exacto de los chunks usados.
    """
    query_embedding = _embed(question)

    similar_chunks = search_similar_chunks(
        db=db,
        query_embedding=query_embedding,
        filename=filename,
        limit=top_k,
    )

    if not similar_chunks:
        return {
            "answer": "No documents are indexed yet. Please upload a document first.",
            "sources": [],
            "chunks_used": 0,
            "chunks_text": [],
        }

    context_parts = []
    sources = []
    chunks_text = []  # texto exacto de cada chunk para mostrarlo en la UI

    for chunk in similar_chunks:
        context_parts.append(
            f"[Document: {chunk.filename} | Page: {chunk.page_number}]\n{chunk.content}"
        )
        source = {"filename": chunk.filename, "page": chunk.page_number}
        if source not in sources:
            sources.append(source)

        # Guardamos el texto del chunk con su metadata
        chunks_text.append(
            {
                "filename": chunk.filename,
                "page": chunk.page_number,
                "content": chunk.content,
            }
        )

    context = "\n\n---\n\n".join(context_parts)
    answer = _call_claude(question, context)

    return {
        "answer": answer,
        "sources": sources,
        "chunks_used": len(similar_chunks),
        "chunks_text": chunks_text,
    }


# ── Compare mode — misma pregunta contra todos los documentos ────────────────


def compare_documents(
    db: Session,
    question: str,
    top_k: int = 3,
) -> list[dict]:
    """
    Lanza la misma pregunta contra cada documento indexado por separado.
    Devuelve una lista de resultados, uno por documento.

    Cada resultado tiene:
    - filename: nombre del documento
    - answer: respuesta específica para ese documento
    - sources: páginas usadas
    - chunks_text: chunks exactos usados
    - chunks_used: número de chunks recuperados

    Si un documento no tiene información relevante, Claude lo indica
    con "I couldn't find information about that in this document."
    """
    documents = get_all_documents(db)

    if not documents:
        return []

    query_embedding = _embed(question)
    results = []

    for doc in documents:
        filename = doc["filename"]

        # Buscar chunks de este documento específico
        similar_chunks = search_similar_chunks(
            db=db,
            query_embedding=query_embedding,
            filename=filename,
            limit=top_k,
        )

        if not similar_chunks:
            results.append(
                {
                    "filename": filename,
                    "answer": "No relevant content found in this document.",
                    "sources": [],
                    "chunks_used": 0,
                    "chunks_text": [],
                }
            )
            continue

        context_parts = []
        sources = []
        chunks_text = []

        for chunk in similar_chunks:
            context_parts.append(
                f"[Document: {chunk.filename} | Page: {chunk.page_number}]\n{chunk.content}"
            )
            source = {"filename": chunk.filename, "page": chunk.page_number}
            if source not in sources:
                sources.append(source)
            chunks_text.append(
                {
                    "filename": chunk.filename,
                    "page": chunk.page_number,
                    "content": chunk.content,
                }
            )

        context = "\n\n---\n\n".join(context_parts)
        answer = _call_claude(question, context)

        results.append(
            {
                "filename": filename,
                "answer": answer,
                "sources": sources,
                "chunks_used": len(similar_chunks),
                "chunks_text": chunks_text,
            }
        )

    return results


# ── Gestión de documentos ────────────────────────────────────────────────────


def list_documents(db: Session) -> list[dict]:
    return get_all_documents(db)


def remove_document(db: Session, filename: str) -> dict:
    docs = get_all_documents(db)
    doc = next((d for d in docs if d["filename"] == filename), None)

    if not doc:
        raise FileNotFoundError(f"Document not found: {filename}")

    deleted_chunks = delete_document(db, filename)

    if doc.get("r2_key"):
        try:
            delete_pdf(doc["r2_key"])
        except Exception as e:
            logger.warning(f"[Engine] Could not delete from R2: {e}")

    return {"filename": filename, "chunks_deleted": deleted_chunks}


def get_document_url(db: Session, filename: str) -> str:
    docs = get_all_documents(db)
    doc = next((d for d in docs if d["filename"] == filename), None)

    if not doc or not doc.get("r2_key"):
        raise FileNotFoundError(f"Document not found or no R2 key: {filename}")

    return get_presigned_url(doc["r2_key"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _embed(text: str) -> list[float]:
    """Genera embedding de un texto con OpenAI."""
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding


def _call_claude(question: str, context: str) -> str:
    """Llama a Claude con el contexto de chunks y devuelve la respuesta."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    user_message = f"""Context from indexed documents:

{context}

---

Question: {question}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text.strip()
