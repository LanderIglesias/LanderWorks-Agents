"""db.py — Esquema SQLite y conexión del agente Taller Mecánico.

Hito 1: clientes, vehiculos, citas, piezas, presupuestos, decision_log.
Hito 7 (Presupuestador): presupuesto_piezas (línea de partida por
presupuesto, anticipada desde el hito 1) y quejas (nueva, necesaria para
verificar "queja no resuelta" contra datos reales); piezas.es_compatible
añadido a la tabla existente. Ver taller-multiagente-arranque.md (en
esta misma carpeta) para el orden de construcción completo.
"""

from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "taller_mecanico.db"

SCHEMA = """
-- PII cifrada en la capa de aplicación (ver crypto_utils.py), nunca en
-- claro en esta tabla. telefono_hash es un HMAC-SHA256 determinista
-- (clave separada de la de Fernet) — permite UNIQUE/búsqueda por
-- igualdad sin poder invertirse; telefono_encrypted (Fernet, no
-- determinista) NO puede llevar el UNIQUE porque el mismo teléfono
-- cifra distinto cada vez.
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY,
    nombre_encrypted TEXT NOT NULL,
    telefono_encrypted TEXT NOT NULL,
    telefono_hash TEXT NOT NULL UNIQUE,
    email_encrypted TEXT,
    direccion_encrypted TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vehiculos (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    matricula TEXT NOT NULL UNIQUE,
    marca TEXT NOT NULL,
    modelo TEXT NOT NULL,
    anio INTEGER,
    kilometraje INTEGER NOT NULL DEFAULT 0 CHECK (kilometraje >= 0),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_vehiculos_cliente_id ON vehiculos(cliente_id);

CREATE TABLE IF NOT EXISTS citas (
    id INTEGER PRIMARY KEY,
    vehiculo_id INTEGER NOT NULL REFERENCES vehiculos(id),
    fecha_hora DATETIME NOT NULL,
    duracion_minutos INTEGER NOT NULL DEFAULT 60 CHECK (duracion_minutos > 0),
    motivo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'confirmada', 'cancelada', 'completada')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_citas_vehiculo_id ON citas(vehiculo_id);
CREATE INDEX IF NOT EXISTS ix_citas_fecha_hora ON citas(fecha_hora);

CREATE TABLE IF NOT EXISTS piezas (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    referencia TEXT UNIQUE,
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    stock_minimo INTEGER NOT NULL DEFAULT 0 CHECK (stock_minimo >= 0),
    precio_unitario NUMERIC NOT NULL CHECK (precio_unitario >= 0),
    -- 0 = pieza original, 1 = compatible/aftermarket. Es un hecho del
    -- catálogo (hito 7, Presupuestador) — la elección real de original
    -- vs. compatible en un presupuesto concreto se registra por separado
    -- en presupuesto_piezas.es_compatible.
    es_compatible INTEGER NOT NULL DEFAULT 0 CHECK (es_compatible IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS presupuestos (
    id INTEGER PRIMARY KEY,
    cita_id INTEGER NOT NULL REFERENCES citas(id),
    estado TEXT NOT NULL DEFAULT 'borrador'
        CHECK (estado IN ('borrador', 'aprobado', 'rechazado', 'enviado')),
    total NUMERIC NOT NULL DEFAULT 0 CHECK (total >= 0),
    pdf_path TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_presupuestos_cita_id ON presupuestos(cita_id);

-- Línea de partida por presupuesto -- anticipada en el hito 1 ("pendiente
-- para el hito 7, cuando el Presupuestador exista y necesite esa relación
-- de verdad"). es_compatible aquí es la elección REGISTRADA para este
-- presupuesto concreto (puede diferir de piezas.es_compatible si en el
-- futuro se permite forzar una excepción justificada).
CREATE TABLE IF NOT EXISTS presupuesto_piezas (
    id INTEGER PRIMARY KEY,
    presupuesto_id INTEGER NOT NULL REFERENCES presupuestos(id),
    pieza_id INTEGER NOT NULL REFERENCES piezas(id),
    cantidad INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario_aplicado NUMERIC NOT NULL CHECK (precio_unitario_aplicado >= 0),
    es_compatible INTEGER NOT NULL DEFAULT 0 CHECK (es_compatible IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_presupuesto_piezas_presupuesto_id ON presupuesto_piezas(presupuesto_id);
CREATE INDEX IF NOT EXISTS ix_presupuesto_piezas_pieza_id ON presupuesto_piezas(pieza_id);

-- Nueva en el hito 7: no existía ninguna forma de verificar "queja no
-- resuelta vinculada al cliente/vehículo" contra datos reales (uno de
-- los 4 criterios objetivos de descuento excepcional del Presupuestador)
-- -- decision_log no tiene cliente_id/vehiculo_id, y citas.motivo es
-- texto libre no categorizado como queja. Tabla mínima dedicada, en vez
-- de inferir "queja" de texto libre con regex (frágil, no verificable de
-- verdad contra datos reales como exige la regla de negocio).
CREATE TABLE IF NOT EXISTS quejas (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    vehiculo_id INTEGER REFERENCES vehiculos(id),
    descripcion TEXT NOT NULL,
    resuelta INTEGER NOT NULL DEFAULT 0 CHECK (resuelta IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_quejas_cliente_id ON quejas(cliente_id);

CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    input_text TEXT NOT NULL,
    agent TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    output TEXT NOT NULL,
    reviewed_by TEXT,
    verdict TEXT,
    verdict_reason TEXT,
    parent_decision_id INTEGER REFERENCES decision_log(id),
    -- Observabilidad Langfuse (opcional, ver langfuse_utils.py): cruzar
    -- una fila con su traza/observación en Langfuse sin duplicar el
    -- input/output ya guardado arriba en dos sitios. NULL si Langfuse no
    -- estaba configurado (o falló) en el momento de esta decisión -- el
    -- flujo de negocio nunca depende de que estas columnas tengan valor.
    langfuse_trace_id TEXT,
    langfuse_observation_id TEXT
);

CREATE INDEX IF NOT EXISTS ix_decision_log_agent ON decision_log(agent);
CREATE INDEX IF NOT EXISTS ix_decision_log_parent_decision_id ON decision_log(parent_decision_id);
"""

# Migración idempotente para una base de datos ya creada ANTES de que
# estas dos columnas existieran -- CREATE TABLE IF NOT EXISTS (arriba) no
# las añadiría a una tabla decision_log preexistente. Mismo principio que
# la deuda técnica ya documentada en README_taller_mecanico.md ("sin
# migración automática del esquema del hito 1"): esto es deliberadamente
# mínimo (ADD COLUMN, no un framework de migraciones), suficiente porque
# ambas columnas son NULLABLE y no rompen ninguna fila existente.
#
# El índice sobre langfuse_trace_id se crea DESPUÉS de este ALTER (no
# dentro del SCHEMA de arriba): en una BD legacy, decision_log ya existe
# (CREATE TABLE IF NOT EXISTS no la toca) y CREATE INDEX sobre una
# columna que todavía no existe fallaría con "no such column" antes de
# que el ALTER de abajo tuviera ocasión de añadirla.
_ALTER_DECISION_LOG_LANGFUSE = (
    "ALTER TABLE decision_log ADD COLUMN langfuse_trace_id TEXT",
    "ALTER TABLE decision_log ADD COLUMN langfuse_observation_id TEXT",
)


def init_db(conn: sqlite3.Connection) -> None:
    """Crea las 6 tablas (si no existen) sobre una conexión ya abierta."""
    conn.executescript(SCHEMA)
    for statement in _ALTER_DECISION_LOG_LANGFUSE:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass  # la columna ya existe (BD creada con el esquema nuevo)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_decision_log_langfuse_trace_id ON decision_log(langfuse_trace_id)"
    )
    conn.commit()


def _harden_permissions() -> None:
    """Restringe data/ y el .db a solo-propietario (0700 / 0600).

    Efectivo en Linux/macOS (el objetivo real de despliegue, según
    taller-multiagente-arranque.md §6: "montable desde casa"). En Windows,
    chmod no lanza OSError pero tampoco restringe nada más allá del bit
    de solo-lectura — el aislamiento ahí depende de las ACL de NTFS, no
    de esta llamada. Se re-aplica en CADA conexión (no solo al crear el
    archivo) para autorepararse si el .db llega de una copia/backup con
    permisos abiertos.
    """
    try:
        DB_PATH.parent.chmod(stat.S_IRWXU)
    except OSError:
        pass
    try:
        DB_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def get_conn(*, check_same_thread: bool = True) -> sqlite3.Connection:
    """Abre la conexión SQLite, activa foreign keys y asegura el esquema.

    `check_same_thread=False`: pensado para el wrapper HTTP (hito 5), en
    el que una conexión-por-petición puede tener su apertura (antes del
    `yield`) y su cierre (después) despachados por FastAPI/anyio a dos
    hilos DISTINTOS del threadpool -- confirmado con una prueba de 100
    peticiones concurrentes contra `/decisiones`, que sin este flag
    fallan con `sqlite3.ProgrammingError`. Es seguro porque cada
    conexión la sigue usando un único "dueño" lógico (la petición HTTP)
    de forma secuencial, nunca dos hilos a la vez sobre la misma
    conexión -- `check_same_thread=False` solo desactiva la comprobación
    de SQLite, no introduce concurrencia real. El resto de la librería
    (tests, uso directo) mantiene el valor por defecto `True`.

    PRAGMA foreign_keys se activa aquí porque SQLite lo desactiva por
    defecto en cada nueva conexión (a diferencia de Postgres) — sin esto,
    los FK REFERENCES del esquema no se harían cumplir nunca.

    journal_mode=WAL: el esquema está pensado para que varios agentes
    (router/diagnóstico/evaluador/presupuestador, hitos futuros) lean y
    escriban desde procesos/conexiones distintas; WAL permite lectores
    concurrentes con un escritor, a diferencia del rollback-journal por
    defecto que serializa incluso lecturas. busy_timeout se deja
    explícito en el mismo valor que ya usa `sqlite3.connect()` por
    defecto (5000ms) para que quede documentado y no dependa de un valor
    implícito de la librería si algún día cambia.

    Orden importante: el chmod se aplica ANTES de activar WAL. SQLite
    deriva los permisos de los ficheros -wal/-shm de los del .db principal
    en el momento en que los crea — si WAL se activara primero, esos
    sidecars quedarían con los permisos por defecto (0644) y nunca se
    corrigen, aunque el .db principal sí esté en 0600.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row

    _harden_permissions()

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    init_db(conn)

    return conn
