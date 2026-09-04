"""Smoke test contra la API real de Claude Haiku.

NO se ejecuta en una corrida normal de `pytest` -- se salta salvo que se
defina explícitamente TALLER_MECANICO_RUN_LIVE_TESTS=1, para no depender
de red/ANTHROPIC_API_KEY ni gastar tokens en cada `pytest`. Deliberadamente
NO se registró como marcador de pytest (evita tocar el pytest.ini
compartido de la raíz del monorepo, que afecta a todos los demás agentes)
-- el gate vive aquí, en un skipif sobre una variable de entorno.

Ejecutar explícitamente con:
    TALLER_MECANICO_RUN_LIVE_TESTS=1 pytest tests/taller_mecanico/test_router_live.py -v
"""

import os

import pytest

from backend.agents.taller_mecanico import db as tm_db
from backend.agents.taller_mecanico import router

pytestmark = pytest.mark.skipif(
    os.environ.get("TALLER_MECANICO_RUN_LIVE_TESTS") != "1",
    reason="Test de humo contra la API real -- requiere TALLER_MECANICO_RUN_LIVE_TESTS=1 "
    "y ANTHROPIC_API_KEY válida. No se ejecuta en la corrida normal de tests.",
)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db_path = tmp_path / "taller_mecanico.db"
    monkeypatch.setattr(tm_db, "DB_PATH", db_path)
    connection = tm_db.get_conn()
    yield connection
    connection.close()


def test_clasificacion_real_de_una_consulta_tecnica(conn):
    resultado = router.clasificar_mensaje(
        conn, "Mi coche hace un ruido raro al frenar por las mañanas"
    )
    assert resultado["intencion"] in router.INTENCIONES_VALIDAS
    assert resultado["agente_destino"] in router.AGENTES_DESTINO_VALIDOS
    assert resultado["razonamiento"]

    row = conn.execute(
        "SELECT * FROM decision_log WHERE id = ?", (resultado["decision_id"],)
    ).fetchone()
    assert row["agent"] == "router"


def test_clasificacion_real_de_una_peticion_de_cita(conn):
    resultado = router.clasificar_mensaje(conn, "Quiero pedir cita para el jueves por la tarde")
    assert resultado["intencion"] in router.INTENCIONES_VALIDAS
