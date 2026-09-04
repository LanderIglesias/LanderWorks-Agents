import pytest

from backend.agents.taller_mecanico import crm, flujo_completo, inventario
from tests.taller_mecanico.conftest import client_con_json


def _client_router(intencion: str, agente_destino: str, razonamiento: str = "x"):
    return client_con_json(
        {"intencion": intencion, "agente_destino": agente_destino, "razonamiento": razonamiento}
    )


def _client_diagnostico(causas, revisar_primero, confianza, razonamiento="x"):
    return client_con_json(
        {
            "causas_probables": causas,
            "revisar_primero": revisar_primero,
            "confianza": confianza,
            "razonamiento": razonamiento,
        }
    )


def _client_evaluacion_diagnostico(veredicto, coherente=True, razonamiento="x", **kwargs):
    return client_con_json(
        {
            "veredicto": veredicto,
            "confianza_evaluador": kwargs.get("confianza_evaluador", "media"),
            "coherente_con_historial": coherente,
            "advertencia": kwargs.get("advertencia"),
            "feedback_para_reintento": kwargs.get("feedback_para_reintento"),
            "razonamiento": razonamiento,
        }
    )


def _client_presupuesto(piezas_seleccionadas, descuento_tipo="ninguno", **kwargs):
    return client_con_json(
        {
            "piezas_seleccionadas": piezas_seleccionadas,
            "descuento_tipo": descuento_tipo,
            "criterio_excepcional": kwargs.get("criterio_excepcional"),
            "porcentaje_descuento_excepcional": kwargs.get("porcentaje_descuento_excepcional"),
            "razonamiento": kwargs.get("razonamiento", "x"),
        }
    )


def _client_evaluacion_presupuesto(veredicto, **kwargs):
    return client_con_json(
        {
            "veredicto": veredicto,
            "coherente_con_diagnostico": kwargs.get("coherente_con_diagnostico", True),
            "descuento_verificado": kwargs.get("descuento_verificado", True),
            "advertencia": kwargs.get("advertencia"),
            "feedback_para_reintento": kwargs.get("feedback_para_reintento"),
            "razonamiento": kwargs.get("razonamiento", "x"),
        }
    )


@pytest.fixture
def escenario(conn):
    cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
    vehiculo_id = crm.alta_vehiculo(
        conn, cliente_id, matricula="1234ABC", marca="Seat", modelo="Ibiza", kilometraje=80000
    )
    pieza_id = inventario.alta_pieza(conn, "Pastillas", precio_unitario=40.0, stock_inicial=10)
    return {
        "conn": conn,
        "cliente_id": cliente_id,
        "vehiculo_id": vehiculo_id,
        "pieza_id": pieza_id,
    }


class TestFlujoCompletoAceptacion:
    """Test de aceptación COMPLETO del documento de arranque, de principio
    a fin, con los 5 pasos mockeados para probar la ORQUESTACIÓN de forma
    determinista -- la versión contra la API real está en
    test_flujo_completo_live.py."""

    def test_recorrido_completo_hasta_presupuesto_aprobado(self, escenario):
        conn = escenario["conn"]
        resultado = flujo_completo.procesar_flujo_completo(
            conn,
            mensaje="Mi coche hace un ruido raro al frenar por las mañanas",
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            fecha_hora_cita="2026-09-01 10:00",
            piezas_candidatas=[escenario["pieza_id"]],
            horas_mano_obra=1.0,
            router_client=_client_router("consulta_tecnica", "diagnostico"),
            diagnostico_client=_client_diagnostico(
                ["Pastillas de freno desgastadas", "Discos con óxido superficial"],
                "Pastillas de freno",
                "media",
            ),
            evaluador_diagnostico_client=_client_evaluacion_diagnostico(
                "aprobado", advertencia="Se recomienda inspección visual antes de presupuestar."
            ),
            presupuestador_client=_client_presupuesto(
                [
                    {
                        "pieza_id": escenario["pieza_id"],
                        "cantidad": 1,
                        "eleccion": "original",
                        "justificacion": "Pieza original disponible en inventario.",
                    }
                ]
            ),
            evaluador_presupuesto_client=_client_evaluacion_presupuesto("aprobado"),
        )

        assert resultado["resultado_final"] == "aprobado"
        assert resultado["cita_id"] is not None
        assert resultado["presupuestador"] is not None
        assert resultado["evaluador_presupuesto"]["veredicto"] == "aprobado"

        # La cita quedó realmente creada, vía agenda.py.
        cita = conn.execute("SELECT * FROM citas WHERE id = ?", (resultado["cita_id"],)).fetchone()
        assert cita["vehiculo_id"] == escenario["vehiculo_id"]

        # El presupuesto quedó realmente aprobado en la tabla real.
        presupuesto = conn.execute(
            "SELECT * FROM presupuestos WHERE id = ?",
            (resultado["presupuestador"]["presupuesto_id"],),
        ).fetchone()
        assert presupuesto["estado"] == "aprobado"
        assert presupuesto["cita_id"] == resultado["cita_id"]

    def test_cadena_parent_decision_id_de_extremo_a_extremo(self, escenario):
        conn = escenario["conn"]
        resultado = flujo_completo.procesar_flujo_completo(
            conn,
            mensaje="ruido al frenar",
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            fecha_hora_cita="2026-09-01 10:00",
            piezas_candidatas=[escenario["pieza_id"]],
            horas_mano_obra=1.0,
            router_client=_client_router("consulta_tecnica", "diagnostico"),
            diagnostico_client=_client_diagnostico(["Causa A"], "Revisar A", "media"),
            evaluador_diagnostico_client=_client_evaluacion_diagnostico("aprobado"),
            presupuestador_client=_client_presupuesto(
                [
                    {
                        "pieza_id": escenario["pieza_id"],
                        "cantidad": 1,
                        "eleccion": "original",
                        "justificacion": "x",
                    }
                ]
            ),
            evaluador_presupuesto_client=_client_evaluacion_presupuesto("aprobado"),
        )

        router_id = resultado["router"]["decision_id"]
        diagnostico_id = resultado["diagnostico"]["decision_id"]
        eval_diag_id = resultado["evaluador_diagnostico"]["decision_id"]
        presupuestador_id = resultado["presupuestador"]["decision_id"]
        eval_pres_id = resultado["evaluador_presupuesto"]["decision_id"]

        rows = {
            r["id"]: r for r in conn.execute("SELECT * FROM decision_log ORDER BY id").fetchall()
        }
        assert rows[router_id]["parent_decision_id"] is None
        assert rows[diagnostico_id]["parent_decision_id"] == router_id
        assert rows[eval_diag_id]["parent_decision_id"] == diagnostico_id
        assert rows[presupuestador_id]["parent_decision_id"] == eval_diag_id
        assert rows[eval_pres_id]["parent_decision_id"] == presupuestador_id

        # Cadena completa reconstruible: exactamente 5 filas, enlazadas.
        assert len(rows) == 5


class TestFlujoCompletoRechazo:
    """Test de rechazo COMPLETO: discos de freno + 10.000 km -> el
    escalado a humano en Diagnóstico impide que el flujo llegue siquiera
    al Presupuestador. No debe generarse ningún presupuesto."""

    def test_diagnostico_escalado_no_llega_a_presupuestador(self, conn):
        cliente_id = crm.alta_cliente(conn, nombre="Bea Ruiz", telefono="600111223")
        vehiculo_id = crm.alta_vehiculo(
            conn,
            cliente_id,
            matricula="9999XYZ",
            marca="Toyota",
            modelo="Corolla",
            kilometraje=10000,
        )
        presupuestador_client = _client_presupuesto(
            [
                {
                    "pieza_id": 1,
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "no debería usarse",
                }
            ]
        )
        evaluador_presupuesto_client = _client_evaluacion_presupuesto("aprobado")

        resultado = flujo_completo.procesar_flujo_completo(
            conn,
            mensaje="ruido metálico al frenar",
            cliente_id=cliente_id,
            vehiculo_id=vehiculo_id,
            fecha_hora_cita="2026-09-01 10:00",
            piezas_candidatas=[1],
            horas_mano_obra=1.0,
            router_client=_client_router("consulta_tecnica", "diagnostico"),
            diagnostico_client=_client_diagnostico(
                ["Discos de freno desgastados, requieren cambio"], "Discos de freno", "alta"
            ),
            evaluador_diagnostico_client=_client_evaluacion_diagnostico(
                "escalado_humano", coherente=False
            ),
            presupuestador_client=presupuestador_client,
            evaluador_presupuesto_client=evaluador_presupuesto_client,
        )

        assert resultado["resultado_final"] == "escalado_humano"
        assert resultado["cita_id"] is None
        assert resultado["presupuestador"] is None
        assert resultado["evaluador_presupuesto"] is None

        # Prueba definitiva: los clientes falsos de Presupuestador/Evaluador
        # de presupuesto NUNCA recibieron ninguna llamada.
        assert presupuestador_client.messages.ultima_llamada is None
        assert evaluador_presupuesto_client.messages.ultima_llamada is None

        assert conn.execute("SELECT COUNT(*) AS n FROM citas").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM presupuestos").fetchone()["n"] == 0


class TestFlujoCompletoUrgencia:
    """Test de urgencia COMPLETO: el atajo sigue saltándose TODO el
    pipeline (Diagnóstico, Evaluador, Presupuestador) en el flujo unificado."""

    def test_urgencia_salta_todo_el_pipeline(self, escenario):
        conn = escenario["conn"]
        diagnostico_client = _client_diagnostico(["no debería usarse"], "x", "alta")
        evaluador_diagnostico_client = _client_evaluacion_diagnostico("aprobado")
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
        evaluador_presupuesto_client = _client_evaluacion_presupuesto("aprobado")

        resultado = flujo_completo.procesar_flujo_completo(
            conn,
            mensaje="se me han roto los frenos, no puedo parar el coche",
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            fecha_hora_cita="2026-09-01 10:00",
            piezas_candidatas=[escenario["pieza_id"]],
            horas_mano_obra=1.0,
            router_client=_client_router("urgencia", "diagnostico"),  # el modelo se "equivoca"
            diagnostico_client=diagnostico_client,
            evaluador_diagnostico_client=evaluador_diagnostico_client,
            presupuestador_client=presupuestador_client,
            evaluador_presupuesto_client=evaluador_presupuesto_client,
        )

        assert resultado["resultado_final"] == "escalado_humano_inmediato"
        assert resultado["diagnostico"] is None
        assert resultado["evaluador_diagnostico"] is None
        assert resultado["cita_id"] is None
        assert resultado["presupuestador"] is None
        assert resultado["evaluador_presupuesto"] is None

        for client in (
            diagnostico_client,
            evaluador_diagnostico_client,
            presupuestador_client,
            evaluador_presupuesto_client,
        ):
            assert client.messages.ultima_llamada is None

        rows = conn.execute("SELECT * FROM decision_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["agent"] == "router"


class TestValidacionDeEntradas:
    def test_cliente_inexistente_falla_antes_de_llamar_a_nada(self, escenario):
        conn = escenario["conn"]
        router_client = _client_router("consulta_tecnica", "diagnostico")
        with pytest.raises(crm.ClienteNoEncontradoError):
            flujo_completo.procesar_flujo_completo(
                conn,
                mensaje="ruido al frenar",
                cliente_id=999,
                vehiculo_id=escenario["vehiculo_id"],
                fecha_hora_cita="2026-09-01 10:00",
                piezas_candidatas=[escenario["pieza_id"]],
                horas_mano_obra=1.0,
                router_client=router_client,
            )
        assert router_client.messages.ultima_llamada is None

    def test_diagnostico_aprobado_sin_fecha_cita_lanza_value_error(self, escenario):
        conn = escenario["conn"]
        with pytest.raises(ValueError, match="fecha_hora_cita"):
            flujo_completo.procesar_flujo_completo(
                conn,
                mensaje="ruido al frenar",
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                piezas_candidatas=[escenario["pieza_id"]],
                horas_mano_obra=1.0,
                router_client=_client_router("consulta_tecnica", "diagnostico"),
                diagnostico_client=_client_diagnostico(["x"], "x", "media"),
                evaluador_diagnostico_client=_client_evaluacion_diagnostico("aprobado"),
            )

    def test_diagnostico_aprobado_sin_piezas_candidatas_lanza_value_error(self, escenario):
        conn = escenario["conn"]
        with pytest.raises(ValueError, match="piezas_candidatas"):
            flujo_completo.procesar_flujo_completo(
                conn,
                mensaje="ruido al frenar",
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                fecha_hora_cita="2026-09-01 10:00",
                router_client=_client_router("consulta_tecnica", "diagnostico"),
                diagnostico_client=_client_diagnostico(["x"], "x", "media"),
                evaluador_diagnostico_client=_client_evaluacion_diagnostico("aprobado"),
            )

    def test_piezas_candidatas_vacia_lanza_value_error(self, escenario):
        conn = escenario["conn"]
        with pytest.raises(ValueError, match="piezas_candidatas"):
            flujo_completo.procesar_flujo_completo(
                conn,
                mensaje="ruido al frenar",
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                fecha_hora_cita="2026-09-01 10:00",
                piezas_candidatas=[],
                horas_mano_obra=1.0,
                router_client=_client_router("consulta_tecnica", "diagnostico"),
                diagnostico_client=_client_diagnostico(["x"], "x", "media"),
                evaluador_diagnostico_client=_client_evaluacion_diagnostico("aprobado"),
            )

    def test_horas_mano_obra_negativa_lanza_value_error(self, escenario):
        conn = escenario["conn"]
        with pytest.raises(ValueError, match="horas_mano_obra"):
            flujo_completo.procesar_flujo_completo(
                conn,
                mensaje="ruido al frenar",
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                fecha_hora_cita="2026-09-01 10:00",
                piezas_candidatas=[escenario["pieza_id"]],
                horas_mano_obra=-1.0,
                router_client=_client_router("consulta_tecnica", "diagnostico"),
                diagnostico_client=_client_diagnostico(["x"], "x", "media"),
                evaluador_diagnostico_client=_client_evaluacion_diagnostico("aprobado"),
            )

    def test_duracion_cita_no_positiva_lanza_value_error(self, escenario):
        conn = escenario["conn"]
        with pytest.raises(ValueError, match="duracion_cita_minutos"):
            flujo_completo.procesar_flujo_completo(
                conn,
                mensaje="ruido al frenar",
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                fecha_hora_cita="2026-09-01 10:00",
                duracion_cita_minutos=0,
                piezas_candidatas=[escenario["pieza_id"]],
                horas_mano_obra=1.0,
                router_client=_client_router("consulta_tecnica", "diagnostico"),
                diagnostico_client=_client_diagnostico(["x"], "x", "media"),
                evaluador_diagnostico_client=_client_evaluacion_diagnostico("aprobado"),
            )

    def test_vehiculo_de_otro_cliente_lanza_value_error(self, escenario):
        """Hallazgo de la revisión de seguridad del hito 8: sin esta
        comprobación, un llamante podía emparejar el vehículo de un
        cliente con el cliente_id de otro para heredar su historial de
        fidelidad en el cálculo de descuento del Presupuestador."""
        conn = escenario["conn"]
        otro_cliente_id = crm.alta_cliente(conn, nombre="Otro Cliente", telefono="600111299")
        with pytest.raises(ValueError, match="no pertenece"):
            flujo_completo.procesar_flujo_completo(
                conn,
                mensaje="ruido al frenar",
                cliente_id=otro_cliente_id,
                vehiculo_id=escenario["vehiculo_id"],
                fecha_hora_cita="2026-09-01 10:00",
                piezas_candidatas=[escenario["pieza_id"]],
                horas_mano_obra=1.0,
            )


class TestCitaSeCancelaSiFallaElPresupuesto:
    def test_presupuestador_falla_cancela_la_cita_ya_creada(self, escenario):
        """Hallazgo de la revisión de seguridad del hito 8: antes de este
        fix, un fallo en el paso de presupuesto dejaba la cita ya creada
        en estado 'pendiente' para siempre, bloqueando el hueco del
        vehículo sin ninguna forma de recuperarla desde el valor de
        retorno (la excepción se propaga antes de que cita_id llegue al
        llamante)."""
        conn = escenario["conn"]

        class _ClienteQueFalla:
            class messages:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("fallo simulado del Presupuestador")

        with pytest.raises(RuntimeError, match="fallo simulado"):
            flujo_completo.procesar_flujo_completo(
                conn,
                mensaje="ruido al frenar",
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                fecha_hora_cita="2026-09-01 10:00",
                piezas_candidatas=[escenario["pieza_id"]],
                horas_mano_obra=1.0,
                router_client=_client_router("consulta_tecnica", "diagnostico"),
                diagnostico_client=_client_diagnostico(["x"], "x", "media"),
                evaluador_diagnostico_client=_client_evaluacion_diagnostico("aprobado"),
                presupuestador_client=_ClienteQueFalla(),
            )

        # La cita fue creada y luego cancelada, no dejada 'pendiente'.
        citas = conn.execute("SELECT * FROM citas").fetchall()
        assert len(citas) == 1
        assert citas[0]["estado"] == "cancelada"


class TestAislamiento:
    def test_flujo_completo_no_reimplementa_agentes_directamente(self):
        import ast
        from pathlib import Path

        source = Path(flujo_completo.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        modulos = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    modulos.add(node.module.split(".")[-1])
                if node.level > 0:
                    for alias in node.names:
                        modulos.add(alias.name.split(".")[-1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    modulos.add(alias.name.split(".")[-1])

        # Debe apoyarse en las orquestaciones ya construidas...
        assert {"flujo_diagnostico", "flujo_presupuesto", "agenda", "crm"}.issubset(modulos)
        # ...no reimplementar router/diagnostico/evaluador/presupuestador
        # importándolos directamente (eso sería reescribir orquestación
        # que flujo_diagnostico.py/flujo_presupuesto.py ya resuelven).
        prohibidos = {"router", "diagnostico", "evaluador", "presupuestador"}
        assert not (modulos & prohibidos)
