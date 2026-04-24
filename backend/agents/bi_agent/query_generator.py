"""
query_generator.py — Convierte preguntas en lenguaje natural a código Pandas.

Este es el "cerebro" del agente en la Fase 1. Le pasamos a Claude:
1. La pregunta del usuario
2. El schema del DataFrame (columnas, tipos, valores únicos, rangos)

Y Claude devuelve código Pandas ejecutable que asigna el resultado a `result`.

¿Por qué pasamos el schema en el prompt?
Sin schema, Claude inventaría nombres de columnas ("sales", "revenue") que
probablemente no existen. Con el schema, sabe exactamente qué columnas hay,
qué valores aceptan (ej: plan="free" vs plan="Free") y los rangos.

¿Por qué assistant prefill?
Forzamos que Claude empiece a responder con ```python para garantizar que
devuelve código puro, sin explicaciones antes. Es el mismo truco que usamos
en el PDF translator con {"role": "assistant", "content": "{"}.
"""

from __future__ import annotations

import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

# ── Configuración ────────────────────────────────────────────────────────

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024


# ── Prompt del sistema ───────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Python data analyst. You convert natural language questions into Pandas code.

RULES:
1. Return ONLY executable Python code. No explanations, no markdown outside the code block.
2. The DataFrame is ALREADY loaded as `df`. Do NOT read files or import anything.
3. Available in the namespace: pd (pandas), np (numpy), plt (matplotlib.pyplot).
4. You MUST assign the final answer to a variable called `result`.
5. Use ONLY columns that exist in the schema below. Never invent column names.
6. For categorical filters, use the EXACT values from the schema (case-sensitive).
7. For date comparisons, use pd.Timestamp() or string format 'YYYY-MM-DD'.
8. If the question is ambiguous, pick the most reasonable interpretation and go with it.
9. Keep the code concise — 1 to 10 lines is ideal. No functions or classes.
10. If the question asks for a comparison, put the result in a DataFrame with clear column names.

SCHEMA OF THE DATAFRAME:
{schema_str}

EXAMPLES of good output:

Question: "How many unique users do we have?"
```python
result = df['user_id'].nunique()
```

Question: "What's the MRR by plan?"
```python
result = df.groupby('plan')['mrr'].sum().sort_values(ascending=False)
```

Question: "Which plan has the highest churn?"
```python
churned = df[df['status'] == 'churned'].groupby('plan')['user_id'].nunique()
total = df.groupby('plan')['user_id'].nunique()
result = (churned / total * 100).sort_values(ascending=False).round(2)
```
"""


# ── Función principal ────────────────────────────────────────────────────


def generate_pandas_code(question: str, schema: dict) -> dict:
    """
    Llama a Claude Haiku para convertir una pregunta en código Pandas.

    Args:
        question: pregunta del usuario en lenguaje natural
        schema: dict con columnas, tipos y valores únicos del DataFrame

    Returns:
        dict con:
        - code: string con el código Pandas generado
        - raw_response: respuesta cruda de Claude (útil para debug)
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    schema_str = _format_schema_for_prompt(schema)
    system = SYSTEM_PROMPT.format(schema_str=schema_str)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[
            {"role": "user", "content": question},
            # Prefill: forzamos que Claude empiece con ```python para que
            # devuelva código limpio sin preámbulos
            {"role": "assistant", "content": "```python"},
        ],
    )

    raw = response.content[0].text
    # La respuesta empieza justo después del prefill, añadimos de vuelta el ```python
    # para que el code_executor pueda detectar y limpiar el bloque
    full_response = "```python" + raw

    code = _extract_code(full_response)

    return {
        "code": code,
        "raw_response": full_response,
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _format_schema_for_prompt(schema: dict) -> str:
    """
    Convierte el schema a un formato legible para Claude.

    El schema viene de data_loader._build_schema() con estructura:
    {
        "row_count": 55582,
        "columns": [
            {"name": "plan", "dtype": "object", "unique_values": ["free", "pro", ...]},
            {"name": "mrr", "dtype": "int64", "min": 0, "max": 299},
            ...
        ]
    }
    """
    lines = [f"Total rows: {schema.get('row_count', 'unknown')}"]
    lines.append("Columns:")

    for col in schema.get("columns", []):
        line = f"  - {col['name']} ({col['dtype']})"

        if "unique_values" in col:
            values = col["unique_values"]
            # Limitamos la longitud para no saturar el prompt
            if len(values) <= 10:
                line += f" — values: {values}"
            else:
                line += f" — {len(values)} unique values, sample: {values[:5]}"

        if "min" in col and "max" in col:
            line += f" — range: [{col['min']}, {col['max']}]"

        lines.append(line)

    return "\n".join(lines)


def _extract_code(response: str) -> str:
    """
    Extrae el código Python del bloque markdown.

    Claude devuelve: ```python\n<code>\n```
    Queremos solo el <code>.
    """
    response = response.strip()

    # Si empieza con ```python, quitamos la primera línea
    if response.startswith("```python"):
        response = response[len("```python") :].lstrip("\n")
    elif response.startswith("```"):
        response = response[3:].lstrip("\n")

    # Si termina con ```, lo quitamos
    if response.endswith("```"):
        response = response[:-3].rstrip()

    # Si hay texto después del código (explicaciones que Claude añade a veces),
    # cortamos en el primer ``` que encontremos
    if "```" in response:
        response = response.split("```")[0].rstrip()

    return response.strip()
