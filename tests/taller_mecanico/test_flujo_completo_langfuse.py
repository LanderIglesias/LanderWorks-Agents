"""Verifica la integración de observabilidad Langfuse (spans API) sobre
el flujo end-to-end completo (hito 8 + tarea de cierre de observabilidad):

- Una única traza por interacción completa, con Router/Diagnóstico/
  Evaluador/Presupuestador como observaciones HIJAS de esa traza -- no
  como trazas independientes cada una. Verificado como jerarquía real
  (`parent_observation_id`), no solo como `trace_id` compartido: un
  `trace_id` compartido por sí solo NO demuestra anidado real (podrían
  ser hermanos sueltos bajo la misma traza por casualidad del doble de
  prueba) -- esta distinción es justo lo que un hallazgo real contra el
  dashboard de Langfuse detectó que la primera versión de este test no
  podía comprobar.
- `decision_log.langfuse_trace_id`/`langfuse_observation_id` quedan
  guardados correctamente en TODAS las filas de la cadena.
- El veredicto del Evaluador se refleja como SCORE de Langfuse sobre la
  observación evaluada (Diagnóstico/Presupuestador), no solo en
  decision_log.

Usa un FakeLangfuseClient inyectado (nunca credenciales reales -- ver
`langfuse_desactivado`, autouse, en conftest.py) para poder verificar
esto sin red ni dependencias externas. La estructura de jerarquía real
(interaccion_cliente -> flujo_diagnostico/flujo_presupuesto -> agentes)
se verificó además, una vez, contra el servidor real de Langfuse
(`client.api.trace.get(...)`) con Anthropic y Langfuse reales -- ver
README_taller_mecanico.md, sección "Observabilidad con Langfuse", para
el detalle de esa verificación manual.
"""

from backend.agents.taller_mecanico import crm, flujo_completo, inventario, langfuse_utils
from tests.taller_mecanico.conftest import FakeLangfuseClient, client_con_json


def _padre(fake: FakeLangfuseClient, observation_id: str) -> str | None:
    return fake.jerarquia[observation_id]


def _nombre(fake: FakeLangfuseClient, observation_id: str) -> str:
    return fake.nombres[observation_id]


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


def test_flujo_completo_aprobado_deja_trace_id_en_las_5_filas_y_registra_scores(conn, monkeypatch):
    fake = FakeLangfuseClient()
    monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

    cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
    vehiculo_id = crm.alta_vehiculo(
        conn, cliente_id, matricula="1234ABC", marca="Seat", modelo="Ibiza", kilometraje=80000
    )
    pieza_id = inventario.alta_pieza(conn, "Pastillas", precio_unitario=40.0, stock_inicial=10)

    resultado = flujo_completo.procesar_flujo_completo(
        conn,
        mensaje="Mi coche hace un ruido raro al frenar por las mañanas",
        cliente_id=cliente_id,
        vehiculo_id=vehiculo_id,
        fecha_hora_cita="2026-09-01 10:00",
        piezas_candidatas=[pieza_id],
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
                    "pieza_id": pieza_id,
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "Pieza original disponible en inventario.",
                }
            ]
        ),
        evaluador_presupuesto_client=_client_evaluacion_presupuesto("aprobado"),
    )
    assert resultado["resultado_final"] == "aprobado"

    # --- decision_log: las 5 filas tienen langfuse_trace_id, y es EL MISMO
    # en las 5 -- una única traza para toda la interacción. ---
    rows = conn.execute(
        "SELECT agent, langfuse_trace_id, langfuse_observation_id FROM decision_log ORDER BY id"
    ).fetchall()
    assert len(rows) == 5
    trace_ids = {row["langfuse_trace_id"] for row in rows}
    assert len(trace_ids) == 1
    assert None not in trace_ids

    observation_ids = [row["langfuse_observation_id"] for row in rows]
    assert None not in observation_ids
    assert len(set(observation_ids)) == 5  # cada agente, su propia observación

    # --- Jerarquía REAL (parent_observation_id), no solo trace_id
    # compartido: interaccion_cliente (raíz) -> flujo_diagnostico ->
    # {router, diagnostico, evaluador_diagnostico}; interaccion_cliente ->
    # flujo_presupuesto -> {presupuestador, evaluador_presupuesto}. ---
    raiz_id = next(oid for oid, nombre in fake.nombres.items() if nombre == "interaccion_cliente")
    flujo_diag_id = next(
        oid for oid, nombre in fake.nombres.items() if nombre == "flujo_diagnostico"
    )
    flujo_pres_id = next(
        oid for oid, nombre in fake.nombres.items() if nombre == "flujo_presupuesto"
    )
    assert _padre(fake, raiz_id) is None
    assert _padre(fake, flujo_diag_id) == raiz_id
    assert _padre(fake, flujo_pres_id) == raiz_id

    fila_por_agente = {row["agent"]: row for row in rows}
    router_obs_id = fila_por_agente["router"]["langfuse_observation_id"]
    diagnostico_obs_id = fila_por_agente["diagnostico"]["langfuse_observation_id"]
    presupuestador_obs_id = fila_por_agente["presupuestador"]["langfuse_observation_id"]
    assert _padre(fake, router_obs_id) == flujo_diag_id
    assert _padre(fake, diagnostico_obs_id) == flujo_diag_id
    assert _padre(fake, presupuestador_obs_id) == flujo_pres_id
    # Los dos pasos del Evaluador cuelgan del span de su propio flujo, no
    # el uno del otro ni del span raíz directamente.
    evaluador_diag_obs_id = next(
        oid for oid, nombre in fake.nombres.items() if nombre == "evaluador_diagnostico"
    )
    evaluador_pres_obs_id = next(
        oid for oid, nombre in fake.nombres.items() if nombre == "evaluador_presupuesto"
    )
    assert _padre(fake, evaluador_diag_obs_id) == flujo_diag_id
    assert _padre(fake, evaluador_pres_obs_id) == flujo_pres_id

    # --- El veredicto del Evaluador quedó como SCORE de Langfuse sobre la
    # observación EVALUADA (Diagnóstico/Presupuestador), no sobre la
    # propia generación del Evaluador. ---
    assert len(fake.scores) == 2
    nombres_score = {s["name"] for s in fake.scores}
    assert nombres_score == {"veredicto_evaluador_diagnostico", "veredicto_evaluador_presupuesto"}
    for score in fake.scores:
        assert score["value"] == "aprobado"
        assert score["data_type"] == "CATEGORICAL"
        # El observation_id puntuado debe ser el de Diagnóstico/Presupuestador
        # (fila con ese agent en decision_log), nunca el del propio Evaluador.
        agente_puntuado = {
            "veredicto_evaluador_diagnostico": "diagnostico",
            "veredicto_evaluador_presupuesto": "presupuestador",
        }[score["name"]]
        fila_agente = next(r for r in rows if r["agent"] == agente_puntuado)
        assert score["observation_id"] == fila_agente["langfuse_observation_id"]


def test_flujo_completo_rechazo_no_llama_a_langfuse_para_pasos_no_ejecutados(conn, monkeypatch):
    """El caso obligatorio de rechazo (discos + 10.000 km): el Presupuestador
    nunca se invoca, así que tampoco debe abrirse ninguna observación de
    Langfuse para presupuestador/evaluador_presupuesto."""
    fake = FakeLangfuseClient()
    monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

    cliente_id = crm.alta_cliente(conn, nombre="Bea Ruiz", telefono="600111223")
    vehiculo_id = crm.alta_vehiculo(
        conn, cliente_id, matricula="9999XYZ", marca="Toyota", modelo="Corolla", kilometraje=10000
    )
    pieza_id = inventario.alta_pieza(conn, "Discos", precio_unitario=80.0, stock_inicial=5)

    resultado = flujo_completo.procesar_flujo_completo(
        conn,
        mensaje="ruido metálico al frenar",
        cliente_id=cliente_id,
        vehiculo_id=vehiculo_id,
        fecha_hora_cita="2026-09-01 10:00",
        piezas_candidatas=[pieza_id],
        horas_mano_obra=1.0,
        router_client=_client_router("consulta_tecnica", "diagnostico"),
        diagnostico_client=_client_diagnostico(
            ["Discos de freno desgastados, requieren cambio"], "Discos de freno", "alta"
        ),
        evaluador_diagnostico_client=_client_evaluacion_diagnostico(
            "escalado_humano", coherente=False
        ),
    )
    assert resultado["resultado_final"] == "escalado_humano"

    rows = conn.execute(
        "SELECT agent, langfuse_trace_id, langfuse_observation_id FROM decision_log ORDER BY id"
    ).fetchall()
    assert [r["agent"] for r in rows] == ["router", "diagnostico", "evaluador"]
    assert len({r["langfuse_trace_id"] for r in rows}) == 1

    # Jerarquía real: los tres siguen colgando de flujo_diagnostico, que a
    # su vez cuelga de interaccion_cliente -- ningún flujo_presupuesto ni
    # presupuestador se abrieron, porque el paso nunca se ejecutó.
    raiz_id = next(oid for oid, nombre in fake.nombres.items() if nombre == "interaccion_cliente")
    flujo_diag_id = next(
        oid for oid, nombre in fake.nombres.items() if nombre == "flujo_diagnostico"
    )
    assert _padre(fake, flujo_diag_id) == raiz_id
    for row in rows:
        assert _padre(fake, row["langfuse_observation_id"]) == flujo_diag_id
    assert "flujo_presupuesto" not in fake.nombres.values()

    # Un solo score: el veredicto sobre Diagnóstico. Ninguno sobre un
    # presupuesto que nunca se generó.
    assert len(fake.scores) == 1
    assert fake.scores[0]["name"] == "veredicto_evaluador_diagnostico"
    assert fake.scores[0]["value"] == "escalado_humano"


def test_flujo_completo_urgencia_no_abre_ninguna_observacion_de_agente(conn, monkeypatch):
    """La vía de urgencia se salta Diagnóstico/Evaluador/Presupuestador
    por completo -- solo debe existir la observación del Router (y el
    span raíz), ningún score."""
    fake = FakeLangfuseClient()
    monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

    cliente_id = crm.alta_cliente(conn, nombre="Carlos Ruiz", telefono="600111224")
    vehiculo_id = crm.alta_vehiculo(
        conn, cliente_id, matricula="1111AAA", marca="Seat", modelo="Ibiza", kilometraje=50000
    )

    resultado = flujo_completo.procesar_flujo_completo(
        conn,
        mensaje="se me han roto los frenos, no puedo parar el coche",
        cliente_id=cliente_id,
        vehiculo_id=vehiculo_id,
        router_client=_client_router("urgencia", "diagnostico"),
    )
    assert resultado["resultado_final"] == "escalado_humano_inmediato"

    rows = conn.execute(
        "SELECT agent, langfuse_trace_id, langfuse_observation_id FROM decision_log"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["agent"] == "router"
    assert rows[0]["langfuse_trace_id"] is not None
    assert fake.scores == []

    # El router cuelga directamente de flujo_diagnostico (la urgencia
    # nunca llega a abrir un span propio para Diagnóstico/Evaluador, ni
    # el interaccion_cliente llega a llamar a flujo_presupuesto).
    raiz_id = next(oid for oid, nombre in fake.nombres.items() if nombre == "interaccion_cliente")
    flujo_diag_id = next(
        oid for oid, nombre in fake.nombres.items() if nombre == "flujo_diagnostico"
    )
    assert _padre(fake, flujo_diag_id) == raiz_id
    assert _padre(fake, rows[0]["langfuse_observation_id"]) == flujo_diag_id
    assert "flujo_presupuesto" not in fake.nombres.values()
