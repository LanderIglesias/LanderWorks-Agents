"""executor.py — Nodo Executor del grafo, con saneamiento de NaN/Inf."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..code_executor import execute as execute_pandas
from ..data_loader import get_dataframe
from ..sqlite_store import execute_sql
from ..state import AgentState


def executor_node(state: AgentState) -> dict:
    """Ejecuta el código de la subtarea actual (Pandas o SQL)."""
    idx = state["current_subtask_idx"]
    subtasks = list(state["subtasks"])
    subtask = subtasks[idx]
    specialist = subtask["specialist"]
    code = subtask["code"]

    if not code:
        subtask["error"] = "No code to execute (specialist did not generate code)"
        subtasks[idx] = subtask
        return {
            "subtasks": subtasks,
            "trace": [f"executor (task {idx + 1}: no code)"],
        }

    if specialist == "pandas":
        df = get_dataframe(state["session_id"])
        result = execute_pandas(code, df)
    elif specialist == "sql":
        sqlite_path = state["sqlite_path"]
        if not sqlite_path:
            subtask["error"] = "SQLite path not found in state"
            subtasks[idx] = subtask
            return {
                "subtasks": subtasks,
                "trace": [f"executor (task {idx + 1}: no sqlite)"],
            }
        result = _execute_sql_safely(code, sqlite_path)
    else:
        subtask["error"] = f"Unknown specialist: {specialist}"
        subtasks[idx] = subtask
        return {
            "subtasks": subtasks,
            "trace": [f"executor (task {idx + 1}: unknown specialist)"],
        }

    subtask["result"] = result["result"]
    subtask["result_type"] = result["result_type"]
    subtask["error"] = result["error"]
    subtasks[idx] = subtask

    status = "ok" if result["success"] else f"error: {result['error']}"
    return {
        "subtasks": subtasks,
        "trace": [f"executor (task {idx + 1}: {status})"],
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _execute_sql_safely(query: str, db_path: str) -> dict:
    """Ejecuta SQL y devuelve formato compatible con code_executor (con saneamiento)."""
    try:
        df = execute_sql(db_path, query)

        if len(df) == 0:
            return {
                "success": True,
                "result": {
                    "type": "dataframe",
                    "columns": list(df.columns),
                    "rows": [],
                    "total_rows": 0,
                    "truncated": False,
                },
                "result_type": "DataFrame",
                "error": None,
                "code": query,
            }

        truncated = df.head(200)

        # Saneamiento: NaN/Inf → None, numpy types → nativos
        cleaned = truncated.replace([np.inf, -np.inf], np.nan)
        cleaned = cleaned.astype(object).where(pd.notna(cleaned), None)
        rows = cleaned.to_dict(orient="records")

        # Pase extra por si queda algún tipo numpy raro
        for row in rows:
            for key, value in row.items():
                row[key] = _clean_scalar(value)

        return {
            "success": True,
            "result": {
                "type": "dataframe",
                "columns": list(df.columns),
                "rows": rows,
                "total_rows": len(df),
                "truncated": len(df) > 200,
            },
            "result_type": "DataFrame",
            "error": None,
            "code": query,
        }

    except Exception as e:
        return {
            "success": False,
            "result": None,
            "result_type": None,
            "error": f"{type(e).__name__}: {e}",
            "code": query,
        }


def _clean_scalar(value):
    """Convierte un valor a un tipo nativo JSON-safe."""
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if hasattr(value, "item"):  # otros numpy scalars
        try:
            v = value.item()
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return None
            return v
        except (ValueError, AttributeError):
            return str(value)
    return value
