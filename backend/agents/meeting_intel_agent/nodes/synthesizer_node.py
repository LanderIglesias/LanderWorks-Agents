"""
synthesizer_node.py — Nodo 5 del Meeting Intelligence Agent

Responsabilidad: generar el resumen ejecutivo de la reunión.

A diferencia del extractor (que procesa segmentos uno a uno),
el synthesizer recibe TODAS las extracciones consolidadas y
genera una visión global de la reunión.

Puede hacer esto porque las decisions, action items, etc. ya están
condensados — no necesita leer la transcripción entera, solo los
hallazgos estructurados del extractor.
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

SYSTEM_PROMPT = """You are an expert meeting facilitator who writes concise, actionable executive summaries.

Your summaries are:
- 3-5 sentences maximum
- Written in the same language as the meeting content
- Focused on outcomes and next steps, not process
- Clear enough for someone who wasn't in the meeting to understand what happened

Always respond with valid JSON only — no markdown, no preamble."""


def synthesizer_node(state: MeetingState) -> dict:
    """
    Nodo 5: genera el resumen ejecutivo y los temas clave de la reunión.

    Returns:
        dict con:
        - executive_summary: resumen ejecutivo de 3-5 frases
        - key_topics: lista de temas principales tratados
    """
    print("[SynthesizerNode] Generando resumen ejecutivo...")

    if state.get("error"):
        return {}

    decisions = state.get("decisions", [])
    action_items = state.get("action_items", [])
    open_questions = state.get("open_questions", [])
    pending_topics = state.get("pending_topics", [])

    # Si no hay nada extraído, generamos un resumen básico de la transcripción
    if not any([decisions, action_items, open_questions, pending_topics]):
        return {
            "executive_summary": "No structured information could be extracted from this meeting.",
            "key_topics": [],
        }

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = f"""Generate an executive summary for this meeting based on the extracted information.

MEETING TITLE: {state.get("meeting_title", "Untitled Meeting")}
LANGUAGE: {state.get("transcription_language", "es")}

DECISIONS MADE ({len(decisions)}):
{json.dumps(decisions, ensure_ascii=False, indent=2)}

ACTION ITEMS ({len(action_items)}):
{json.dumps(action_items, ensure_ascii=False, indent=2)}

OPEN QUESTIONS ({len(open_questions)}):
{json.dumps(open_questions, ensure_ascii=False, indent=2)}

PENDING TOPICS ({len(pending_topics)}):
{json.dumps(pending_topics, ensure_ascii=False, indent=2)}

Respond ONLY with this JSON:
{{
    "executive_summary": "3-5 sentence summary of what happened and what comes next",
    "key_topics": ["topic 1", "topic 2", "topic 3"]
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
        result = json.loads(clean)

        print(f"[SynthesizerNode] Resumen generado. " f"Temas: {result.get('key_topics', [])}")

        return {
            "executive_summary": result.get("executive_summary", ""),
            "key_topics": result.get("key_topics", []),
        }

    except json.JSONDecodeError:
        # Fallback si Claude no devuelve JSON válido
        return {
            "executive_summary": f"Meeting with {len(decisions)} decisions and {len(action_items)} action items.",
            "key_topics": [],
        }
    except Exception as e:
        return {"error": f"Synthesis failed: {e}"}
