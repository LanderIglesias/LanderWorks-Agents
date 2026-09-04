import pytest

from backend.agents.taller_mecanico import crm, flujo_presupuesto, inventario, presupuestador
from tests.taller_mecanico.conftest import client_con_json

DIAGNOSTICO_APROBADO = {
    "causas_probables": ["Pastillas de freno desgastadas"],
    "revisar_primero": "Pastillas de freno",
    "confianza": "media",
    "razonamiento": "Ruido al frenar compatible con desgaste de pastillas.",
}


def _client_presupuesto(piezas_seleccionadas, descuento_tipo="ninguno", **kwargs):
    payload = {
        "piezas_seleccionadas": piezas_seleccionadas,
        "descuento_tipo": descuento_tipo,
        "criterio_excepcional": kwargs.get("criterio_excepcional"),
        "porcentaje_descuento_excepcional": kwargs.get("porcentaje_descuento_excepcional"),
        "razonamiento": kwargs.get("razonamiento", "Presupuesto calculado."),
    }
    return client_con_json(payload)


def _client_evaluacion(veredicto: str, coherente=True, descuento_verificado=True, **kwargs):
    return client_con_json(
        {
            "veredicto": veredicto,
            "coherente_con_diagnostico": coherente,
            "descuento_verificado": descuento_verificado,
            "advertencia": kwargs.get("advertencia"),
            "feedback_para_reintento": kwargs.get("feedback_para_reintento"),
            "razonamiento": kwargs.get("razonamiento", "razón"),
        }
    )


@pytest.fixture
def escenario(conn):
    cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
    vehiculo_id = crm.alta_vehiculo(
        conn, cliente_id, matricula="1234ABC", marca="Seat", modelo="Ibiza", kilometraje=80000
    )
    cita_id = conn.execute(
        "INSERT INTO citas (vehiculo_id, fecha_hora, motivo) VALUES (?, '2026-09-01 10:00', 'Ruido al frenar')",
        (vehiculo_id,),
    ).lastrowid
    conn.commit()
    pieza_id = inventario.alta_pieza(conn, "Pastillas", precio_unitario=40.0, stock_inicial=10)
    return {
        "conn": conn,
        "cliente_id": cliente_id,
        "vehiculo_id": vehiculo_id,
        "cita_id": cita_id,
        "pieza_id": pieza_id,
    }


class TestFlujoPresupuestoAprobado:
    def test_presupuestador_y_evaluador_encadenados(self, escenario):
        conn = escenario["conn"]
        presupuestador_client = _client_presupuesto(
            [
                {
                    "pieza_id": escenario["pieza_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "Pieza original disponible en inventario.",
                }
            ]
        )
        evaluador_client = _client_evaluacion("aprobado")

        resultado = flujo_presupuesto.procesar_presupuesto(
            conn,
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            cita_id=escenario["cita_id"],
            diagnostico_aprobado=DIAGNOSTICO_APROBADO,
            piezas_candidatas=[escenario["pieza_id"]],
            horas_mano_obra=1.0,
            intencion_original="consulta_tecnica",
            presupuestador_client=presupuestador_client,
            evaluador_client=evaluador_client,
        )

        assert resultado["resultado_final"] == "aprobado"
        assert resultado["presupuestador"] is not None
        assert resultado["evaluador"] is not None

        presupuestador_id = resultado["presupuestador"]["decision_id"]
        evaluador_id = resultado["evaluador"]["decision_id"]
        rows = {
            row["id"]: row
            for row in conn.execute("SELECT * FROM decision_log ORDER BY id").fetchall()
        }
        assert rows[presupuestador_id]["agent"] == "presupuestador"
        assert rows[evaluador_id]["parent_decision_id"] == presupuestador_id
        assert rows[evaluador_id]["verdict"] == "aprobado"

        # Hallazgo de la revisión de seguridad: el veredicto del Evaluador
        # debe reflejarse en presupuestos.estado, no quedar solo en
        # decision_log -- si no, la fila real queda en 'borrador' para
        # siempre y nada distingue un presupuesto aprobado de uno que el
        # Evaluador rechazó.
        fila_presupuesto = conn.execute(
            "SELECT estado FROM presupuestos WHERE id = ?",
            (resultado["presupuestador"]["presupuesto_id"],),
        ).fetchone()
        assert fila_presupuesto["estado"] == "aprobado"

    def test_veredicto_rechazado_actualiza_estado_del_presupuesto(self, escenario):
        conn = escenario["conn"]
        presupuestador_client = _client_presupuesto(
            [
                {
                    "pieza_id": escenario["pieza_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ]
        )
        evaluador_client = _client_evaluacion(
            "rechazado", feedback_para_reintento="corrige la elección de pieza"
        )

        resultado = flujo_presupuesto.procesar_presupuesto(
            conn,
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            cita_id=escenario["cita_id"],
            diagnostico_aprobado=DIAGNOSTICO_APROBADO,
            piezas_candidatas=[escenario["pieza_id"]],
            horas_mano_obra=1.0,
            intencion_original="consulta_tecnica",
            presupuestador_client=presupuestador_client,
            evaluador_client=evaluador_client,
        )

        fila_presupuesto = conn.execute(
            "SELECT estado FROM presupuestos WHERE id = ?",
            (resultado["presupuestador"]["presupuesto_id"],),
        ).fetchone()
        assert fila_presupuesto["estado"] == "rechazado"

    def test_veredicto_escalado_humano_tambien_marca_rechazado(self, escenario):
        conn = escenario["conn"]
        presupuestador_client = _client_presupuesto(
            [
                {
                    "pieza_id": escenario["pieza_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ]
        )
        evaluador_client = _client_evaluacion("escalado_humano", descuento_verificado=False)

        resultado = flujo_presupuesto.procesar_presupuesto(
            conn,
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            cita_id=escenario["cita_id"],
            diagnostico_aprobado=DIAGNOSTICO_APROBADO,
            piezas_candidatas=[escenario["pieza_id"]],
            horas_mano_obra=1.0,
            intencion_original="consulta_tecnica",
            presupuestador_client=presupuestador_client,
            evaluador_client=evaluador_client,
        )

        # No hay un estado 'escalado_humano' en el esquema de presupuestos
        # (solo borrador/aprobado/rechazado/enviado) -- se marca
        # 'rechazado' porque, igual que un rechazo, NO debe enviarse al
        # cliente sin más acción.
        fila_presupuesto = conn.execute(
            "SELECT estado FROM presupuestos WHERE id = ?",
            (resultado["presupuestador"]["presupuesto_id"],),
        ).fetchone()
        assert fila_presupuesto["estado"] == "rechazado"


class TestFlujoPresupuestoRechazoDeterministaNuncaLlegaAlEvaluador:
    def test_pieza_sin_respaldo_no_llama_al_evaluador(self, escenario):
        conn = escenario["conn"]
        presupuestador_client = _client_presupuesto(
            [
                {
                    "pieza_id": escenario["pieza_id"],
                    "cantidad": 1,
                    "eleccion": "compatible",  # sin respaldo real -- pieza es original en catálogo
                    "justificacion": "Es más barata.",
                }
            ]
        )
        evaluador_client = _client_evaluacion("aprobado")

        with pytest.raises(presupuestador.PresupuestoRechazadoError):
            flujo_presupuesto.procesar_presupuesto(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                presupuestador_client=presupuestador_client,
                evaluador_client=evaluador_client,
            )

        assert evaluador_client.messages.ultima_llamada is None


class TestAislamiento:
    def test_solo_flujo_presupuesto_importa_a_ambos(self):
        import ast
        from pathlib import Path

        source = Path(flujo_presupuesto.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        modulos = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    modulos.add(node.module.split(".")[-1])
                if node.level > 0:
                    for alias in node.names:
                        modulos.add(alias.name.split(".")[-1])
        assert {"presupuestador", "evaluador"}.issubset(modulos)
