"""Smoke tests contra la API real para flujo_presupuesto.py (hito 7).

Mismo gate que los demás tests de humo: TALLER_MECANICO_RUN_LIVE_TESTS=1.

Ejecutar con:
    TALLER_MECANICO_RUN_LIVE_TESTS=1 pytest tests/taller_mecanico/test_flujo_presupuesto_live.py -v
"""

import os

import pytest

from backend.agents.taller_mecanico import crm, flujo_presupuesto, inventario

pytestmark = pytest.mark.skipif(
    os.environ.get("TALLER_MECANICO_RUN_LIVE_TESTS") != "1",
    reason="Test de humo contra la API real -- requiere TALLER_MECANICO_RUN_LIVE_TESTS=1 "
    "y ANTHROPIC_API_KEY válida. No se ejecuta en la corrida normal de tests.",
)

DIAGNOSTICO_APROBADO = {
    "causas_probables": ["Pastillas de freno desgastadas"],
    "revisar_primero": "Pastillas de freno",
    "confianza": "media",
    "razonamiento": "Ruido al frenar compatible con desgaste de pastillas.",
}


def _escenario(conn, telefono: str, matricula: str):
    cliente_id = crm.alta_cliente(conn, nombre="Cliente de prueba", telefono=telefono)
    vehiculo_id = crm.alta_vehiculo(
        conn, cliente_id, matricula=matricula, marca="Seat", modelo="Ibiza", kilometraje=80000
    )
    cita_id = conn.execute(
        "INSERT INTO citas (vehiculo_id, fecha_hora, motivo) VALUES (?, '2026-09-01 10:00', 'Ruido al frenar')",
        (vehiculo_id,),
    ).lastrowid
    conn.commit()
    pieza_id = inventario.alta_pieza(
        conn, "Pastillas Bosch", precio_unitario=40.0, stock_inicial=10
    )
    return cliente_id, vehiculo_id, cita_id, pieza_id


def test_presupuesto_normal_aprobado_end_to_end_real(conn):
    cliente_id, vehiculo_id, cita_id, pieza_id = _escenario(conn, "600111240", "1111PRE")

    resultado = flujo_presupuesto.procesar_presupuesto(
        conn,
        cliente_id=cliente_id,
        vehiculo_id=vehiculo_id,
        cita_id=cita_id,
        diagnostico_aprobado=DIAGNOSTICO_APROBADO,
        piezas_candidatas=[pieza_id],
        horas_mano_obra=1.0,
        intencion_original="consulta_tecnica",
    )

    assert resultado["presupuestador"]["descuento_tipo"] == "ninguno"
    assert resultado["resultado_final"] == "aprobado", (
        f"Se esperaba aprobado, se obtuvo {resultado['resultado_final']!r}. "
        f"Razonamiento del Evaluador: {resultado['evaluador']['razonamiento']!r}"
    )

    # Cadena completa verificada contra decision_log real.
    pid = resultado["presupuestador"]["decision_id"]
    eid = resultado["evaluador"]["decision_id"]
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM decision_log ORDER BY id").fetchall()}
    assert rows[pid]["agent"] == "presupuestador"
    assert rows[eid]["parent_decision_id"] == pid
    assert rows[eid]["verdict"] == "aprobado"


def test_descuento_estandar_por_fidelidad_end_to_end_real(conn):
    cliente_id, vehiculo_id, cita_id, pieza_id = _escenario(conn, "600111241", "2222PRE")
    for i in range(3):
        conn.execute(
            "INSERT INTO citas (vehiculo_id, fecha_hora, motivo, estado) "
            f"VALUES (?, '2026-0{i + 1}-01 09:00', 'Visita previa', 'completada')",
            (vehiculo_id,),
        )
    conn.commit()

    resultado = flujo_presupuesto.procesar_presupuesto(
        conn,
        cliente_id=cliente_id,
        vehiculo_id=vehiculo_id,
        cita_id=cita_id,
        diagnostico_aprobado=DIAGNOSTICO_APROBADO,
        piezas_candidatas=[pieza_id],
        horas_mano_obra=1.0,
        intencion_original="consulta_tecnica",
    )

    assert resultado["presupuestador"]["descuento_tipo"] == "estandar", (
        f"Se esperaba descuento estándar (cliente con 3 visitas completadas), se obtuvo "
        f"{resultado['presupuestador']['descuento_tipo']!r}. Razonamiento: "
        f"{resultado['presupuestador']['razonamiento']!r}"
    )
