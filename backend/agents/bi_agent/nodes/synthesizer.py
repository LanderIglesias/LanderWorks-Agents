"""
synthesizer.py — Nodo Synthesizer del grafo (Fase 3).

Cambio respecto a Fase 2: si el AnomalyDetector detectó anomalías,
el Synthesizer las incluye en la respuesta final al usuario.

Se mencionan de forma integrada en el texto, no como apéndice separado.
Claude decide cómo incluirlas de forma natural.
"""

from __future__ import annotations

import os

import anthropic
from dotenv import load_dotenv

from ..state import AgentState

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 800


SYSTEM_PROMPT = """You are a data analyst explaining query results to a business user.

You receive:
- The original question
- One or more subtask results (each with its code, result, and whether it succeeded)
- Optionally: a list of anomalies detected by a statistical engine

Your job: write a clear, concise answer in the same language as the question.

RULES:
1. Lead with the answer. No "sure, here's the analysis" preambles.
2. If there was only one subtask: explain that result directly.
3. If there were multiple subtasks: COMBINE them into a coherent answer.
4. Use markdown for readability: **bold** for key numbers, bullet points, tables when comparing.
5. If a subtask failed, mention it briefly but try to answer with what worked.
6. Add a short business insight at the end when it adds value.
7. Never mention "subtasks", "the code", "Pandas", "SQL" — implementation details the user doesn't care about.

IF ANOMALIES ARE PROVIDED:
- Include them in a dedicated "⚠️ Anomalies detected" section after the main answer.
- Use a bullet list, one line per anomaly with its title in bold.
- Only mention the 2-3 most important anomalies. Skip low-severity ones if there are many.
- Do NOT make up anomalies that aren't in the list.

Keep total response under 250 words.
"""


def synthesizer_node(state: AgentState) -> dict:
    """Genera la respuesta final combinando resultados + anomalías."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    subtasks_summary = _build_subtasks_summary(state["subtasks"])
    anomalies_summary = _build_anomalies_summary(state.get("anomalies", []))

    user_msg = f"""Original question: {state['question']}

Subtask results:
{subtasks_summary}
"""

    if anomalies_summary:
        user_msg += f"\nAnomalies detected by statistical engine:\n{anomalies_summary}\n"

    user_msg += "\nWrite the final answer."

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        answer = response.content[0].text.strip()
    except Exception as e:
        answer = _fallback_answer(state["subtasks"], str(e))

    final_result = _pick_final_result(state["subtasks"])

    return {
        "final_answer": answer,
        "final_result": final_result,
        "trace": ["synthesizer"],
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _build_subtasks_summary(subtasks: list) -> str:
    lines = []
    for i, st in enumerate(subtasks, start=1):
        lines.append(f"--- Subtask {i} ({st['specialist']}) ---")
        lines.append(f"Description: {st['description']}")
        lines.append(f"Code: {st['code']}")

        if st["error"]:
            lines.append(f"Status: FAILED — {st['error']}")
        else:
            result_str = _format_result(st["result"])
            lines.append(f"Result ({st['result_type']}): {result_str}")

        lines.append("")

    return "\n".join(lines)


def _build_anomalies_summary(anomalies: list[dict]) -> str:
    """Formatea las anomalías para el prompt."""
    if not anomalies:
        return ""

    # Filtrar las más relevantes: priorizar high y medium
    high = [a for a in anomalies if a.get("severity") == "high"]
    medium = [a for a in anomalies if a.get("severity") == "medium"]
    top = (high + medium)[:5]

    if not top:
        return ""

    lines = []
    for a in top:
        title = a.get("title", a.get("metric", "Anomaly"))
        message = a.get("message", "")
        severity = a.get("severity", "medium")
        lines.append(f"- [{severity}] {title}: {message}")

    return "\n".join(lines)


def _format_result(result) -> str:
    if result is None:
        return "None"

    if isinstance(result, dict):
        if result.get("type") == "dataframe":
            rows = result.get("rows", [])[:15]
            return (
                f"DataFrame ({result.get('total_rows')} rows, cols {result.get('columns')}): {rows}"
            )
        if result.get("type") == "series":
            items = list(result.get("data", {}).items())[:15]
            return f"Series ({result.get('total_items')} items): {items}"
        return str(result)

    if isinstance(result, list):
        return str(result[:15]) + (f" ...({len(result)} total)" if len(result) > 15 else "")

    return str(result)


def _pick_final_result(subtasks: list):
    """Elige qué resultado mostrar en la UI."""
    for st in reversed(subtasks):
        if not st["error"] and st["result"] is not None:
            return st["result"]
    return None


def _fallback_answer(subtasks: list, error: str) -> str:
    """Si el synthesizer LLM falla, devolvemos los resultados crudos."""
    lines = [f"Could not synthesize a natural language answer ({error}). Raw results:"]
    for i, st in enumerate(subtasks, start=1):
        if st["error"]:
            lines.append(f"- Task {i}: FAILED ({st['error']})")
        else:
            lines.append(f"- Task {i}: {_format_result(st['result'])}")
    return "\n".join(lines)
