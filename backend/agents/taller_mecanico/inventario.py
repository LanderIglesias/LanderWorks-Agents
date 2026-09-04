"""inventario.py — herramienta determinista de piezas (hito 2).

CRUD de `piezas` con una regla de negocio real: no se puede descontar
más stock del disponible (el `CHECK (stock >= 0)` del esquema es la
última línea de defensa; aquí se rechaza ANTES de tocar la fila, con un
error de dominio legible en vez de dejar que la excepción de SQLite
llegue tal cual al agente que llame a esta herramienta).

Sin razonamiento de IA — funciones aisladas para que los agentes de los
hitos 3+ las invoquen como herramienta.
"""

from __future__ import annotations

import sqlite3


class PiezaNoEncontradaError(LookupError):
    """No existe ninguna pieza con el id dado."""


class StockInsuficienteError(ValueError):
    """Se pidió descontar más stock del que hay disponible."""


def alta_pieza(
    conn: sqlite3.Connection,
    nombre: str,
    precio_unitario: float,
    referencia: str | None = None,
    stock_inicial: int = 0,
    stock_minimo: int = 0,
    es_compatible: int = 0,
) -> int:
    """Da de alta una pieza nueva en el catálogo. `es_compatible=1` marca
    la pieza como compatible/aftermarket (0 = original) — usado por
    presupuestador.py (hito 7) para decidir entre pieza original vs.
    compatible. Lanza sqlite3.IntegrityError si `referencia` ya existe o
    `precio_unitario`/stock/es_compatible no cumplen el CHECK/UNIQUE del
    esquema."""
    try:
        cur = conn.execute(
            "INSERT INTO piezas (nombre, referencia, stock, stock_minimo, precio_unitario, es_compatible) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nombre, referencia, stock_inicial, stock_minimo, precio_unitario, es_compatible),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise
    assert cur.lastrowid is not None  # siempre hay id tras un INSERT que no lanzó
    return cur.lastrowid


def _get_pieza(conn: sqlite3.Connection, pieza_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM piezas WHERE id = ?", (pieza_id,)).fetchone()
    if row is None:
        raise PiezaNoEncontradaError(f"No existe la pieza {pieza_id}.")
    return row


def consultar_stock(conn: sqlite3.Connection, pieza_id: int) -> int:
    """Devuelve el stock actual de una pieza. Lanza PiezaNoEncontradaError
    si el id no existe."""
    return _get_pieza(conn, pieza_id)["stock"]


def obtener_pieza(conn: sqlite3.Connection, pieza_id: int) -> dict:
    """Devuelve una pieza completa (id, nombre, referencia, stock,
    stock_minimo, precio_unitario, es_compatible, created_at). Lanza
    PiezaNoEncontradaError si el id no existe. Usado por presupuestador.py
    (hito 7) para leer precio real y es_compatible sin duplicar SQL."""
    return dict(_get_pieza(conn, pieza_id))


def descontar_stock(conn: sqlite3.Connection, pieza_id: int, cantidad: int) -> int:
    """Descuenta `cantidad` unidades del stock de una pieza.

    Rechaza la operación (sin tocar la fila) si `cantidad` no es positiva
    o si supera el stock disponible — nunca deja el stock en negativo.
    Devuelve el stock resultante.

    El UPDATE es atómico (`stock = stock - ?` con `AND stock >= ?` en el
    WHERE, no un SELECT-luego-UPDATE con el valor calculado en Python):
    con varios agentes futuros escribiendo sobre la misma pieza en
    conexiones distintas (WAL + busy_timeout en db.py lo permite), un
    SELECT-luego-UPDATE es una lectura obsoleta clásica — dos
    descuentos concurrentes podrían leer el mismo stock de partida y
    perder una de las dos restas sin que ningún CHECK lo detecte.
    """
    if cantidad <= 0:
        raise ValueError(f"La cantidad a descontar debe ser positiva, se recibió {cantidad}.")

    cur = conn.execute(
        "UPDATE piezas SET stock = stock - ? WHERE id = ? AND stock >= ?",
        (cantidad, pieza_id, cantidad),
    )
    if cur.rowcount == 0:
        conn.rollback()
        pieza = _get_pieza(conn, pieza_id)  # lanza PiezaNoEncontradaError si no existe
        raise StockInsuficienteError(
            f"La pieza {pieza_id} tiene {pieza['stock']} unidades; "
            f"no se pueden descontar {cantidad}."
        )
    conn.commit()
    return _get_pieza(conn, pieza_id)["stock"]


def necesita_reposicion(conn: sqlite3.Connection, pieza_id: int) -> bool:
    """True si el stock actual está en o por debajo de stock_minimo.

    Consulta directamente con el mismo predicado que listar_piezas_bajo_minimo
    (`stock <= stock_minimo`) en vez de traer la fila y comparar en Python,
    para que la regla viva en un único sitio.
    """
    _get_pieza(conn, pieza_id)  # lanza PiezaNoEncontradaError si no existe
    row = conn.execute(
        "SELECT 1 FROM piezas WHERE id = ? AND stock <= stock_minimo", (pieza_id,)
    ).fetchone()
    return row is not None


def listar_piezas_bajo_minimo(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Todas las piezas cuyo stock actual está en o por debajo de su stock_minimo."""
    return conn.execute("SELECT * FROM piezas WHERE stock <= stock_minimo").fetchall()
