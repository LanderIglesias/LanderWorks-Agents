"""Smoke tests contra la API real de Claude Haiku para diagnostico.py.

Mismo gate que test_router_live.py: NO se ejecuta en una corrida normal de
`pytest` -- requiere TALLER_MECANICO_RUN_LIVE_TESTS=1 explícito.

Ejecutar con:
    TALLER_MECANICO_RUN_LIVE_TESTS=1 pytest tests/taller_mecanico/test_diagnostico_live.py -v
"""

import os

import pytest

from backend.agents.taller_mecanico import diagnostico

pytestmark = pytest.mark.skipif(
    os.environ.get("TALLER_MECANICO_RUN_LIVE_TESTS") != "1",
    reason="Test de humo contra la API real -- requiere TALLER_MECANICO_RUN_LIVE_TESTS=1 "
    "y ANTHROPIC_API_KEY válida. No se ejecuta en la corrida normal de tests.",
)


def test_caso_de_aceptacion_del_documento_de_arranque_contra_la_api_real(conn):
    """El caso EXACTO de la sección 8: 'ruido raro al frenar por las
    mañanas' -> pastillas desgastadas o discos con óxido superficial,
    confianza media (falta inspección visual). Es el mismo caso que se
    usará como test de aceptación del hito 6 -- se verifica aquí, contra
    el modelo real, para no descubrir un desajuste más adelante."""
    resultado = diagnostico.diagnosticar(
        conn, "Mi coche hace un ruido raro al frenar por las mañanas"
    )

    causas_en_minuscula = " ".join(resultado["causas_probables"]).lower()
    menciona_pastillas_o_discos = (
        "pastilla" in causas_en_minuscula
        or "disco" in causas_en_minuscula
        or "óxido" in causas_en_minuscula
        or "oxido" in causas_en_minuscula
    )
    assert menciona_pastillas_o_discos, (
        f"Se esperaba pastillas/discos como causa probable, se obtuvo: "
        f"{resultado['causas_probables']}"
    )
    assert resultado["confianza"] == "media", (
        f"Se esperaba confianza='media' (falta inspección visual), "
        f"se obtuvo: {resultado['confianza']!r}. Razonamiento del modelo: "
        f"{resultado['razonamiento']!r}"
    )


def test_diagnostico_con_vehiculo_real_incluye_contexto_en_el_razonamiento(conn):
    from backend.agents.taller_mecanico import crm

    cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
    vehiculo_id = crm.alta_vehiculo(
        conn,
        cliente_id,
        matricula="1234ABC",
        marca="Seat",
        modelo="Ibiza",
        anio=2010,
        kilometraje=180000,
    )
    resultado = diagnostico.diagnosticar(
        conn, "ruido metálico al girar el volante", vehiculo_id=vehiculo_id
    )
    assert resultado["confianza"] in diagnostico.NIVELES_CONFIANZA_VALIDOS
    assert resultado["causas_probables"]
