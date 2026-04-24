"""
data_loader.py — Carga datos CSV o SQLite y los mantiene en memoria por sesión.

¿Por qué caché en memoria?
Cargar un CSV de 55k filas tarda ~200ms. Si lo recargáramos en cada pregunta
el agente sería lento. Mantenemos el DataFrame en memoria asociado a un
session_id que el cliente envía en cada request.

Nota sobre Render (producción):
Render tiene almacenamiento efímero y worker único por defecto, así que un
diccionario en memoria funciona correctamente. Si escalamos a múltiples workers
habría que migrar a Redis. Por ahora, memoria = suficiente.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

# ── Almacén de sesiones ────────────────────────────────────────────────────
# Diccionario global: session_id -> {df, schema, source_info}
# Cada sesión guarda el DataFrame y su metadata para no recalcular en cada request
_SESSIONS: dict[str, dict[str, Any]] = {}


def create_session_id() -> str:
    """Genera un ID único para una nueva sesión."""
    return str(uuid.uuid4())


def load_csv(path: str | Path, session_id: str | None = None) -> dict:
    """
    Carga un CSV y lo guarda en caché bajo un session_id.

    Args:
        path: ruta al archivo CSV
        session_id: si se proporciona, usa ese ID. Si no, genera uno nuevo.

    Returns:
        dict con session_id, schema del DataFrame, número de filas, etc.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV no encontrado: {path}")

    # Parseamos fechas automáticamente si hay columnas que parezcan fechas
    df = pd.read_csv(path)
    df = _auto_parse_dates(df)

    session_id = session_id or create_session_id()
    schema = _build_schema(df)

    _SESSIONS[session_id] = {
        "df": df,
        "schema": schema,
        "source": {"type": "csv", "path": str(path), "filename": path.name},
    }

    return {
        "session_id": session_id,
        "schema": schema,
        "rows": len(df),
        "columns": list(df.columns),
        "filename": path.name,
    }


def load_sqlite(db_path: str | Path, table: str, session_id: str | None = None) -> dict:
    """
    Carga una tabla de SQLite y la guarda en caché bajo un session_id.

    Args:
        db_path: ruta al archivo .db o .sqlite
        table: nombre de la tabla a cargar
        session_id: opcional, genera uno nuevo si no se pasa
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Base de datos no encontrada: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        # Validamos que la tabla existe antes de consultarla
        tables = pd.read_sql(
            "SELECT name FROM sqlite_master WHERE type='table'",
            conn,
        )
        if table not in tables["name"].values:
            raise ValueError(f"Tabla '{table}' no existe en {db_path.name}")

        df = pd.read_sql(f"SELECT * FROM {table}", conn)
        df = _auto_parse_dates(df)
    finally:
        conn.close()

    session_id = session_id or create_session_id()
    schema = _build_schema(df)

    _SESSIONS[session_id] = {
        "df": df,
        "schema": schema,
        "source": {"type": "sqlite", "path": str(db_path), "table": table},
    }

    return {
        "session_id": session_id,
        "schema": schema,
        "rows": len(df),
        "columns": list(df.columns),
        "table": table,
    }


def get_session(session_id: str) -> dict:
    """Devuelve los datos de una sesión. Lanza KeyError si no existe."""
    if session_id not in _SESSIONS:
        raise KeyError(f"Sesión no encontrada: {session_id}")
    return _SESSIONS[session_id]


def get_dataframe(session_id: str) -> pd.DataFrame:
    """Atajo para recuperar solo el DataFrame de una sesión."""
    return get_session(session_id)["df"]


def session_exists(session_id: str) -> bool:
    """Comprueba si una sesión está activa."""
    return session_id in _SESSIONS


def delete_session(session_id: str) -> bool:
    """Elimina una sesión y libera la memoria. Devuelve True si existía."""
    return _SESSIONS.pop(session_id, None) is not None


# ── Helpers internos ──────────────────────────────────────────────────────


def _auto_parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detecta columnas que parecen fechas y las parsea automáticamente.

    Criterio: si el nombre contiene 'date' o 'time' y el tipo es object,
    intentamos convertir. Si falla, dejamos como está.
    """
    for col in df.columns:
        if any(key in col.lower() for key in ["date", "time"]):
            if df[col].dtype == "object":
                try:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
                except (ValueError, TypeError):
                    pass  # no es fecha real, seguimos
    return df


def _build_schema(df: pd.DataFrame) -> dict:
    """
    Construye un resumen del DataFrame que Claude usará como contexto
    para generar código Pandas correcto.

    Incluye:
    - Nombre de cada columna
    - Tipo de cada columna (string legible)
    - Valores únicos para columnas categóricas (<10 únicos)
    - Min/max para numéricas y fechas
    """
    schema = {"columns": [], "row_count": len(df)}

    for col in df.columns:
        dtype = str(df[col].dtype)
        col_info = {"name": col, "dtype": dtype}

        # Para columnas categóricas con pocos valores únicos, guardamos la lista
        # Esto ayuda a Claude a generar filtros correctos (ej: plan="free")
        if df[col].dtype == "object" or df[col].nunique() < 10:
            uniques = df[col].dropna().unique()
            if len(uniques) <= 20:
                col_info["unique_values"] = [str(v) for v in uniques]

        # Para numéricas y fechas, guardamos rango
        if pd.api.types.is_numeric_dtype(df[col]):
            col_info["min"] = float(df[col].min()) if df[col].notna().any() else None
            col_info["max"] = float(df[col].max()) if df[col].notna().any() else None
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            col_info["min"] = str(df[col].min()) if df[col].notna().any() else None
            col_info["max"] = str(df[col].max()) if df[col].notna().any() else None

        schema["columns"].append(col_info)

    return schema
