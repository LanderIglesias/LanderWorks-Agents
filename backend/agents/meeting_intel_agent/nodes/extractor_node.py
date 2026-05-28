"""
extractor_node.py — Nodo 3 del Meeting Intelligence Agent

Responsabilidad: extraer información estructurada de cada segmento
de la transcripción usando Claude.

Por cada segmento extrae:
- decisions: decisiones tomadas en la reunión
- action_items: tareas asignadas con responsable, fecha y prioridad
- open_questions: preguntas que quedaron sin responder
- pending_topics: temas que quedaron pendientes para otra reunión

Claude recibe cada segmento por separado (no toda la transcripción)
para maximizar la precisión y no saturar el context window.
Los resultados de todos los segmentos se fusionan al final.
"""

from __future__ import annotations

import json
import os

import anthropic
from dotenv import load_dotenv

from ..state import MeetingState

load_dotenv(override=False)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

SYSTEM_PROMPT = """You are an expert meeting analyst. Your job is to extract structured information from meeting transcription segments.

Extract ONLY information explicitly mentioned in the text. Do NOT infer or assume.
If something is not mentioned, return an empty list for that category.

Always respond with valid JSON only — no markdown, no preamble, no explanation.
"""


def extractor_node(state: MeetingState) -> dict:
    """
    Nodo 3: extrae información estructurada de la transcripción.

    Procesa cada segmento con Claude y fusiona los resultados.
    """
    print("[ExtractorNode] Iniciando...")

    if state.get("error"):
        return {}

    segments = state.get("segments")
    if not segments:
        return {"error": "No segments available for extraction"}

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    all_decisions = []
    all_action_items = []
    all_questions = []
    all_pending = []

    for i, segment in enumerate(segments):
        print(f"[ExtractorNode] Procesando segmento {i+1}/{len(segments)}...")

        result = _extract_from_segment(client, segment["text"])

        all_decisions.extend(result.get("decisions", []))
        all_action_items.extend(result.get("action_items", []))
        all_questions.extend(result.get("open_questions", []))
        all_pending.extend(result.get("pending_topics", []))

    # Deduplicamos items muy similares
    all_decisions = _deduplicate(all_decisions, key="text")
    all_action_items = _deduplicate(all_action_items, key="task")
    all_questions = _deduplicate(all_questions, key="question")
    all_pending = _deduplicate(all_pending, key="topic")

    print(
        f"[ExtractorNode] Extraído: {len(all_decisions)} decisions, "
        f"{len(all_action_items)} action items, "
        f"{len(all_questions)} open questions, "
        f"{len(all_pending)} pending topics"
    )

    return {
        "decisions": all_decisions,
        "action_items": all_action_items,
        "open_questions": all_questions,
        "pending_topics": all_pending,
    }


def _extract_from_segment(client: anthropic.Anthropic, segment_text: str) -> dict:
    """
    Llama a Claude para extraer información estructurada de un segmento.
    Devuelve un dict con las 4 categorías.
    """
    prompt = f"""Extract structured information from this meeting transcript segment.

TRANSCRIPT SEGMENT:
{segment_text}

Respond ONLY with a JSON object in this exact format:
{{
    "decisions": [
        {{"text": "decision made", "context": "brief context"}}
    ],
    "action_items": [
        {{
            "task": "what needs to be done",
            "owner": "person responsible (or 'unassigned' if not mentioned)",
            "deadline": "deadline (or 'not specified' if not mentioned)",
            "priority": "high|medium|low"
        }}
    ],
    "open_questions": [
        {{"question": "question that was raised", "context": "brief context"}}
    ],
    "pending_topics": [
        {{"topic": "topic left for later", "reason": "why it was deferred"}}
    ]
}}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)

    except json.JSONDecodeError:
        # Si Claude no devuelve JSON válido, devolvemos listas vacías
        # El agente no falla — simplemente ese segmento no aporta extracciones
        print("[ExtractorNode] JSON decode error en segmento — saltando")
        return {
            "decisions": [],
            "action_items": [],
            "open_questions": [],
            "pending_topics": [],
        }
    except Exception as e:
        print(f"[ExtractorNode] Error en segmento: {e}")
        return {
            "decisions": [],
            "action_items": [],
            "open_questions": [],
            "pending_topics": [],
        }


def _deduplicate(items: list[dict], key: str) -> list[dict]:
    """
    Elimina items duplicados o muy similares basándose en el campo key.
    Comparación simple por texto exacto — suficiente para la mayoría de casos.
    """
    seen = set()
    result = []
    for item in items:
        value = item.get(key, "").strip().lower()
        if value and value not in seen:
            seen.add(value)
            result.append(item)
    return result
