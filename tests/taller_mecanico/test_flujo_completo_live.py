"""Smoke tests contra la API real para flujo_completo.py (hito 8, ÚLTIMO HITO).

Los cinco pasos (Router, Diagnóstico, Evaluador, Presupuestador,
Evaluador) hacen llamadas REALES a Claude Haiku, encadenados de verdad —
esta es la verificación definitiva del patrón completo del documento de
arranque, de principio a fin. Mismo gate que los demás tests de humo:
TALLER_MECANICO_RUN_LIVE_TESTS=1.

Único mock usado: Diagnóstico en el caso de rechazo, EXACTAMENTE la
misma decisión tomada en el hito 6 (test_flujo_diagnostico_live.py) tras
investigar que un Diagnóstico real, al ver también el kilometraje real
vía crm.py, calibra bien su propia confianza y evita el error que ese
caso necesita para poder probar la reacción del Evaluador de forma
reproducible -- ver README, sección "Flujo Diagnóstico (orquestación)".

Ejecutar con:
    TALLER_MECANICO_RUN_LIVE_TESTS=1 pytest tests/taller_mecanico/test_flujo_completo_live.py -v
"""

import os

import pytest

from backend.agents.taller_mecanico import crm, flujo_completo, inventario
from tests.taller_mecanico.conftest import client_con_json

pytestmark = pytest.mark.skipif(
    os.environ.get("TALLER_MECANICO_RUN_LIVE_TESTS") != "1",
    reason="Test de humo contra la API real -- requiere TALLER_MECANICO_RUN_LIVE_TESTS=1 "
    "y ANTHROPIC_API_KEY válida. No se ejecuta en la corrida normal de tests.",
)


def _escenario(conn, telefono: str, matricula: str, kilometraje: int):
    cliente_id = crm.alta_cliente(conn, nombre="Cliente de prueba", telefono=telefono)
    vehiculo_id = crm.alta_vehiculo(
        conn, cliente_id, matricula=matricula, marca="Seat", modelo="Ibiza", kilometraje=kilometraje
    )
    pieza_id = inventario.alta_pieza(
        conn, "Pastillas Bosch", precio_unitario=40.0, stock_inicial=10
    )
    return cliente_id, vehiculo_id, pieza_id


def test_caso_de_aceptacion_completo_del_documento_de_arranque(conn):
    """El test de aceptación COMPLETO, de principio a fin, SIN mocks:
    'ruido raro al frenar por las mañanas' -> Router deriva a Diagnóstico
    -> aprobado con advertencia -> cita creada -> Presupuestador genera
    presupuesto -> Evaluador aprueba."""
    cliente_id, vehiculo_id, pieza_id = _escenario(conn, "600111250", "1111FIN", kilometraje=80000)

    resultado = flujo_completo.procesar_flujo_completo(
        conn,
        mensaje="Mi coche hace un ruido raro al frenar por las mañanas",
        cliente_id=cliente_id,
        vehiculo_id=vehiculo_id,
        fecha_hora_cita="2026-09-01 10:00",
        piezas_candidatas=[pieza_id],
        horas_mano_obra=1.0,
    )

    assert resultado["router"]["intencion"] == "consulta_tecnica"
    assert resultado["evaluador_diagnostico"]["veredicto"] == "aprobado", (
        f"Diagnóstico no aprobado. Razonamiento: "
        f"{resultado['evaluador_diagnostico']['razonamiento']!r}"
    )
    assert resultado["cita_id"] is not None
    assert resultado["resultado_final"] == "aprobado", (
        f"Se esperaba 'aprobado' de extremo a extremo, se obtuvo "
        f"{resultado['resultado_final']!r}. Razonamiento del Evaluador del presupuesto: "
        f"{resultado['evaluador_presupuesto']['razonamiento']!r}"
    )

    # Cadena de parent_decision_id de extremo a extremo, con datos reales:
    # router(NULL) <- diagnostico <- evaluador_diagnostico <- presupuestador <- evaluador_presupuesto.
    ids = [
        resultado["router"]["decision_id"],
        resultado["diagnostico"]["decision_id"],
        resultado["evaluador_diagnostico"]["decision_id"],
        resultado["presupuestador"]["decision_id"],
        resultado["evaluador_presupuesto"]["decision_id"],
    ]
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM decision_log ORDER BY id").fetchall()}
    assert len(rows) == 5
    assert rows[ids[0]]["parent_decision_id"] is None
    for hijo, padre in zip(ids[1:], ids[:-1], strict=True):
        assert rows[hijo]["parent_decision_id"] == padre, (
            f"Fila {hijo} (agent={rows[hijo]['agent']}) debería encadenar con {padre}, "
            f"pero tiene parent_decision_id={rows[hijo]['parent_decision_id']}"
        )

    # El presupuesto real quedó aprobado en la tabla real, no solo en el
    # valor de retorno.
    presupuesto = conn.execute(
        "SELECT * FROM presupuestos WHERE id = ?", (resultado["presupuestador"]["presupuesto_id"],)
    ).fetchone()
    assert presupuesto["estado"] == "aprobado"
    assert presupuesto["cita_id"] == resultado["cita_id"]


def test_caso_de_rechazo_completo_10000_km(conn):
    """OBLIGATORIO: discos de freno + 10.000 km -> el escalado a humano en
    el paso de Diagnóstico impide que el flujo llegue siquiera al
    Presupuestador. Diagnóstico se mockea con la salida deliberadamente
    mal calibrada del hito 5/6 -- Router y ambos pasos del Evaluador son
    llamadas reales."""
    cliente_id, vehiculo_id, pieza_id = _escenario(conn, "600111251", "2222FIN", kilometraje=10000)

    diagnostico_client = client_con_json(
        {
            "causas_probables": ["Discos de freno desgastados, requieren cambio"],
            "revisar_primero": "Discos de freno",
            "confianza": "alta",
            "razonamiento": "El ruido es compatible con discos desgastados que requieren sustitución.",
        }
    )

    resultado = flujo_completo.procesar_flujo_completo(
        conn,
        mensaje="Se escucha un chirrido al frenar de vez en cuando",
        cliente_id=cliente_id,
        vehiculo_id=vehiculo_id,
        fecha_hora_cita="2026-09-01 10:00",
        piezas_candidatas=[pieza_id],
        horas_mano_obra=1.0,
        diagnostico_client=diagnostico_client,
    )

    assert resultado["router"]["agente_destino"] == "diagnostico"
    assert resultado["resultado_final"] == "escalado_humano", (
        f"Se esperaba escalado_humano; se obtuvo {resultado['resultado_final']!r}. "
        f"Razonamiento del Evaluador: {resultado['evaluador_diagnostico']['razonamiento']!r}"
    )
    assert resultado["cita_id"] is None
    assert resultado["presupuestador"] is None
    assert resultado["evaluador_presupuesto"] is None

    # Ninguna cita ni presupuesto real, no solo ausentes del valor de retorno.
    assert conn.execute("SELECT COUNT(*) AS n FROM citas").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM presupuestos").fetchone()["n"] == 0


def test_via_de_urgencia_completa_salta_todo_el_pipeline(conn):
    """Confirma que el atajo de urgencia sigue saltándose TODO el
    pipeline (Diagnóstico, Evaluador, Presupuestador) en el flujo
    unificado de extremo a extremo, con una llamada real."""
    cliente_id, vehiculo_id, pieza_id = _escenario(conn, "600111252", "3333FIN", kilometraje=80000)

    resultado = flujo_completo.procesar_flujo_completo(
        conn,
        mensaje="Se me han roto los frenos, no puedo parar el coche, es peligroso",
        cliente_id=cliente_id,
        vehiculo_id=vehiculo_id,
    )

    assert resultado["router"]["intencion"] == "urgencia"
    assert resultado["resultado_final"] == "escalado_humano_inmediato"
    assert resultado["diagnostico"] is None
    assert resultado["evaluador_diagnostico"] is None
    assert resultado["cita_id"] is None
    assert resultado["presupuestador"] is None
    assert resultado["evaluador_presupuesto"] is None

    rows = conn.execute("SELECT * FROM decision_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["agent"] == "router"
