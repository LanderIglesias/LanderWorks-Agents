"""agenda.py — herramienta determinista de citas (hito 2).

CRUD de `citas` con una única regla de negocio real: dos citas del MISMO
vehículo no pueden solaparse en el tiempo. El solapamiento se calcula por
vehículo, no por capacidad global del taller (el esquema no modela
bahías/mecánicos como recurso limitado; ver README_taller_mecanico.md,
sección "Decisiones de negocio tomadas en el hito 2").

Sin razonamiento de IA — estas funciones son las que los agentes de los
hitos 3+ invocarán como herramienta, así que cada función pública es
invocable de forma aislada, sin estado oculto entre llamadas (el único
estado es el que ya vive en la fila de `citas` en SQLite).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

_ESTADOS_QUE_BLOQUEAN_HUECO = ("pendiente", "confirmada", "completada")
_ESTADOS_PLACEHOLDER = ",".join("?" * len(_ESTADOS_QUE_BLOQUEAN_HUECO))
_FORMATOS_FECHA_HORA = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")
_MAX_DURACION_MINUTOS_RAZONABLE = 24 * 60


class CitaNoEncontradaError(LookupError):
    """No existe ninguna cita con el id dado."""


class SolapamientoError(ValueError):
    """La franja solicitada se solapa con otra cita activa del mismo vehículo."""


class FechaHoraInvalidaError(ValueError):
    """fecha_hora no tiene ninguno de los formatos aceptados."""


class EstadoCitaInvalidoError(ValueError):
    """La operación no es válida para el estado actual de la cita
    (p.ej. reprogramar una cita cancelada o completada)."""


def _parse(fecha_hora: str) -> datetime:
    for formato in _FORMATOS_FECHA_HORA:
        try:
            return datetime.strptime(fecha_hora, formato)
        except ValueError:
            continue
    raise FechaHoraInvalidaError(
        f"'{fecha_hora}' no coincide con ninguno de los formatos aceptados: "
        f"{', '.join(_FORMATOS_FECHA_HORA)}."
    )


def _rango(fecha_hora: str, duracion_minutos: int) -> tuple[datetime, datetime]:
    inicio = _parse(fecha_hora)
    return inicio, inicio + timedelta(minutes=duracion_minutos)


def _hay_solapamiento(
    conn: sqlite3.Connection,
    vehiculo_id: int,
    fecha_hora: str,
    duracion_minutos: int,
    excluir_cita_id: int | None = None,
) -> bool:
    inicio_nueva, fin_nueva = _rango(fecha_hora, duracion_minutos)

    # Acota la búsqueda a una ventana alrededor de la franja nueva (en vez
    # de traer TODO el historial del vehículo) para que ix_citas_fecha_hora
    # se pueda usar; el margen cubre la duración máxima razonable de una
    # cita existente que aún podría solapar por el lado izquierdo.
    ventana_inicio = (inicio_nueva - timedelta(minutes=_MAX_DURACION_MINUTOS_RAZONABLE)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    ventana_fin = fin_nueva.strftime("%Y-%m-%d %H:%M:%S")

    query = (
        "SELECT fecha_hora, duracion_minutos FROM citas "
        f"WHERE vehiculo_id = ? AND estado IN ({_ESTADOS_PLACEHOLDER}) "
        "AND fecha_hora >= ? AND fecha_hora < ?"
    )
    params: list = [vehiculo_id, *_ESTADOS_QUE_BLOQUEAN_HUECO, ventana_inicio, ventana_fin]
    if excluir_cita_id is not None:
        query += " AND id != ?"
        params.append(excluir_cita_id)

    for row in conn.execute(query, params).fetchall():
        inicio_existente, fin_existente = _rango(row["fecha_hora"], row["duracion_minutos"])
        # Dos intervalos [a, b) y [c, d) se solapan si a < d y c < b.
        if inicio_nueva < fin_existente and inicio_existente < fin_nueva:
            return True
    return False


def esta_disponible(
    conn: sqlite3.Connection, vehiculo_id: int, fecha_hora: str, duracion_minutos: int = 60
) -> bool:
    """True si el vehículo no tiene ninguna cita activa que se solape con esta franja."""
    return not _hay_solapamiento(conn, vehiculo_id, fecha_hora, duracion_minutos)


def crear_cita(
    conn: sqlite3.Connection,
    vehiculo_id: int,
    fecha_hora: str,
    motivo: str,
    duracion_minutos: int = 60,
) -> int:
    """Crea una cita. Lanza SolapamientoError si el hueco ya está ocupado
    por otra cita activa del mismo vehículo. Lanza sqlite3.IntegrityError
    si vehiculo_id no existe (FK) — esa validación ya la hace la BD.

    Comprobación + inserción ocurren dentro de una única transacción
    `BEGIN IMMEDIATE`: con varios agentes futuros escribiendo desde
    conexiones distintas (WAL + busy_timeout en db.py lo permite), un
    SELECT de comprobación fuera de transacción e INSERT por separado
    dejaría una ventana donde dos llamadas concurrentes podrían leer
    "hueco libre" antes de que ninguna de las dos haya insertado — y
    terminar con dos citas solapadas pese a esta comprobación.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        if _hay_solapamiento(conn, vehiculo_id, fecha_hora, duracion_minutos):
            raise SolapamientoError(
                f"El vehículo {vehiculo_id} ya tiene una cita activa que se solapa con "
                f"{fecha_hora} ({duracion_minutos} min)."
            )
        cur = conn.execute(
            "INSERT INTO citas (vehiculo_id, fecha_hora, motivo, duracion_minutos) VALUES (?, ?, ?, ?)",
            (vehiculo_id, fecha_hora, motivo, duracion_minutos),
        )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    assert cur.lastrowid is not None  # siempre hay id tras un INSERT que no lanzó
    return cur.lastrowid


def _get_cita(conn: sqlite3.Connection, cita_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM citas WHERE id = ?", (cita_id,)).fetchone()
    if row is None:
        raise CitaNoEncontradaError(f"No existe la cita {cita_id}.")
    return row


def reprogramar_cita(
    conn: sqlite3.Connection,
    cita_id: int,
    nueva_fecha_hora: str,
    nueva_duracion_minutos: int | None = None,
) -> None:
    """Cambia fecha_hora (y opcionalmente duracion_minutos) de una cita
    existente. Rechaza el cambio si la nueva franja se solapa con OTRA
    cita activa del mismo vehículo (la propia cita se excluye de la
    comprobación). Lanza EstadoCitaInvalidoError si la cita ya está
    'cancelada' o 'completada' — reprogramar esos estados falsificaría
    el historial que crm.historial_vehiculo devuelve a los agentes
    futuros."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        cita = _get_cita(conn, cita_id)
        if cita["estado"] not in ("pendiente", "confirmada"):
            raise EstadoCitaInvalidoError(
                f"No se puede reprogramar la cita {cita_id}: está en estado '{cita['estado']}'."
            )
        duracion = (
            nueva_duracion_minutos
            if nueva_duracion_minutos is not None
            else cita["duracion_minutos"]
        )
        if _hay_solapamiento(
            conn, cita["vehiculo_id"], nueva_fecha_hora, duracion, excluir_cita_id=cita_id
        ):
            raise SolapamientoError(
                f"No se puede reprogramar la cita {cita_id} a {nueva_fecha_hora}: "
                "se solapa con otra cita activa del mismo vehículo."
            )
        conn.execute(
            "UPDATE citas SET fecha_hora = ?, duracion_minutos = ? WHERE id = ?",
            (nueva_fecha_hora, duracion, cita_id),
        )
    except Exception:
        conn.rollback()
        raise
    conn.commit()


def cancelar_cita(conn: sqlite3.Connection, cita_id: int) -> None:
    """Marca la cita como 'cancelada', liberando su hueco para otras citas."""
    try:
        _get_cita(conn, cita_id)
        conn.execute("UPDATE citas SET estado = 'cancelada' WHERE id = ?", (cita_id,))
    except Exception:
        conn.rollback()
        raise
    conn.commit()
