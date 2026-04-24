"""
code_executor.py — Ejecución segura del código Pandas generado por Claude.

Cambio importante: ahora saneamos NaN/Inf antes de serializar. Estos valores
son válidos en Pandas/NumPy pero rompen json.dumps() con:
"Out of range float values are not JSON compliant: nan"

Convertimos NaN e Inf a None (que se serializa como null en JSON).
"""

from __future__ import annotations

import math
import signal
from contextlib import contextmanager
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

EXECUTION_TIMEOUT_SECONDS = 10

SAFE_BUILTINS = {
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "hash",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "object",
    "ord",
    "pow",
    "print",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "str",
    "sum",
    "tuple",
    "type",
    "zip",
    "True",
    "False",
    "None",
}


class ExecutionTimeout(Exception):
    """Se lanza cuando el código tarda más de EXECUTION_TIMEOUT_SECONDS."""


@contextmanager
def _timeout(seconds: int):
    """Context manager que interrumpe la ejecución si tarda demasiado."""
    try:
        if hasattr(signal, "SIGALRM"):

            def _handler(signum, frame):
                raise ExecutionTimeout(f"Code execution exceeded {seconds}s")

            old = signal.signal(signal.SIGALRM, _handler)
            signal.alarm(seconds)
        yield
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)


def execute(code: str, df: pd.DataFrame) -> dict:
    """Ejecuta código Python en un namespace restringido."""
    code = code.strip()
    if code.startswith("```"):
        code = _strip_markdown_fences(code)

    safe_builtins = {
        name: (
            __builtins__.get(name)
            if isinstance(__builtins__, dict)
            else getattr(__builtins__, name, None)
        )
        for name in SAFE_BUILTINS
    }
    safe_builtins = {k: v for k, v in safe_builtins.items() if v is not None}

    namespace = {
        "__builtins__": safe_builtins,
        "pd": pd,
        "np": np,
        "plt": plt,
        "df": df.copy(),
        "result": None,
    }

    try:
        with _timeout(EXECUTION_TIMEOUT_SECONDS):
            exec(code, namespace)

        result = namespace.get("result")
        return {
            "success": True,
            "result": _serialize_result(result),
            "result_type": type(result).__name__,
            "error": None,
            "code": code,
        }

    except ExecutionTimeout as e:
        return {
            "success": False,
            "result": None,
            "result_type": None,
            "error": f"Timeout: {e}",
            "code": code,
        }

    except Exception as e:
        return {
            "success": False,
            "result": None,
            "result_type": None,
            "error": f"{type(e).__name__}: {str(e)}",
            "code": code,
        }


# ── Helpers ──────────────────────────────────────────────────────────────


def _strip_markdown_fences(code: str) -> str:
    lines = code.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _clean_nan(value: Any) -> Any:
    """
    Convierte NaN e Inf a None para que json.dumps() no rompa.
    JSON no soporta NaN ni Inf, pero sí null (None en Python).
    """
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
    # numpy floats también pueden ser nan
    if isinstance(value, (np.floating,)):
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    return value


def _scalar(value: Any) -> Any:
    """Convierte un valor escalar a tipo nativo de Python y limpia NaN."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return str(value)
    if isinstance(value, np.ndarray):
        return [_scalar(v) for v in value.tolist()]
    return value


def _serialize_result(result: Any) -> Any:
    """
    Convierte el resultado a un formato serializable para JSON.
    Sanea NaN, Inf y tipos de numpy.
    """
    if result is None:
        return None

    if isinstance(result, pd.DataFrame):
        truncated = result.head(200)
        # Sanear el DataFrame antes de convertir a dict
        cleaned = _sanitize_dataframe(truncated)
        return {
            "type": "dataframe",
            "columns": list(cleaned.columns),
            "rows": cleaned.to_dict(orient="records"),
            "total_rows": len(result),
            "truncated": len(result) > 200,
        }

    if isinstance(result, pd.Series):
        # Saneamos cada valor de la Serie
        items = {}
        for k, v in result.head(200).items():
            items[str(k)] = _scalar(v)
        return {
            "type": "series",
            "name": str(result.name) if result.name is not None else None,
            "data": items,
            "total_items": len(result),
            "truncated": len(result) > 200,
        }

    if isinstance(result, (np.integer, np.floating)):
        return _scalar(result)

    if isinstance(result, (pd.Timestamp, pd.Timedelta)):
        return str(result)

    if isinstance(result, (list, tuple)):
        return [_scalar(v) for v in result]

    if isinstance(result, dict):
        return {str(k): _scalar(v) for k, v in result.items()}

    return _scalar(result)


def _sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Sanea un DataFrame convirtiendo NaN/Inf a None y tipos numpy a nativos.
    Devuelve una copia limpia del DataFrame.
    """
    # pandas 2.x: where con NaN a None no es trivial; usamos replace
    cleaned = df.copy()

    # Reemplazamos NaN/Inf por None en todas las columnas numéricas
    cleaned = cleaned.replace([np.inf, -np.inf], np.nan)
    # pandas no puede tener None en columnas numéricas, pero podemos cambiar
    # el dtype a object para que acepte None, o confiar en que to_dict
    # con astype(object) haga el trabajo
    cleaned = cleaned.astype(object).where(pd.notna(cleaned), None)

    return cleaned
