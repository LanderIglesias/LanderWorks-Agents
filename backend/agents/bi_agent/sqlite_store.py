"""
sqlite_store.py — Gestiona la conversión DataFrame → SQLite temporal.

¿Por qué esto?
El SQL Specialist necesita ejecutar SQL real contra una base de datos. Como
los datos los carga el usuario desde un CSV, creamos un SQLite temporal
por cada sesión.

Lifecycle:
1. Usuario sube CSV → data_loader lo carga en memoria como DataFrame
2. Al crear el grafo por primera vez → convertimos el DF a SQLite temporal
3. El SQL Specialist ejecuta queries contra ese SQLite
4. Cuando la sesión se elimina → borramos el archivo SQLite

El SQLite vive en /tmp durante la sesión. No es persistente entre reinicios
del servidor — igual que el DataFrame en memoria.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pandas as pd

# Directorio temporal para los SQLite de cada sesión
SQLITE_DIR = Path(tempfile.gettempdir()) / "bi_agent_sqlite"
SQLITE_DIR.mkdir(parents=True, exist_ok=True)


def create_sqlite_from_dataframe(
    df: pd.DataFrame,
    session_id: str,
    table_name: str = "data",
) -> str:
    """
    Crea un SQLite temporal con el DataFrame como una tabla.

    Args:
        df: DataFrame a volcar
        session_id: ID de la sesión (para nombrar el archivo)
        table_name: nombre de la tabla en SQLite (default: "data")

    Returns:
        Ruta absoluta al archivo SQLite creado
    """
    db_path = SQLITE_DIR / f"{session_id}.db"

    # Si ya existe para esta sesión, lo sobreescribimos
    if db_path.exists():
        db_path.unlink()

    # Convertimos columnas datetime a ISO string — SQLite no tiene tipo nativo
    # para datetime, así que las guardamos como TEXT y las parseamos al vuelo
    df_to_save = df.copy()
    for col in df_to_save.columns:
        if pd.api.types.is_datetime64_any_dtype(df_to_save[col]):
            df_to_save[col] = df_to_save[col].dt.strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(str(db_path))
    try:
        df_to_save.to_sql(table_name, conn, if_exists="replace", index=False)

        # Creamos índices en columnas que probablemente se usen en WHERE
        # (columnas categóricas con pocos valores únicos)
        _create_auto_indices(conn, df, table_name)

        conn.commit()
    finally:
        conn.close()

    return str(db_path)


def delete_sqlite(session_id: str) -> bool:
    """
    Elimina el SQLite de una sesión.

    Returns:
        True si el archivo existía y se eliminó.
    """
    db_path = SQLITE_DIR / f"{session_id}.db"
    if db_path.exists():
        db_path.unlink()
        return True
    return False


def execute_sql(db_path: str, query: str) -> pd.DataFrame:
    """
    Ejecuta una query SELECT y devuelve el resultado como DataFrame.

    Solo permite queries de lectura — bloquea INSERT, UPDATE, DELETE, DROP.
    Esto es defensa en profundidad: aunque Claude tiene instrucciones de solo
    generar SELECT, validamos aquí también.
    """
    query_upper = query.upper().strip()
    forbidden_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]
    for keyword in forbidden_keywords:
        if keyword in query_upper:
            raise ValueError(f"Query contains forbidden keyword: {keyword}")

    conn = sqlite3.connect(db_path)
    try:
        return pd.read_sql(query, conn)
    finally:
        conn.close()


def get_sqlite_schema(db_path: str, table_name: str = "data") -> dict:
    """
    Devuelve el schema de la tabla en formato SQL-friendly.
    Útil para pasárselo a Claude cuando genere SQL.
    """
    conn = sqlite3.connect(db_path)
    try:
        # PRAGMA table_info devuelve: cid, name, type, notnull, default, pk
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        columns = [
            {"name": row[1], "type": row[2], "notnull": bool(row[3])} for row in cursor.fetchall()
        ]

        # Contamos filas
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
        row_count = cursor.fetchone()[0]

        return {
            "table_name": table_name,
            "columns": columns,
            "row_count": row_count,
        }
    finally:
        conn.close()


# ── Helpers internos ──────────────────────────────────────────────────────


def _create_auto_indices(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    table_name: str,
) -> None:
    """
    Crea índices automáticamente en columnas que probablemente se usen
    en WHERE o GROUP BY.

    Heurística:
    - Columnas categóricas con <100 valores únicos → índice útil
    - Columnas tipo fecha → índice útil para ranges
    - Columnas numéricas sin muchos valores únicos → índice útil
    """
    for col in df.columns:
        nunique = df[col].nunique()
        total = len(df)

        # Si tiene pocos valores únicos en relación al total, crear índice
        if nunique < min(100, total * 0.5):
            safe_col = col.replace(" ", "_").replace("-", "_")
            index_name = f"idx_{table_name}_{safe_col}"
            try:
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {index_name} " f'ON {table_name}("{col}")'
                )
            except sqlite3.Error:
                # Si falla por algún motivo (nombre raro), seguimos sin el índice
                pass
