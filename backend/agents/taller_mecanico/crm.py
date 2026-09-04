"""crm.py — herramienta determinista de clientes y vehículos (hito 2).

CRUD de `clientes`/`vehiculos`. Todo campo sensible de `clientes` pasa
por crypto_utils.py antes de tocar la BD — este es el único módulo que
debe construir filas de `clientes`; ningún otro módulo (agenda,
inventario, ni los agentes de hitos 3+) debe cifrar/descifrar por su
cuenta.

Sin razonamiento de IA — funciones aisladas para que los agentes de los
hitos 3+ las invoquen como herramienta.
"""

from __future__ import annotations

import sqlite3

from . import crypto_utils


class ClienteNoEncontradoError(LookupError):
    """No existe ningún cliente con el id dado."""


class VehiculoNoEncontradoError(LookupError):
    """No existe ningún vehículo con el id dado."""


class ClienteDuplicadoError(ValueError):
    """Ya existe un cliente con ese mismo teléfono (detectado vía telefono_hash)."""


class QuejaNoEncontradaError(LookupError):
    """No existe ninguna queja con el id dado."""


def alta_cliente(
    conn: sqlite3.Connection,
    nombre: str,
    telefono: str,
    email: str | None = None,
    direccion: str | None = None,
) -> int:
    """Da de alta un cliente nuevo. Cifra nombre/telefono/email/direccion
    con crypto_utils antes de insertar. Rechaza el alta si `telefono` ya
    pertenece a otro cliente.

    `telefono` se normaliza (strip) una única vez aquí, antes de cifrar Y
    de hashear — si no, `encrypt(" 600111222")` y `hash_for_lookup("600111222")`
    (que sí normaliza internamente) describirían el mismo cliente con un
    teléfono descifrado distinto del que se usó para buscarlo.

    La comprobación por telefono_hash (determinista) es solo la vía
    rápida y sin decrypt: la garantía real es el UNIQUE de la BD sobre
    telefono_hash. Bajo dos altas concurrentes con el mismo teléfono
    (dos agentes/procesos distintos), ambas podrían pasar la
    comprobación antes de que ninguna haya insertado — por eso el
    INSERT también se protege con try/except sobre el IntegrityError
    del UNIQUE, para que ClienteDuplicadoError sea el resultado en
    los dos órdenes posibles, no solo en el más común."""
    telefono = telefono.strip()
    telefono_hash = crypto_utils.hash_for_lookup(telefono)

    # SELECT id, no el teléfono: el mensaje de ClienteDuplicadoError puede
    # acabar persistido por un agente futuro en decision_log.output o
    # .verdict_reason (texto libre, sin cifrar) — la excepción no debe ser
    # ella misma una vía de fuga de PII. El id ya es suficiente para que
    # el llamante actúe (p.ej. seguir con el cliente existente).
    existente = conn.execute(
        "SELECT id FROM clientes WHERE telefono_hash = ?", (telefono_hash,)
    ).fetchone()
    if existente is not None:
        raise ClienteDuplicadoError(
            f"Ya existe un cliente (id={existente['id']}) con ese mismo teléfono."
        )

    try:
        cur = conn.execute(
            "INSERT INTO clientes "
            "(nombre_encrypted, telefono_encrypted, telefono_hash, email_encrypted, direccion_encrypted) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                crypto_utils.encrypt(nombre),
                crypto_utils.encrypt(telefono),
                telefono_hash,
                crypto_utils.encrypt(email) if email is not None else None,
                crypto_utils.encrypt(direccion) if direccion is not None else None,
            ),
        )
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "telefono_hash" in str(exc):
            raise ClienteDuplicadoError(
                "Ya existe un cliente con ese mismo teléfono (detectado al insertar)."
            ) from exc
        raise
    conn.commit()
    assert cur.lastrowid is not None  # siempre hay id tras un INSERT que no lanzó
    return cur.lastrowid


def _row_to_cliente(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "nombre": crypto_utils.decrypt(row["nombre_encrypted"]),
        "telefono": crypto_utils.decrypt(row["telefono_encrypted"]),
        "email": crypto_utils.decrypt(row["email_encrypted"]) if row["email_encrypted"] else None,
        "direccion": (
            crypto_utils.decrypt(row["direccion_encrypted"]) if row["direccion_encrypted"] else None
        ),
        "created_at": row["created_at"],
    }


def obtener_cliente(conn: sqlite3.Connection, cliente_id: int) -> dict:
    """Devuelve un cliente con sus campos ya descifrados. Lanza
    ClienteNoEncontradoError si el id no existe."""
    row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if row is None:
        raise ClienteNoEncontradoError(f"No existe el cliente {cliente_id}.")
    return _row_to_cliente(row)


def buscar_cliente_por_telefono(conn: sqlite3.Connection, telefono: str) -> dict | None:
    """Busca un cliente por teléfono vía telefono_hash (determinista).
    Devuelve None si no existe ninguno — nunca lanza por "no encontrado",
    ya que "no existe todavía" es un resultado válido de una búsqueda."""
    telefono_hash = crypto_utils.hash_for_lookup(telefono.strip())
    row = conn.execute(
        "SELECT * FROM clientes WHERE telefono_hash = ?", (telefono_hash,)
    ).fetchone()
    return _row_to_cliente(row) if row is not None else None


def alta_vehiculo(
    conn: sqlite3.Connection,
    cliente_id: int,
    matricula: str,
    marca: str,
    modelo: str,
    anio: int | None = None,
    kilometraje: int = 0,
) -> int:
    """Vincula un vehículo nuevo a un cliente existente. Lanza
    sqlite3.IntegrityError si cliente_id no existe o matricula ya está
    en uso — esas validaciones ya las hace el FK/UNIQUE del esquema."""
    try:
        cur = conn.execute(
            "INSERT INTO vehiculos (cliente_id, matricula, marca, modelo, anio, kilometraje) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cliente_id, matricula, marca, modelo, anio, kilometraje),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise
    assert cur.lastrowid is not None  # siempre hay id tras un INSERT que no lanzó
    return cur.lastrowid


def obtener_vehiculo(conn: sqlite3.Connection, vehiculo_id: int) -> dict:
    """Devuelve un vehículo (id, cliente_id, matricula, marca, modelo,
    anio, kilometraje, created_at). Lanza VehiculoNoEncontradoError si el
    id no existe. Sin PII propia que descifrar (a diferencia de
    obtener_cliente) — matricula no está cifrada, ver README_taller_mecanico.md,
    sección "Deuda técnica conocida y aceptada"."""
    row = conn.execute("SELECT * FROM vehiculos WHERE id = ?", (vehiculo_id,)).fetchone()
    if row is None:
        raise VehiculoNoEncontradoError(f"No existe el vehículo {vehiculo_id}.")
    return dict(row)


def historial_vehiculo(conn: sqlite3.Connection, vehiculo_id: int) -> list[sqlite3.Row]:
    """Citas pasadas y presentes de un vehículo, más recientes primero.
    Devuelve lista vacía si el vehículo existe pero no tiene citas —
    lanza VehiculoNoEncontradoError solo si el vehículo en sí no existe."""
    existe = conn.execute("SELECT 1 FROM vehiculos WHERE id = ?", (vehiculo_id,)).fetchone()
    if existe is None:
        raise VehiculoNoEncontradoError(f"No existe el vehículo {vehiculo_id}.")

    return conn.execute(
        "SELECT * FROM citas WHERE vehiculo_id = ? ORDER BY fecha_hora DESC", (vehiculo_id,)
    ).fetchall()


def contar_visitas_completadas_cliente(conn: sqlite3.Connection, cliente_id: int) -> int:
    """Número de citas en estado 'completada', sumadas sobre TODOS los
    vehículos del cliente (no solo uno) — la fidelidad es del cliente,
    no de un vehículo concreto. Usado por presupuestador.py (hito 7) para
    los umbrales de descuento estándar/excepcional. Lanza
    ClienteNoEncontradoError si el cliente no existe."""
    existe = conn.execute("SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if existe is None:
        raise ClienteNoEncontradoError(f"No existe el cliente {cliente_id}.")

    row = conn.execute(
        "SELECT COUNT(*) AS n FROM citas "
        "JOIN vehiculos ON vehiculos.id = citas.vehiculo_id "
        "WHERE vehiculos.cliente_id = ? AND citas.estado = 'completada'",
        (cliente_id,),
    ).fetchone()
    return row["n"]


def registrar_queja(
    conn: sqlite3.Connection, cliente_id: int, descripcion: str, vehiculo_id: int | None = None
) -> int:
    """Registra una queja de un cliente (opcionalmente vinculada a un
    vehículo concreto), sin resolver por defecto. Lanza
    sqlite3.IntegrityError si cliente_id (o vehiculo_id, si se pasa) no
    existe."""
    try:
        cur = conn.execute(
            "INSERT INTO quejas (cliente_id, vehiculo_id, descripcion) VALUES (?, ?, ?)",
            (cliente_id, vehiculo_id, descripcion),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise
    assert cur.lastrowid is not None  # siempre hay id tras un INSERT que no lanzó
    return cur.lastrowid


def tiene_queja_no_resuelta(conn: sqlite3.Connection, cliente_id: int) -> bool:
    """True si el cliente tiene al menos una queja con resuelta=0.
    Usado por presupuestador.py (hito 7) para verificar el criterio
    objetivo "queja no resuelta" de un descuento excepcional contra datos
    reales, no contra lo que el modelo afirme. Lanza
    ClienteNoEncontradoError si el cliente no existe."""
    existe = conn.execute("SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if existe is None:
        raise ClienteNoEncontradoError(f"No existe el cliente {cliente_id}.")

    row = conn.execute(
        "SELECT 1 FROM quejas WHERE cliente_id = ? AND resuelta = 0", (cliente_id,)
    ).fetchone()
    return row is not None


def resolver_queja(conn: sqlite3.Connection, queja_id: int) -> None:
    """Marca una queja como resuelta (resuelta=1). Sin esto, una queja
    registrada satisfacía el criterio excepcional "queja_no_resuelta" de
    presupuestador.py para siempre, sin ningún mecanismo para cerrarla
    (hallazgo de la revisión de seguridad del hito 7). Lanza
    QuejaNoEncontradaError si el id no existe."""
    cur = conn.execute("UPDATE quejas SET resuelta = 1 WHERE id = ?", (queja_id,))
    if cur.rowcount == 0:
        conn.rollback()
        raise QuejaNoEncontradaError(f"No existe la queja {queja_id}.")
    conn.commit()
