"""api.py — Endpoints FastAPI del Document Intelligence Agent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db
from .demo_template import demo_html
from .engine import (
    answer_question,
    compare_documents,
    get_document_url,
    index_document,
    list_documents,
    remove_document,
)

router = APIRouter(prefix="/doc-intel", tags=["doc-intel"])

MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


# ── Schemas ───────────────────────────────────────────────────────────────────


class DocIntelAskRequest(BaseModel):
    question: str
    filename: str | None = None
    top_k: int = 5


class DocIntelAskResponse(BaseModel):
    answer: str
    sources: list[dict]
    chunks_used: int
    chunks_text: list[dict] = []  # texto exacto de cada chunk usado


class DocIntelUploadResponse(BaseModel):
    filename: str
    r2_key: str
    chunk_count: int
    pages_processed: int
    message: str


class DocIntelCompareRequest(BaseModel):
    question: str
    top_k: int = 3


class DocIntelCompareResponse(BaseModel):
    question: str
    results: list[dict]  # una entrada por documento


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/upload", response_model=DocIntelUploadResponse)
async def upload_document(
    file: UploadFile = File(...),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """Sube un PDF, lo indexa en PostgreSQL y lo almacena en R2."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF.")

    content = await file.read()

    if len(content) > MAX_PDF_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds {MAX_PDF_SIZE_BYTES // 1024 // 1024}MB limit.",
        )

    try:
        result = index_document(db, content, file.filename)
        return DocIntelUploadResponse(
            **result,
            message=f"Successfully indexed {result['chunk_count']} chunks from {result['pages_processed']} pages.",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to index document: {e}") from e


@router.post("/ask", response_model=DocIntelAskResponse)
def ask(payload: DocIntelAskRequest, db: Session = Depends(get_db)):  # noqa: B008
    """Responde una pregunta buscando en los documentos indexados."""
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        result = answer_question(
            db=db,
            question=payload.question,
            filename=payload.filename,
            top_k=payload.top_k,
        )
        return DocIntelAskResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error answering question: {e}") from e


@router.post("/compare", response_model=DocIntelCompareResponse)
def compare(payload: DocIntelCompareRequest, db: Session = Depends(get_db)):  # noqa: B008
    """
    Lanza la misma pregunta contra todos los documentos indexados.
    Devuelve una respuesta por documento — útil para comparar información
    entre múltiples contratos, informes o manuales.
    """
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        results = compare_documents(
            db=db,
            question=payload.question,
            top_k=payload.top_k,
        )
        return DocIntelCompareResponse(
            question=payload.question,
            results=results,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comparing documents: {e}") from e


@router.get("/documents")
def get_documents(db: Session = Depends(get_db)):  # noqa: B008
    return {"documents": list_documents(db)}


@router.get("/document/{filename}/url")
def get_pdf_url(filename: str, db: Session = Depends(get_db)):  # noqa: B008
    try:
        url = get_document_url(db, filename)
        return {"filename": filename, "url": url, "expires_in": 3600}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/document/{filename}")
def delete_document_endpoint(filename: str, db: Session = Depends(get_db)):  # noqa: B008
    try:
        result = remove_document(db, filename)
        return {"ok": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/demo", response_class=HTMLResponse)
def serve_demo():
    return HTMLResponse(content=demo_html())
