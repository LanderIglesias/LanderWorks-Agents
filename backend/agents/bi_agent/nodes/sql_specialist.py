"""sql_specialist.py — Nodo SQL Specialist del grafo (con contexto time-series)."""

from __future__ import annotations

import os

import anthropic
from dotenv import load_dotenv

from ..state import AgentState

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024


SYSTEM_PROMPT = """You are a SQL analyst. You convert subtask descriptions into SQLite SELECT queries.

RULES:
1. Return ONLY the SQL query. No explanations, no markdown outside the code block.
2. ONLY SELECT queries — never INSERT, UPDATE, DELETE, DROP, ALTER, CREATE.
3. The table is named: {table_name}
4. Use ONLY columns that exist in the schema. Never invent column names.
5. For categorical filters, use the EXACT values from the schema (case-sensitive).
6. Dates are stored as TEXT in ISO format 'YYYY-MM-DD HH:MM:SS'. Use strftime() or string comparison for date ranges.
7. Use standard SQLite syntax. Functions available: COUNT, SUM, AVG, MIN, MAX, strftime, date, substr, round, cast.
8. Limit results to 1000 rows if not otherwise constrained.

{dataset_context}

SCHEMA OF THE TABLE `{table_name}`:
{schema_str}

{retry_block}

EXAMPLES:

Subtask: "Count unique users"
```sql
SELECT COUNT(DISTINCT user_id) AS unique_users FROM {table_name};
```

Subtask: "Total MRR by plan for the latest snapshot"
```sql
SELECT plan, SUM(mrr) AS total_mrr
FROM {table_name}
WHERE date = (SELECT MAX(date) FROM {table_name})
GROUP BY plan
ORDER BY total_mrr DESC;
```

Subtask: "Churn rate per plan: unique churned users / total unique users × 100"
```sql
SELECT
  plan,
  ROUND(
    100.0 *
    COUNT(DISTINCT CASE WHEN status = 'churned' THEN user_id END) /
    COUNT(DISTINCT user_id),
    2
  ) AS churn_rate_pct
FROM {table_name}
GROUP BY plan
ORDER BY churn_rate_pct DESC;
```

Subtask: "Signups per month in 2026"
```sql
SELECT strftime('%Y-%m', signup_date) AS month, COUNT(DISTINCT user_id) AS signups
FROM {table_name}
WHERE signup_date LIKE '2026%'
GROUP BY month
ORDER BY month;
```
"""

RETRY_INSTRUCTION = """
RETRY CONTEXT:
Your previous attempt failed with this feedback:
{feedback}

Analyze the feedback carefully and generate a CORRECTED version of the query.
"""


def sql_specialist_node(state: AgentState) -> dict:
    idx = state["current_subtask_idx"]
    subtasks = list(state["subtasks"])
    subtask = subtasks[idx]

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    schema_str = _format_schema_for_sql(state["schema"])
    dataset_context = _detect_dataset_context(state["schema"])
    table_name = state["table_name"]
    retry_block = ""
    if subtask["validation_feedback"]:
        retry_block = RETRY_INSTRUCTION.format(feedback=subtask["validation_feedback"])

    system = SYSTEM_PROMPT.format(
        table_name=table_name,
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
            {"role": "assistant", "content": "```sql"},
        ],
    )

    raw = "```sql" + response.content[0].text
    sql = _extract_sql(raw)

    subtask["code"] = sql
    subtasks[idx] = subtask

    return {
        "subtasks": subtasks,
        "trace": [f"sql_specialist (task {idx + 1}, retry={subtask['retry_count']})"],
    }


def _format_schema_for_sql(schema: dict) -> str:
    lines = [f"Total rows: {schema.get('row_count', 'unknown')}"]
    lines.append("Columns:")
    for col in schema.get("columns", []):
        sql_type = _dtype_to_sql(col.get("dtype", "object"))
        line = f"  - {col['name']} ({sql_type})"
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
1. To count entities: use COUNT(DISTINCT {entity_col}) — NEVER COUNT(*).
2. For rates/percentages involving entities: COUNT(DISTINCT ...) in BOTH numerator and denominator.
3. For "entities that ever had status X": COUNT(DISTINCT CASE WHEN status = 'X' THEN {entity_col} END)
4. For MRR/revenue "now": filter WHERE {date_col} = (SELECT MAX({date_col}) FROM {{table_name}}), then sum.
5. Churn rate per plan: (DISTINCT users with ever churned row) / (DISTINCT users in plan) × 100.
"""


def _dtype_to_sql(dtype: str) -> str:
    dtype = dtype.lower()
    if "int" in dtype:
        return "INTEGER"
    if "float" in dtype:
        return "REAL"
    if "datetime" in dtype:
        return "TEXT (ISO date)"
    if "bool" in dtype:
        return "INTEGER (0/1)"
    return "TEXT"


def _extract_sql(response: str) -> str:
    response = response.strip()
    if response.startswith("```sql"):
        response = response[len("```sql") :].lstrip("\n")
    elif response.startswith("```"):
        response = response[3:].lstrip("\n")
    if response.endswith("```"):
        response = response[:-3].rstrip()
    if "```" in response:
        response = response.split("```")[0].rstrip()
    return response.strip().rstrip(";")
