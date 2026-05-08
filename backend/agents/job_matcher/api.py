"""
API del Job Matcher Agent.

Endpoints:
- POST /job-matcher/analyze — analiza CV (PDF/DOCX) + oferta (URL/texto)
- GET  /job-matcher/health  — estado del modelo
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .extractor import extraer_texto_docx, extraer_texto_pdf, scrapeear_url
from .feature_extractor import calcular_features, extraer_info_cv, extraer_info_oferta
from .llm_engine import generar_informe
from .templates import job_matcher_html

router = APIRouter(prefix="/job-matcher", tags=["job-matcher"])

# Cargamos el modelo al arrancar
MODEL_PATH = Path("backend/agents/job_matcher/training/model.pkl")


def _cargar_modelo():
    if not MODEL_PATH.exists():
        raise RuntimeError(
            "Modelo no encontrado. Ejecuta primero: "
            "python -m backend.agents.job_matcher.training.train_model"
        )
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


try:
    _modelo_data = _cargar_modelo()
    _modelo = _modelo_data["modelo"]
    _features = _modelo_data["features"]
    _modelo_ok = True
except RuntimeError as e:
    print(f"[JOB-MATCHER] Warning: {e}")
    _modelo_ok = False


class AnalysisResult(BaseModel):
    score: float
    nivel_encaje: str
    info_cv: dict
    info_oferta: dict
    features: dict
    informe: str
    modelo_mae: float


@router.post("/analyze", response_model=AnalysisResult)
async def analyze(
    cv: UploadFile = File(..., description="CV en formato PDF o DOCX"),  # noqa: B008
    oferta_url: str = Form(default="", description="URL de la oferta (opcional)"),
    oferta_texto: str = Form(default="", description="Texto de la oferta (opcional si hay URL)"),
):
    """
    Analiza el encaje entre un CV y una oferta de empleo.

    Acepta:
    - CV como archivo PDF o DOCX
    - Oferta como URL scrapeble O como texto pegado directamente

    Devuelve:
    - Score 0-100 calculado por el modelo ML
    - Informe cualitativo generado por Claude
    - Gaps identificados y recomendaciones concretas
    """
    if not _modelo_ok:
        raise HTTPException(status_code=503, detail="Modelo ML no disponible")

    # ── 1. Extraer texto del CV ────────────────────────────────────────────────
    contenido_cv = await cv.read()
    nombre = cv.filename or ""

    if nombre.lower().endswith(".pdf"):
        texto_cv = extraer_texto_pdf(contenido_cv)
    elif nombre.lower().endswith(".docx"):
        texto_cv = extraer_texto_docx(contenido_cv)
    else:
        raise HTTPException(status_code=400, detail="Formato de CV no soportado. Usa PDF o DOCX.")

    if not texto_cv.strip():
        raise HTTPException(status_code=400, detail="No se pudo extraer texto del CV")

    # ── 2. Extraer texto de la oferta ─────────────────────────────────────────
    if oferta_url.strip():
        try:
            texto_oferta = scrapeear_url(oferta_url.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904
    elif oferta_texto.strip():
        texto_oferta = oferta_texto.strip()
    else:
        raise HTTPException(status_code=400, detail="Proporciona una URL o el texto de la oferta")

    # ── 3. Extraer informacion estructurada con Claude ────────────────────────
    info_cv = extraer_info_cv(texto_cv)
    info_oferta = extraer_info_oferta(texto_oferta)

    # ── 4. Calcular features y predecir score ─────────────────────────────────
    features = calcular_features(info_cv, info_oferta)
    features_modelo = {k: v for k, v in features.items() if k != "techs_match_detalle"}
    X = pd.DataFrame([features_modelo])[_features]
    score = float(np.clip(_modelo.predict(X)[0], 0, 100))

    nivel_encaje = (
        "excelente"
        if score >= 80
        else "bueno" if score >= 60 else "medio" if score >= 40 else "bajo"
    )

    # ── 5. Generar informe con Claude ─────────────────────────────────────────
    informe = generar_informe(score, info_cv, info_oferta, features)

    return AnalysisResult(
        score=round(score, 1),
        nivel_encaje=nivel_encaje,
        info_cv=info_cv,
        info_oferta=info_oferta,
        features=features,
        informe=informe,
        modelo_mae=round(_modelo_data.get("mae_cv", 0), 2),
    )


@router.get("/health")
def health():
    """Estado del modelo ML."""
    if not _modelo_ok:
        return {"status": "modelo no disponible"}
    return {
        "status": "ok",
        "modelo": "GradientBoostingRegressor",
        "mae_cv": round(_modelo_data.get("mae_cv", 0), 2),
        "r2_test": round(_modelo_data.get("r2_test", 0), 3),
        "features": _features,
    }


@router.get("/", response_class=HTMLResponse)
def serve_ui():
    return HTMLResponse(content=job_matcher_html())
