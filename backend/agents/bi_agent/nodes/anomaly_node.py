"""
anomaly_node.py — Nodo Anomaly Detector del grafo LangGraph.

Se ejecuta DESPUÉS del executor pero ANTES del validator. Así el Validator
puede ver las anomalías como parte del contexto de la subtarea.

Flujo:
1. Toma el resultado de la subtarea actual
2. Lo pasa por anomaly_detector (estadística pura)
3. Si hay anomalías, pide a Claude que las explique en lenguaje de negocio
4. Añade las anomalías enriquecidas al estado global

Diseño clave — orden en el grafo:
  executor → anomaly_detector → validator
                                    ↓
                             specialist (si retry) o synthesizer

Importante: este nodo NUNCA marca un resultado como inválido. Las anomalías
son INFORMATIVAS, no errores. El Validator sigue siendo el único que decide
retry/fail.
"""

from __future__ import annotations

import os

import anthropic
from dotenv import load_dotenv

from ..anomaly_detector import analyze_result
from ..state import AgentState

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 600


INTERPRET_SYSTEM_PROMPT = """You are a data analyst reviewing anomaly detections from a statistical engine.

You receive:
- The user's original question
- The Pandas/SQL code that was executed
- A list of raw statistical anomalies (z-scores, spikes, segment deviations)

Your job: rewrite each anomaly as a 1-2 sentence business-language alert.

RULES:
1. Be concrete: mention the actual values, not "a high z-score".
2. When possible, suggest WHY it might be happening (hypothesis, not certainty).
3. Keep each alert under 40 words.
4. If multiple anomalies seem related, you can merge them.
5. Skip anomalies that are obvious or low-value (e.g., a single day slightly above average).
6. Return ONLY a JSON array of interpreted alerts. No preamble.

OUTPUT FORMAT:
[
  {
    "severity": "high" | "medium" | "low",
    "title": "Short title (max 8 words)",
    "message": "1-2 sentence business explanation with actual values",
    "metric": "the metric involved"
  }
]
"""


def anomaly_node(state: AgentState) -> dict:
    """
    Analiza el resultado de la subtarea actual y detecta anomalías.
    Añade las anomalías enriquecidas al estado global.
    """
    idx = state["current_subtask_idx"]
    subtasks = state["subtasks"]

    if idx >= len(subtasks):
        return {"trace": ["anomaly_detector (skipped: no current subtask)"]}

    subtask = subtasks[idx]

    # Si la subtarea falló, no hay nada que analizar
    if subtask["error"] or subtask["result"] is None:
        return {"trace": [f"anomaly_detector (task {idx + 1}: skipped, no result)"]}

    # Paso 1: detección estadística (sin LLM)
    raw_anomalies = analyze_result(subtask["result"], metric_name=subtask["description"][:40])

    if not raw_anomalies:
        return {"trace": [f"anomaly_detector (task {idx + 1}: no anomalies)"]}

    # Paso 2: interpretar con Claude (si hay suficientes anomalías)
    # Si solo hay 1-2 anomalías muy leves, no merece la pena la llamada al LLM
    significant = [a for a in raw_anomalies if a["severity"] in ("high", "medium")]
    if not significant:
        return {
            "anomalies": raw_anomalies[:3],
            "trace": [f"anomaly_detector (task {idx + 1}: {len(raw_anomalies)} minor)"],
        }

    interpreted = _interpret_with_llm(
        question=state["question"],
        code=subtask["code"] or "",
        anomalies=significant,
    )

    return {
        "anomalies": interpreted if interpreted else raw_anomalies[:3],
        "trace": [f"anomaly_detector (task {idx + 1}: {len(interpreted or significant)} detected)"],
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _interpret_with_llm(question: str, code: str, anomalies: list[dict]) -> list[dict]:
    """
    Pide a Claude que traduzca las anomalías estadísticas a alertas de negocio.
    Si Claude falla, devolvemos las anomalías crudas.
    """
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    except Exception:
        return []

    user_msg = f"""Original question: {question}

Code executed:
{code}

Raw statistical anomalies detected:
{_format_anomalies_for_prompt(anomalies)}

Interpret them as business-language alerts."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=INTERPRET_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": "["},
            ],
        )

        raw = "[" + response.content[0].text
        return _parse_json_array(raw)
    except Exception:
        return []


def _format_anomalies_for_prompt(anomalies: list[dict]) -> str:
    """Formato legible para el prompt del LLM."""
    lines = []
    for i, a in enumerate(anomalies, start=1):
        lines.append(f"Anomaly {i} [{a['severity']}]:")
        lines.append(f"  Type: {a['type']}")
        lines.append(f"  Metric: {a['metric']}")
        for k, v in a["details"].items():
            lines.append(f"  {k}: {v}")
        lines.append("")
    return "\n".join(lines)


def _parse_json_array(raw: str) -> list[dict]:
    """Extrae el array JSON de la respuesta. Similar al planner."""
    import json

    raw = raw.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Intento de extracción del array principal
    start = raw.find("[")
    if start == -1:
        return []

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(raw)):
        char = raw[i]
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                candidate = raw[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    return []

    return []
