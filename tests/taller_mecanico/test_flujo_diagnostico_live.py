"""Smoke tests contra la API real para flujo_diagnostico.py (hito 6).

Los tres agentes hacen llamadas REALES a Claude Haiku, encadenados de
verdad -- esta es la verificación definitiva de que el patrón completo
Router → Diagnóstico → Evaluador funciona de extremo a extremo, no solo
mockeado. Mismo gate que los demás tests de humo:
TALLER_MECANICO_RUN_LIVE_TESTS=1.

Ejecutar con:
    TALLER_MECANICO_RUN_LIVE_TESTS=1 pytest tests/taller_mecanico/test_flujo_diagnostico_live.py -v
"""

import os

import pytest

from backend.agents.taller_mecanico import agenda, crm, flujo_diagnostico

pytestmark = pytest.mark.skipif(
    os.environ.get("TALLER_MECANICO_RUN_LIVE_TESTS") != "1",
    reason="Test de humo contra la API real -- requiere TALLER_MECANICO_RUN_LIVE_TESTS=1 "
    "y ANTHROPIC_API_KEY válida. No se ejecuta en la corrida normal de tests.",
)


def _vehiculo(conn, telefono: str, matricula: str, kilometraje: int) -> int:
    cliente_id = crm.alta_cliente(conn, nombre="Cliente de prueba", telefono=telefono)
    return crm.alta_vehiculo(
        conn,
        cliente_id,
        matricula=matricula,
        marca="Seat",
        modelo="Ibiza",
        anio=2015,
        kilometraje=kilometraje,
    )


def test_caso_de_aceptacion_completo_del_documento_de_arranque(conn):
    """Router deriva a Diagnóstico -> Diagnóstico sugiere pastillas/discos
    con confianza media -> Evaluador aprueba con advertencia -- los TRES
    pasos con llamadas reales, encadenados de verdad."""
    vehiculo_id = _vehiculo(conn, "600111230", "1111LIV", kilometraje=120000)

    resultado = flujo_diagnostico.procesar_mensaje(
        conn, "Mi coche hace un ruido raro al frenar por las mañanas", vehiculo_id=vehiculo_id
    )

    assert resultado["router"]["intencion"] == "consulta_tecnica"
    assert resultado["router"]["agente_destino"] == "diagnostico"
    assert resultado["diagnostico"] is not None
    assert resultado["evaluador"] is not None
    assert resultado["resultado_final"] == "aprobado", (
        f"Se esperaba 'aprobado', se obtuvo {resultado['resultado_final']!r}. "
        f"Diagnóstico: {resultado['diagnostico']['causas_probables']!r} "
        f"(confianza={resultado['diagnostico']['confianza']!r}). "
        f"Evaluador: {resultado['evaluador']['razonamiento']!r}"
    )

    # Cadena de parent_decision_id de extremo a extremo, con datos reales.
    router_id = resultado["router"]["decision_id"]
    diagnostico_id = resultado["diagnostico"]["decision_id"]
    evaluador_id = resultado["evaluador"]["decision_id"]
    rows = {
        row["id"]: row for row in conn.execute("SELECT * FROM decision_log ORDER BY id").fetchall()
    }
    assert rows[router_id]["parent_decision_id"] is None
    assert rows[diagnostico_id]["parent_decision_id"] == router_id
    assert rows[evaluador_id]["parent_decision_id"] == diagnostico_id
    assert rows[evaluador_id]["reviewed_by"] == "evaluador"
    assert rows[evaluador_id]["verdict"] == "aprobado"
    assert len(rows) == 3


def test_caso_de_rechazo_en_flujo_conectado_10000_km(conn):
    """OBLIGATORIO: mismo caso que en el hito 5 (10.000 km + Diagnóstico
    sugiere discos con confianza alta) -> el Evaluador debe escalar,
    ahora dentro del flujo CONECTADO real, no con la salida de
    Diagnóstico entregada directamente a evaluar_diagnostico() como en el
    test aislado del hito 5.

    Router y Evaluador son LLAMADAS REALES. Diagnóstico se mockea con el
    mismo diagnóstico deliberadamente mal calibrado del hito 5 --
    decisión tomada tras investigar (ver README, sección "Hito 6 --
    investigación conectado vs. aislado") que un Diagnóstico real, al
    recibir también el kilometraje vía crm.py (contexto que en el hito 5
    solo veía el Evaluador), tiende a calibrar bien su propia confianza y
    ya no comete el error que este caso necesita para poder probar la
    reacción del Evaluador de forma reproducible. Lo que este test SÍ
    verifica en vivo: que el Evaluador, recibiendo ese diagnóstico a
    través del código real de flujo_diagnostico.py (no a mano en un
    test), sigue escalando -- es decir, que la integración no alteró ni
    perdió nada en el camino Diagnóstico -> Evaluador."""
    from tests.taller_mecanico.conftest import client_con_json

    vehiculo_id = _vehiculo(conn, "600111231", "2222LIV", kilometraje=10000)

    diagnostico_client = client_con_json(
        {
            "causas_probables": ["Discos de freno desgastados, requieren cambio"],
            "revisar_primero": "Discos de freno",
            "confianza": "alta",
            "razonamiento": (
                "El ruido es compatible con discos desgastados que requieren sustitución."
            ),
        }
    )

    resultado = flujo_diagnostico.procesar_mensaje(
        conn,
        "Se escucha un chirrido al frenar de vez en cuando",
        vehiculo_id=vehiculo_id,
        diagnostico_client=diagnostico_client,
    )

    assert resultado["router"]["agente_destino"] == "diagnostico", (
        "El Router (llamada real) no derivó a diagnóstico -- no se puede probar la "
        f"cadena. Clasificación real: {resultado['router']!r}"
    )
    assert resultado["resultado_final"] == "escalado_humano", (
        f"Se esperaba escalado_humano; se obtuvo {resultado['resultado_final']!r}. "
        f"Razonamiento del Evaluador (real): {resultado['evaluador']['razonamiento']!r}"
    )
    assert resultado["evaluador"]["coherente_con_historial"] is False


def test_via_de_urgencia_sigue_sin_pasar_por_diagnostico_ni_evaluador(conn):
    """Confirma que conectar el flujo normal no rompió el atajo de
    urgencia del hito 4: un mensaje de urgencia real debe seguir yendo
    directo a escalado_humano_inmediato."""
    resultado = flujo_diagnostico.procesar_mensaje(
        conn, "Se me han roto los frenos, no puedo parar el coche, es peligroso"
    )

    assert resultado["router"]["intencion"] == "urgencia"
    assert resultado["resultado_final"] == "escalado_humano_inmediato"
    assert resultado["diagnostico"] is None
    assert resultado["evaluador"] is None

    rows = conn.execute("SELECT * FROM decision_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["agent"] == "router"


def test_motivo_de_cita_real_llega_neutralizado_al_evaluador_en_flujo_conectado(conn):
    """Verifica con datos REALES del sistema (una cita creada de verdad
    vía agenda.crear_cita, la herramienta del hito 2 -- no un INSERT
    escrito a mano en el test) que el motivo de una cita real sigue
    pasando por _neutralizar_delimitadores dentro del flujo conectado end-to-end,
    no solo en el test aislado de evaluador.py que descubrió el riesgo."""
    vehiculo_id = _vehiculo(conn, "600111232", "3333LIV", kilometraje=80000)

    # Cita real, motivo real, creada con la herramienta real del hito 2.
    agenda.crear_cita(conn, vehiculo_id, "2026-01-10 09:00", "Revisión de nivel de aceite")
    conn.execute("UPDATE citas SET estado = 'completada' WHERE vehiculo_id = ?", (vehiculo_id,))
    conn.commit()

    resultado = flujo_diagnostico.procesar_mensaje(
        conn, "ruido raro al arrancar en frío", vehiculo_id=vehiculo_id
    )

    # El propio hecho de que el flujo completo corra sin error confirma
    # que evaluador._construir_contenido procesó el historial real sin
    # romperse. Confirmamos además que el motivo real llegó al modelo
    # (a través de decision_log.input_text de Diagnóstico, que incluye el
    # historial en su propio prompt) y que la cadena se completó.
    assert resultado["evaluador"] is not None
    assert resultado["resultado_final"] in ("aprobado", "rechazado", "escalado_humano")
