"""
router.py — Endpoints FastAPI del PDF Translator v2

Misma interfaz que v1 pero usa el grafo LangGraph internamente.
El endpoint muestra el número de iteraciones del quality gate en los headers.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .graph import translate_pdf

router = APIRouter(prefix="/pdf-translator-v2", tags=["PDF Translator v2 — LangGraph"])

TEMP_DIR = tempfile.gettempdir()
OUTPUT_DIR = os.path.join(TEMP_DIR, "pdf_translator_v2_outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SUPPORTED_LANGUAGES = {
    "spanish": "Español",
    "english": "English",
    "french": "Français",
    "german": "Deutsch",
    "italian": "Italiano",
    "portuguese": "Português",
    "dutch": "Nederlands",
    "polish": "Polski",
    "russian": "Русский",
    "chinese": "中文",
    "japanese": "日本語",
    "catalan": "Català",
}


@router.get("/languages")
async def get_languages():
    return {"languages": SUPPORTED_LANGUAGES}


@router.get("/health")
async def health():
    return {"status": "ok", "agent": "PDF Translator v2 — LangGraph", "version": "2.0.0"}


@router.post("/translate")
async def translate(
    file: UploadFile = File(...),
    target_language: str = Form(...),
    source_language: str = Form(default="auto"),
    max_quality_iterations: int = Form(default=2),
):
    """
    Traduce un PDF usando el pipeline LangGraph con quality gate.

    - **max_quality_iterations**: cuántas veces puede el quality gate
      pedir retraducción (1-3, default 2)
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El fichero debe ser un PDF.")

    if target_language.lower() not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Idioma '{target_language}' no soportado.")

    max_quality_iterations = max(1, min(3, max_quality_iterations))

    job_id = str(uuid.uuid4())[:8]
    input_path = os.path.join(TEMP_DIR, f"input_v2_{job_id}.pdf")
    output_dir = os.path.join(OUTPUT_DIR, job_id)

    try:
        content = await file.read()
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="PDF demasiado grande (máx 50MB).")

        with open(input_path, "wb") as f:
            f.write(content)

        result = translate_pdf(
            input_pdf_path=input_path,
            target_language=target_language.lower(),
            output_dir=output_dir,
            source_language=source_language,
            max_quality_iterations=max_quality_iterations,
        )

        if not result["success"]:
            raise HTTPException(status_code=500, detail=result.get("error", "Error desconocido"))

        output_path = result["output_path"]
        if not os.path.exists(output_path):
            raise HTTPException(status_code=500, detail="El PDF no se generó correctamente.")

        original_name = Path(file.filename).stem
        download_name = f"{original_name}_{target_language}_v2.pdf"

        stats = result.get("stats", {})

        return FileResponse(
            path=output_path,
            media_type="application/pdf",
            filename=download_name,
            headers={
                "X-Pages": str(stats.get("pages", 0)),
                "X-Blocks-Translated": str(stats.get("translatable", 0)),
                "X-Time-Seconds": str(stats.get("time_seconds", 0)),
                "X-Quality-Iterations": str(stats.get("quality_iterations", 0)),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)


@router.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Sirve el frontend del agente."""
    html_path = Path(__file__).parent / "frontend" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>PDF Translator v2</h1><p>Frontend not found.</p>")
