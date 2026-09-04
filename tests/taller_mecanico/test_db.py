"""Tests de `db.get_conn()` -- en particular, del mecanismo real detrás
del hallazgo CRÍTICO de la revisión de código del hito 5 del Hub
Personal de Agentes (`check_same_thread`).

Estas pruebas son DETERMINISTAS a propósito, a diferencia de las
pruebas de concurrencia vía HTTP en `test_api.py`: se descubrió que
esas dependen de cómo el planificador de hilos de anyio reparte el
trabajo en un momento dado -- reproducible de forma fiable (100/100)
contra el servidor real con una BD ya poblada, pero NO siempre contra
una BD de test pequeña y sin carga, donde el mismo hilo puede terminar
sirviendo tanto la apertura como el cierre de la conexión por pura
coincidencia de scheduling, incluso con el bug presente. Las pruebas de
aquí no dependen de esa suerte: fuerzan el cruce de hilos a mano con
`threading.Thread`."""

from __future__ import annotations

import sqlite3
import threading

from backend.agents.taller_mecanico import db


def _usar_conexion_desde_otro_hilo(conn: sqlite3.Connection) -> dict:
    resultado: dict = {}

    def _tarea() -> None:
        try:
            conn.execute("SELECT 1")
            resultado["ok"] = True
        except sqlite3.ProgrammingError as exc:
            resultado["error"] = str(exc)

    hilo = threading.Thread(target=_tarea)
    hilo.start()
    hilo.join()
    return resultado


def test_check_same_thread_false_permite_usar_la_conexion_desde_otro_hilo(tmp_path, monkeypatch):
    """Mecanismo real que arregla el hallazgo CRÍTICO: una conexión
    abierta con `check_same_thread=False` debe poder usarse desde un
    hilo distinto al que la creó, sin `sqlite3.ProgrammingError` --
    exactamente lo que necesita `api.get_db()`, cuya apertura y cierre
    pueden caer en hilos distintos del threadpool de FastAPI/anyio."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "det_false.db")
    conn = db.get_conn(check_same_thread=False)
    try:
        resultado = _usar_conexion_desde_otro_hilo(conn)
    finally:
        conn.close()
    assert resultado.get("ok") is True, resultado.get("error")


def test_check_same_thread_true_por_defecto_bloquea_uso_desde_otro_hilo(tmp_path, monkeypatch):
    """Contraprueba: sin el flag (el valor por defecto, que sigue usando
    el resto de la librería y del resto de la suite de tests), SQLite sí
    bloquea el uso cross-hilo -- confirma que la prueba de arriba
    verifica algo real, no un `check_same_thread` que ya no tuviera
    ningún efecto en esta versión de Python/sqlite3."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "det_true.db")
    conn = db.get_conn()
    try:
        resultado = _usar_conexion_desde_otro_hilo(conn)
    finally:
        conn.close()
    assert "error" in resultado
    assert "same thread" in resultado["error"].lower()


def test_get_conn_sigue_activando_wal_y_busy_timeout_con_check_same_thread_false(
    tmp_path, monkeypatch
):
    """El fix del hallazgo CRÍTICO vive en el `db.get_conn()` COMPARTIDO,
    no en una conexión paralela propia del wrapper -- por diseño, las
    mismas PRAGMA journal_mode=WAL / busy_timeout que ya protegen contra
    escritores concurrentes desde el hito 1 del propio taller_mecanico
    se aplican sin condicionar a `check_same_thread`, así que no hace
    falta (ni existe) una segunda capa de protecciones que replicar."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "det_pragmas.db")
    conn = db.get_conn(check_same_thread=False)
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    finally:
        conn.close()
    assert journal_mode.lower() == "wal"
    assert busy_timeout == 5000
