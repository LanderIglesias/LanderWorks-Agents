import json

import pytest

from backend.agents.taller_mecanico import langfuse_utils, router
from tests.taller_mecanico.conftest import FakeAnthropicClient, FakeLangfuseClient, client_con_json


def _client_con_respuesta(
    intencion: str, agente_destino: str, razonamiento: str
) -> FakeAnthropicClient:
    return client_con_json(
        {"intencion": intencion, "agente_destino": agente_destino, "razonamiento": razonamiento}
    )


class TestClasificarMensaje:
    def test_clasifica_consulta_tecnica_y_deriva_a_diagnostico(self, conn):
        client = _client_con_respuesta(
            "consulta_tecnica",
            "diagnostico",
            "El cliente describe un ruido mecánico, no una cita ni queja.",
        )
        resultado = router.clasificar_mensaje(
            conn, "Mi coche hace un ruido raro al frenar por las mañanas", client=client
        )
        assert resultado["intencion"] == "consulta_tecnica"
        assert resultado["agente_destino"] == "diagnostico"
        assert "decision_id" in resultado

    def test_clasifica_cita_y_deriva_a_herramienta_agenda(self, conn):
        client = _client_con_respuesta(
            "cita", "herramienta_agenda", "El cliente pide directamente reservar hora."
        )
        resultado = router.clasificar_mensaje(
            conn, "Quiero pedir cita para el jueves", client=client
        )
        assert resultado["intencion"] == "cita"
        assert resultado["agente_destino"] == "herramienta_agenda"

    def test_clasifica_queja_y_deriva_a_humano(self, conn):
        client = _client_con_respuesta(
            "queja", "humano", "El cliente expresa insatisfacción con un servicio anterior."
        )
        resultado = router.clasificar_mensaje(
            conn,
            "Llevo dos semanas esperando y nadie me ha llamado, esto es inadmisible",
            client=client,
        )
        assert resultado["intencion"] == "queja"
        assert resultado["agente_destino"] == "humano"

    def test_mensaje_vacio_rechazado_sin_llamar_a_la_api(self, conn):
        client = _client_con_respuesta("otro", "humano", "no debería usarse")
        with pytest.raises(ValueError):
            router.clasificar_mensaje(conn, "   ", client=client)
        assert client.messages.ultima_llamada is None

    def test_usa_el_modelo_haiku_configurado(self, conn):
        client = _client_con_respuesta("otro", "humano", "x")
        router.clasificar_mensaje(conn, "hola", client=client)
        assert client.messages.ultima_llamada["model"] == router.MODEL

    def test_envia_el_mensaje_del_cliente_tal_cual(self, conn):
        client = _client_con_respuesta("otro", "humano", "x")
        router.clasificar_mensaje(conn, "mensaje exacto de prueba", client=client)
        assert client.messages.ultima_llamada["messages"] == [
            {"role": "user", "content": "mensaje exacto de prueba"}
        ]


class TestDecisionLogAislado:
    def test_escribe_una_fila_en_decision_log(self, conn):
        client = _client_con_respuesta("consulta_tecnica", "diagnostico", "razón de prueba")
        router.clasificar_mensaje(conn, "ruido al frenar", client=client)
        row = conn.execute("SELECT * FROM decision_log").fetchone()
        assert row["agent"] == "router"
        assert row["input_text"] == "ruido al frenar"
        assert row["reasoning"] == "razón de prueba"
        assert row["reviewed_by"] is None
        assert row["verdict"] is None

    def test_output_es_json_valido_con_la_clasificacion(self, conn):
        client = _client_con_respuesta("presupuesto", "presupuestador", "pide precio")
        router.clasificar_mensaje(conn, "¿cuánto cuesta cambiar las pastillas?", client=client)
        row = conn.execute("SELECT output FROM decision_log").fetchone()
        output = json.loads(row["output"])
        assert output["intencion"] == "presupuesto"
        assert output["agente_destino"] == "presupuestador"

    def test_no_escribe_en_ninguna_otra_tabla(self, conn):
        client = _client_con_respuesta("cita", "herramienta_agenda", "x")
        router.clasificar_mensaje(conn, "quiero cita", client=client)
        for tabla in ("clientes", "vehiculos", "citas", "piezas", "presupuestos"):
            count = conn.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"]
            assert count == 0, f"router no debería escribir en {tabla}"


class TestRespuestaInvalidaDelModelo:
    def test_respuesta_no_json_lanza_error_pero_deja_rastro_en_el_log(self, conn):
        client = FakeAnthropicClient("esto no es json en absoluto")
        with pytest.raises(router.RouterRespuestaInvalidaError):
            router.clasificar_mensaje(conn, "mensaje de prueba", client=client)

        row = conn.execute("SELECT * FROM decision_log").fetchone()
        assert row is not None, "debe quedar constancia del intento fallido en decision_log"
        assert row["agent"] == "router"
        assert row["input_text"] == "mensaje de prueba"

    def test_respuesta_con_intencion_desconocida_lanza_error(self, conn):
        payload = json.dumps(
            {"intencion": "no_existe", "agente_destino": "humano", "razonamiento": "x"}
        )
        client = FakeAnthropicClient(payload)
        with pytest.raises(router.RouterRespuestaInvalidaError):
            router.clasificar_mensaje(conn, "mensaje", client=client)

    def test_respuesta_con_clave_faltante_lanza_error(self, conn):
        payload = json.dumps({"intencion": "cita", "razonamiento": "falta agente_destino"})
        client = FakeAnthropicClient(payload)
        with pytest.raises(router.RouterRespuestaInvalidaError):
            router.clasificar_mensaje(conn, "mensaje", client=client)

    def test_respuesta_con_razonamiento_no_textual_lanza_error_de_dominio(self, conn):
        # Sin esta validación, un dict/lista en "razonamiento" llegaría
        # intacto al INSERT y sqlite3 lanzaría InterfaceError -- una
        # excepción no documentada, en vez de RouterRespuestaInvalidaError.
        payload = json.dumps(
            {
                "intencion": "cita",
                "agente_destino": "herramienta_agenda",
                "razonamiento": {"no": "es texto"},
            }
        )
        client = FakeAnthropicClient(payload)
        with pytest.raises(router.RouterRespuestaInvalidaError):
            router.clasificar_mensaje(conn, "mensaje", client=client)

    def test_respuesta_con_razonamiento_vacio_lanza_error(self, conn):
        # Alineado con diagnostico._validar_diagnostico: un razonamiento
        # vacío no sirve de nada como auditoría en decision_log.
        payload = json.dumps(
            {"intencion": "cita", "agente_destino": "herramienta_agenda", "razonamiento": "   "}
        )
        client = FakeAnthropicClient(payload)
        with pytest.raises(router.RouterRespuestaInvalidaError):
            router.clasificar_mensaje(conn, "mensaje", client=client)

    def test_respuesta_envuelta_en_markdown_se_extrae_igualmente(self, conn):
        payload = json.dumps(
            {"intencion": "cita", "agente_destino": "herramienta_agenda", "razonamiento": "x"}
        )
        client = FakeAnthropicClient(f"```json\n{payload}\n```")
        resultado = router.clasificar_mensaje(conn, "quiero cita", client=client)
        assert resultado["intencion"] == "cita"


class TestAislamiento:
    def test_router_no_importa_los_otros_agentes_ni_agenda_inventario_crm(self):
        import ast
        from pathlib import Path

        source = Path(router.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        modulos_importados = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modulos_importados.add(node.module.split(".")[-1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    modulos_importados.add(alias.name.split(".")[-1])

        prohibidos = {"agenda", "inventario", "crm", "diagnostico", "presupuestador", "evaluador"}
        assert not (modulos_importados & prohibidos), (
            f"router.py importa módulos que debería aislar en el hito 3: "
            f"{modulos_importados & prohibidos}"
        )


class TestObservabilidadLangfuse:
    """Sin Langfuse configurado (el caso por defecto en toda la suite, ver
    `langfuse_desactivado` en conftest.py), router.py debe seguir
    funcionando exactamente igual -- la observabilidad es una capa
    adicional, no una dependencia dura."""

    def test_sin_langfuse_configurado_langfuse_trace_id_queda_null(self, conn):
        client = _client_con_respuesta(
            "cita", "herramienta_agenda", "El cliente quiere reservar hora."
        )
        resultado = router.clasificar_mensaje(conn, "quiero pedir cita", client=client)

        assert resultado["langfuse_trace_id"] is None
        assert resultado["langfuse_observation_id"] is None
        row = conn.execute("SELECT langfuse_trace_id FROM decision_log").fetchone()
        assert row["langfuse_trace_id"] is None

    def test_con_langfuse_activo_el_trace_id_queda_en_decision_log(self, conn, monkeypatch):
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        client = _client_con_respuesta(
            "cita", "herramienta_agenda", "El cliente quiere reservar hora."
        )
        resultado = router.clasificar_mensaje(conn, "quiero pedir cita", client=client)

        assert resultado["langfuse_trace_id"] is not None
        row = conn.execute(
            "SELECT langfuse_trace_id, langfuse_observation_id FROM decision_log"
        ).fetchone()
        assert row["langfuse_trace_id"] == resultado["langfuse_trace_id"]
        assert row["langfuse_observation_id"] == resultado["langfuse_observation_id"]

    def test_fallo_de_langfuse_no_rompe_la_clasificacion(self, conn, monkeypatch):
        """Requisito no negociable: un fallo de Langfuse (aquí, al abrir la
        observación) nunca debe impedir que router.py complete su trabajo
        ni perder la fila de decision_log."""
        fake = FakeLangfuseClient(fallar_al_abrir=True)
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        client = _client_con_respuesta("cita", "herramienta_agenda", "x")
        resultado = router.clasificar_mensaje(conn, "quiero pedir cita", client=client)

        assert resultado["intencion"] == "cita"
        assert resultado["langfuse_trace_id"] is None
        row = conn.execute("SELECT * FROM decision_log").fetchone()
        assert row["input_text"] == "quiero pedir cita"

    def test_error_de_dominio_se_relanza_intacto_incluso_con_langfuse_activo(
        self, conn, monkeypatch
    ):
        """Regresión del bug real encontrado durante la integración: una
        RouterRespuestaInvalidaError lanzada dentro del `with
        langfuse_utils.generacion_agente(...)` debe seguir propagándose
        (y dejando rastro en decision_log), no quedar enmascarada por un
        error de contextlib ni silenciada por Langfuse."""
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        client = FakeAnthropicClient("esto no es json en absoluto")
        with pytest.raises(router.RouterRespuestaInvalidaError):
            router.clasificar_mensaje(conn, "mensaje de prueba", client=client)

        row = conn.execute("SELECT * FROM decision_log").fetchone()
        assert row is not None
        assert row["langfuse_trace_id"] is not None


class TestUrgenciaEscalaDirectoAHumano:
    """Ajuste del hito 4: urgencia -> escalado_humano_inmediato SIEMPRE,
    sin pasar por Diagnóstico ni Evaluador (que ni siquiera existen todavía).
    Es una regla determinista del código, no solo una sugerencia al modelo
    -- estos tests fuerzan el caso en que el modelo se equivoca o ignora
    la instrucción, para comprobar que el código corrige igual."""

    def test_urgencia_fuerza_escalado_aunque_el_modelo_sugiera_otro_destino(self, conn):
        # El modelo "se equivoca" y sugiere diagnostico para una urgencia.
        client = _client_con_respuesta(
            "urgencia", "diagnostico", "El cliente reporta un fallo de frenos."
        )
        resultado = router.clasificar_mensaje(
            conn, "Se me han roto los frenos, no puedo parar el coche", client=client
        )
        assert resultado["intencion"] == "urgencia"
        assert resultado["agente_destino"] == "escalado_humano_inmediato"

    def test_urgencia_ya_clasificada_correctamente_no_cambia(self, conn):
        client = _client_con_respuesta(
            "urgencia", "escalado_humano_inmediato", "Riesgo de seguridad inmediato."
        )
        resultado = router.clasificar_mensaje(conn, "mensaje urgente", client=client)
        assert resultado["agente_destino"] == "escalado_humano_inmediato"

    def test_reasoning_explica_por_que_se_salto_el_pipeline_normal(self, conn):
        client = _client_con_respuesta("urgencia", "diagnostico", "Fallo de frenos reportado.")
        router.clasificar_mensaje(conn, "mensaje urgente", client=client)
        row = conn.execute("SELECT reasoning FROM decision_log").fetchone()
        razonamiento = row["reasoning"].lower()
        assert "diagn" in razonamiento and "evaluador" in razonamiento

    def test_output_json_en_decision_log_refleja_el_destino_forzado(self, conn):
        client = _client_con_respuesta("urgencia", "diagnostico", "x")
        router.clasificar_mensaje(conn, "mensaje urgente", client=client)
        row = conn.execute("SELECT output FROM decision_log").fetchone()
        output = json.loads(row["output"])
        assert output["agente_destino"] == "escalado_humano_inmediato"

    def test_intenciones_no_urgentes_no_se_tocan(self, conn):
        client = _client_con_respuesta("consulta_tecnica", "diagnostico", "razón normal")
        resultado = router.clasificar_mensaje(conn, "ruido al frenar", client=client)
        assert resultado["agente_destino"] == "diagnostico"
        row = conn.execute("SELECT reasoning FROM decision_log").fetchone()
        assert row["reasoning"] == "razón normal"

    def test_escalado_humano_inmediato_es_un_destino_valido(self, conn):
        client = _client_con_respuesta(
            "urgencia", "escalado_humano_inmediato", "riesgo de seguridad"
        )
        resultado = router.clasificar_mensaje(conn, "mensaje urgente", client=client)
        assert resultado["agente_destino"] in router.AGENTES_DESTINO_VALIDOS
