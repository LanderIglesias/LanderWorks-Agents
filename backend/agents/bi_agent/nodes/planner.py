"""
planner.py — Nodo Planner del grafo LangGraph.

Rol: analiza la pregunta del usuario y decide si es simple (una subtarea)
o compleja (varias subtareas). Para cada subtarea, sugiere qué especialista
debe manejarla (pandas o sql).

Cambios:
- Detección automática de time-series en el dataset
- Extracción robusta de JSON (maneja texto extra que Claude a veces añade
  después del objeto JSON cerrado)
"""

from __future__ import annotations

import json
import os

import anthropic
from dotenv import load_dotenv

from ..state import AgentState, SpecialistType, create_subtask

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024


SYSTEM_PROMPT = """You are a data analysis planner. Your job is to break down a user's question into a list of subtasks.

Each subtask must specify:
- A short description of what to compute
- Which specialist should handle it: "pandas" or "sql"

GUIDELINES:
- Most questions are SIMPLE and need only 1 subtask.
- Only split into multiple subtasks when the question requires genuinely separate computations that must be combined afterwards (e.g., "compare X vs Y across two periods").
- Prefer SQL for: aggregations (SUM, AVG, COUNT), GROUP BY, WHERE filters, JOINs.
- Prefer Pandas for: pivoting, time-series resampling, percentile calculations, correlations, complex transformations.
- When in doubt, prefer pandas.
- Stay focused on exactly what the user asked. Do NOT add extra dimensions they didn't ask for (e.g., if user asks about "free and pro plans", do NOT include enterprise).

{dataset_context}

SCHEMA OF THE DATA:
{schema_str}

OUTPUT FORMAT — return ONLY a JSON object, nothing else. No preamble, no explanation after.
{{
  "subtasks": [
    {{
      "description": "Short, specific description. If counting users, say 'unique user_ids'.",
      "specialist": "pandas" or "sql"
    }}
  ]
}}

EXAMPLES:

Question: "How many unique users do we have?"
{{
  "subtasks": [
    {{"description": "Count the number of unique user_id values", "specialist": "sql"}}
  ]
}}

Question: "Which plan has the highest churn rate?"
{{
  "subtasks": [
    {{"description": "For each plan, calculate churn rate as (unique users that ever churned) / (total unique users in that plan) * 100. Sort descending.", "specialist": "pandas"}}
  ]
}}

Question: "Compare MRR between October and March"
{{
  "subtasks": [
    {{"description": "Calculate total MRR (sum of mrr column) for all rows where date is in October 2025", "specialist": "sql"}},
    {{"description": "Calculate total MRR for all rows where date is in March 2026", "specialist": "sql"}}
  ]
}}
"""


def planner_node(state: AgentState) -> dict:
    """Toma la pregunta y devuelve subtareas."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    schema_str = _format_schema(state["schema"])
    dataset_context = _detect_dataset_context(state["schema"])
    system = SYSTEM_PROMPT.format(
        schema_str=schema_str,
        dataset_context=dataset_context,
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[
            {"role": "user", "content": state["question"]},
            {"role": "assistant", "content": "{"},
        ],
    )

    raw = "{" + response.content[0].text
    parsed = _parse_json_robust(raw)

    if parsed is None:
        # Si el JSON es irrecuperable, fallback a una subtarea simple con la pregunta
        return {
            "subtasks": [create_subtask("task_1", state["question"], "pandas")],
            "current_subtask_idx": 0,
            "trace": ["planner (fallback: JSON parse error)"],
            "errors": [f"Planner JSON error, raw response: {raw[:200]}"],
        }

    raw_subtasks = parsed.get("subtasks", [])
    subtasks = []
    for i, st in enumerate(raw_subtasks, start=1):
        specialist: SpecialistType = st.get("specialist", "pandas")
        if specialist not in ("pandas", "sql"):
            specialist = "pandas"
        subtasks.append(
            create_subtask(
                task_id=f"task_{i}",
                description=st.get("description", state["question"]),
                specialist=specialist,
            )
        )

    if not subtasks:
        subtasks = [create_subtask("task_1", state["question"], "pandas")]

    return {
        "subtasks": subtasks,
        "current_subtask_idx": 0,
        "trace": [f"planner ({len(subtasks)} subtask{'s' if len(subtasks) > 1 else ''})"],
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _parse_json_robust(raw: str) -> dict | None:
    """
    Intenta parsear JSON de forma robusta, manejando casos donde Claude
    añade texto extra antes o después del objeto JSON.

    Estrategia:
    1. Intenta json.loads() directo (caso ideal)
    2. Si falla, busca el primer `{` y hace match con su `}` correspondiente
       contando llaves
    3. Si todo falla, devuelve None
    """
    raw = raw.strip()

    # Primer intento: JSON directo
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Segundo intento: extraer el objeto JSON principal
    # Buscamos el primer `{` y contamos llaves para encontrar su par
    start = raw.find("{")
    if start == -1:
        return None

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

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                # Encontramos el cierre del objeto principal
                candidate = raw[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return None

    return None


def _format_schema(schema: dict) -> str:
    lines = [f"Total rows: {schema.get('row_count', 'unknown')}"]
    lines.append("Columns:")
    for col in schema.get("columns", []):
        line = f"  - {col['name']} ({col['dtype']})"
        if "unique_values" in col and len(col["unique_values"]) <= 10:
            line += f" — values: {col['unique_values']}"
        if "min" in col and "max" in col:
            line += f" — range: [{col['min']}, {col['max']}]"
        lines.append(line)
    return "\n".join(lines)


def _detect_dataset_context(schema: dict) -> str:
    """Detecta si es time-series y lo avisa al LLM."""
    cols = {c["name"].lower(): c for c in schema.get("columns", [])}
    date_cols = [
        c for c in cols.values() if "date" in c["name"].lower() or "time" in c["name"].lower()
    ]
    id_cols = [
        c for c in cols.values() if c["name"].lower().endswith("_id") or c["name"].lower() == "id"
    ]

    if not date_cols or not id_cols or schema.get("row_count", 0) < 1000:
        return ""

    entity_col = id_cols[0]["name"]
    date_col = date_cols[0]["name"]

    return f"""IMPORTANT — DATASET STRUCTURE:
This dataset is TIME-SERIES: multiple rows per entity over time.
Each `{entity_col}` has one row per `{date_col}`.

CRITICAL RULES WHEN PLANNING:
1. Counting entities → use unique counts (COUNT DISTINCT / nunique)
2. Rates/percentages → unique counts in BOTH numerator and denominator
3. "Users that ever had status X" → use DISTINCT {entity_col} where status = X
4. Financial metrics (MRR, revenue) at "current" moment → filter to latest date first
5. Churn analysis → (unique users ever churned) / (unique users in segment) × 100
"""
