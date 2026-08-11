"""categorizer.py — Categorización automática de gastos con Claude Haiku.

Mismo patrón que backend/agents/bi_agent/api.py::_interpret_anomalies:
cliente Anthropic creado por llamada, turno de assistant pre-rellenado con
"{" para forzar JSON puro, y try/except que degrada a un resultado neutro
(needs_review=True) si la llamada o el parseo fallan, en vez de tumbar el
webhook.
"""

from __future__ import annotations

import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv(override=False)

MODEL = "claude-haiku-4-5-20251001"

CATEGORIES = ["comida", "transporte", "suscripciones", "ocio", "salud", "hogar", "otros"]

CONFIDENCE_THRESHOLD = 0.6

SYSTEM_PROMPT = f"""You classify a single expense into exactly one category.

Categories (choose exactly one): {", ".join(CATEGORIES)}

Return ONLY a JSON object, no preamble, no explanation:
{{"category": "one of the categories above", "confidence": 0.0-1.0}}
"""


def categorize(merchant: str | None, amount: float) -> dict:
    """Devuelve {"category": str | None, "confidence": float}.

    confidence=0.0 y category=None si la llamada a Claude falla o la
    respuesta no se puede parsear — el caller (engine.py) interpreta eso
    como needs_review=True, igual que un regex sin match en parsers.py.
    """
    fallback = {"category": None, "confidence": 0.0}

    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    except Exception:
        return fallback

    user_msg = f"Merchant: {merchant or 'unknown'}\nAmount: {amount:.2f} EUR"

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=100,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": "{"},
            ],
        )
        raw = "{" + response.content[0].text
        parsed = json.loads(raw)
        category = parsed.get("category")
        confidence = float(parsed.get("confidence", 0.0))
        if category not in CATEGORIES:
            return fallback
        return {"category": category, "confidence": confidence}
    except Exception:
        return fallback
