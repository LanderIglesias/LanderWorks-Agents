"""pandas_specialist.py — Nodo Pandas Specialist del grafo (con contexto time-series)."""

from __future__ import annotations

import os

import anthropic
from dotenv import load_dotenv

from ..state import AgentState

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024


SYSTEM_PROMPT = """You are a Python data analyst. You convert subtask descriptions into Pandas code.

RULES:
1. Return ONLY executable Python code. No explanations, no markdown outside the code block.
2. The DataFrame is ALREADY loaded as `df`. Do NOT read files or import anything.
3. Available in the namespace: pd (pandas), np (numpy), plt (matplotlib.pyplot).
4. You MUST assign the final answer to a variable called `result`.
5. Use ONLY columns that exist in the schema. Never invent column names.
6. For categorical filters, use the EXACT values from the schema (case-sensitive).
7. Keep the code concise — 1 to 10 lines. No functions, no classes.
8. If the subtask asks for a comparison or ranking, put the result in a DataFrame or Series with clear labels.

{dataset_context}

SCHEMA:
{schema_str}

{retry_block}

EXAMPLES:

Subtask: "Count unique users"
```python
result = df['user_id'].nunique()
```

Subtask: "MRR total grouped by plan sorted descending (most recent snapshot)"
```python
latest_date = df['date'].max()
result = df[df['date'] == latest_date].groupby('plan')['mrr'].sum().sort_values(ascending=False)
```

Subtask: "Churn rate per plan: unique churned users / total unique users per plan"
```python
churned = df[df['status'] == 'churned'].groupby('plan')['user_id'].nunique()
total = df.groupby('plan')['user_id'].nunique()
result = (churned / total * 100).sort_values(ascending=False).round(2)
```
"""

RETRY_INSTRUCTION = """
RETRY CONTEXT:
Your previous attempt failed with this feedback:
{feedback}

Analyze the feedback carefully and generate a CORRECTED version of the code.
"""


def pandas_specialist_node(state: AgentState) -> dict:
    idx = state["current_subtask_idx"]
    subtasks = list(state["subtasks"])
    subtask = subtasks[idx]

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    schema_str = _format_schema(state["schema"])
    dataset_context = _detect_dataset_context(state["schema"])
    retry_block = ""
    if subtask["validation_feedback"]:
        retry_block = RETRY_INSTRUCTION.format(feedback=subtask["validation_feedback"])

    system = SYSTEM_PROMPT.format(
        schema_str=schema_str,
        dataset_context=dataset_context,
        retry_block=retry_block,
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[
            {"role": "user", "content": subtask["description"]},
            {"role": "assistant", "content": "```python"},
        ],
    )

    raw = "```python" + response.content[0].text
    code = _extract_code(raw)

    subtask["code"] = code
    subtasks[idx] = subtask

    return {
        "subtasks": subtasks,
        "trace": [f"pandas_specialist (task {idx + 1}, retry={subtask['retry_count']})"],
    }


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
This is TIME-SERIES data: multiple rows per entity over time.
Each `{entity_col}` has one row per `{date_col}`.

CRITICAL RULES:
1. To count entities: use df['{entity_col}'].nunique() — NEVER len(df) or df.shape[0].
2. For rates/percentages involving entities: nunique() in BOTH numerator and denominator.
3. For "entities that ever had status X": df[df['status'] == 'X']['{entity_col}'].nunique()
4. For MRR/revenue "now": filter to the LATEST date first (df['{date_col}'].max()), then sum.
5. A user is "churned" if they appear with status='churned' at ANY point — use .nunique() on filtered df.
"""


def _extract_code(response: str) -> str:
    response = response.strip()
    if response.startswith("```python"):
        response = response[len("```python") :].lstrip("\n")
    elif response.startswith("```"):
        response = response[3:].lstrip("\n")
    if response.endswith("```"):
        response = response[:-3].rstrip()
    if "```" in response:
        response = response.split("```")[0].rstrip()
    return response.strip()
