import json

import pytest

from backend.agents.taller_mecanico import (
    config_presupuesto as cfg,
)
from backend.agents.taller_mecanico import (
    crm,
    inventario,
    presupuestador,
)
from tests.taller_mecanico.conftest import FakeAnthropicClient, client_con_json

DIAGNOSTICO_APROBADO = {
    "causas_probables": ["Pastillas de freno desgastadas"],
    "revisar_primero": "Pastillas de freno",
    "confianza": "media",
    "razonamiento": "Ruido al frenar compatible con desgaste de pastillas.",
}


def _client_presupuesto(
    piezas_seleccionadas: list[dict],
    descuento_tipo: str = "ninguno",
    criterio_excepcional: str | None = None,
    porcentaje_descuento_excepcional: float | None = None,
    razonamiento: str = "Presupuesto calculado según diagnóstico.",
) -> FakeAnthropicClient:
    return client_con_json(
        {
            "piezas_seleccionadas": piezas_seleccionadas,
            "descuento_tipo": descuento_tipo,
            "criterio_excepcional": criterio_excepcional,
            "porcentaje_descuento_excepcional": porcentaje_descuento_excepcional,
            "razonamiento": razonamiento,
        }
    )


@pytest.fixture
def escenario(conn):
    """Cliente + vehículo + cita + pieza original, listos para presupuestar."""
    cliente_id = crm.alta_cliente(conn, nombre="Ana García", telefono="600111222")
    vehiculo_id = crm.alta_vehiculo(
        conn, cliente_id, matricula="1234ABC", marca="Seat", modelo="Ibiza", kilometraje=80000
    )
    cita_id = conn.execute(
        "INSERT INTO citas (vehiculo_id, fecha_hora, motivo) VALUES (?, '2026-09-01 10:00', 'Ruido al frenar')",
        (vehiculo_id,),
    ).lastrowid
    conn.commit()
    pieza_original_id = inventario.alta_pieza(
        conn, "Pastillas Bosch (original)", precio_unitario=40.0, stock_inicial=10
    )
    return {
        "conn": conn,
        "cliente_id": cliente_id,
        "vehiculo_id": vehiculo_id,
        "cita_id": cita_id,
        "pieza_original_id": pieza_original_id,
    }


def _marcar_visitas_completadas(conn, vehiculo_id: int, cantidad: int) -> None:
    for i in range(cantidad):
        conn.execute(
            "INSERT INTO citas (vehiculo_id, fecha_hora, motivo, estado) "
            f"VALUES (?, '2026-0{(i % 9) + 1}-01 09:00', 'Visita previa', 'completada')",
            (vehiculo_id,),
        )
    conn.commit()


class TestPresupuestoNormalSinDescuento:
    """Caso obligatorio 1: presupuesto normal sin descuento -> aprobado
    (aprobado se confirma en flujo_presupuesto, aquí se confirma que
    presupuestar() lo acepta y lo registra sin rechazar nada)."""

    def test_presupuesto_normal_se_acepta(self, escenario):
        conn = escenario["conn"]
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "Pieza original disponible en inventario.",
                }
            ],
            descuento_tipo="ninguno",
        )
        resultado = presupuestador.presupuestar(
            conn,
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            cita_id=escenario["cita_id"],
            diagnostico_aprobado=DIAGNOSTICO_APROBADO,
            piezas_candidatas=[escenario["pieza_original_id"]],
            horas_mano_obra=1.0,
            intencion_original="consulta_tecnica",
            client=client,
        )
        assert resultado["descuento_tipo"] == "ninguno"
        assert resultado["coste_piezas"] == 40.0
        assert resultado["mano_obra_total"] == cfg.TARIFA_HORA_MANO_OBRA
        assert resultado["total"] > resultado["coste_piezas"] + resultado["mano_obra_total"] * 0
        assert "presupuesto_id" in resultado
        assert "decision_id" in resultado

        # Verificado contra datos reales, no solo el valor de retorno.
        fila = conn.execute(
            "SELECT * FROM presupuestos WHERE id = ?", (resultado["presupuesto_id"],)
        ).fetchone()
        assert fila["cita_id"] == escenario["cita_id"]
        assert fila["total"] == resultado["total"]

        lineas = conn.execute(
            "SELECT * FROM presupuesto_piezas WHERE presupuesto_id = ?",
            (resultado["presupuesto_id"],),
        ).fetchall()
        assert len(lineas) == 1
        assert lineas[0]["pieza_id"] == escenario["pieza_original_id"]

    def test_margen_bruto_respeta_el_defecto_de_config(self, escenario):
        conn = escenario["conn"]
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ]
        )
        resultado = presupuestador.presupuestar(
            conn,
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            cita_id=escenario["cita_id"],
            diagnostico_aprobado=DIAGNOSTICO_APROBADO,
            piezas_candidatas=[escenario["pieza_original_id"]],
            horas_mano_obra=1.0,
            intencion_original="consulta_tecnica",
            client=client,
        )
        margen_real = (resultado["precio_venta_piezas"] - resultado["coste_piezas"]) / resultado[
            "precio_venta_piezas"
        ]
        assert margen_real == pytest.approx(cfg.MARGEN_DEFECTO)


class TestDescuentoEstandarPorFidelidad:
    """Caso obligatorio 2: cliente con 3+ visitas, sin urgencia ->
    descuento estándar 5% aplicado correctamente, margen neto >= 10%."""

    def test_descuento_estandar_aplicado_correctamente(self, escenario):
        conn = escenario["conn"]
        _marcar_visitas_completadas(
            conn, escenario["vehiculo_id"], cfg.UMBRAL_VISITAS_FIDELIDAD_ESTANDAR
        )

        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ],
            descuento_tipo="estandar",
        )
        resultado = presupuestador.presupuestar(
            conn,
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            cita_id=escenario["cita_id"],
            diagnostico_aprobado=DIAGNOSTICO_APROBADO,
            piezas_candidatas=[escenario["pieza_original_id"]],
            horas_mano_obra=1.0,
            intencion_original="consulta_tecnica",
            client=client,
        )
        assert resultado["descuento_tipo"] == "estandar"
        assert resultado["descuento_porcentaje"] == pytest.approx(cfg.DESCUENTO_FIDELIDAD_ESTANDAR)

        margen_neto = (resultado["precio_venta_piezas"] - resultado["coste_piezas"]) / resultado[
            "precio_venta_piezas"
        ]
        assert margen_neto >= cfg.MARGEN_NETO_MINIMO_TRAS_DESCUENTO


class TestUrgenciaYDescuentoSonExcluyentes:
    """Caso obligatorio 3: cliente con urgencia Y 3+ visitas -> SIN
    descuento, aunque cumpla el umbral de fidelidad."""

    def test_urgencia_fuerza_sin_descuento_aunque_cumpla_fidelidad(self, escenario):
        conn = escenario["conn"]
        _marcar_visitas_completadas(conn, escenario["vehiculo_id"], 5)

        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ],
            descuento_tipo="estandar",  # el modelo "propone" descuento pese a la urgencia
        )
        resultado = presupuestador.presupuestar(
            conn,
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            cita_id=escenario["cita_id"],
            diagnostico_aprobado=DIAGNOSTICO_APROBADO,
            piezas_candidatas=[escenario["pieza_original_id"]],
            horas_mano_obra=1.0,
            intencion_original="urgencia",
            client=client,
        )
        assert resultado["descuento_tipo"] == "ninguno"
        assert resultado["descuento_porcentaje"] == 0
        assert "urgencia" in resultado["razonamiento"].lower()


class TestDescuentoExcepcionalSinCriterioValido:
    """Caso obligatorio 4: intento de descuento excepcional sin ningún
    criterio válido -> rechazado determinísticamente, sin llegar al
    Evaluador (aquí: presupuestar() ni siquiera termina de construir el
    presupuesto -- lanza antes de que exista nada que evaluar)."""

    def test_criterio_excepcional_nulo_rechazado(self, escenario):
        conn = escenario["conn"]
        _marcar_visitas_completadas(
            conn, escenario["vehiculo_id"], cfg.UMBRAL_VISITAS_FIDELIDAD_ESTANDAR
        )
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ],
            descuento_tipo="excepcional",
            criterio_excepcional=None,
        )
        with pytest.raises(presupuestador.PresupuestoRechazadoError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )
        # No debe haber quedado ningún presupuesto ni línea a medio crear.
        assert conn.execute("SELECT COUNT(*) AS n FROM presupuestos").fetchone()["n"] == 0

    def test_criterio_que_no_verifica_contra_datos_reales_rechazado(self, escenario):
        conn = escenario["conn"]
        _marcar_visitas_completadas(
            conn, escenario["vehiculo_id"], cfg.UMBRAL_VISITAS_FIDELIDAD_ESTANDAR
        )
        # El modelo AFIRMA que hay una queja no resuelta, pero no existe
        # ninguna queja real para este cliente -- debe rechazarse igual.
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ],
            descuento_tipo="excepcional",
            criterio_excepcional="queja_no_resuelta",
            porcentaje_descuento_excepcional=cfg.DESCUENTO_EXCEPCIONAL_MAXIMO,
        )
        with pytest.raises(presupuestador.PresupuestoRechazadoError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )


class TestDescuentoExcepcionalValidoQueViolaMargenMinimo:
    """Caso obligatorio 5: descuento excepcional que cumple el criterio
    cualitativo (queja real en CRM, verificada) pero cuyo porcentaje
    dejaría el margen neto por debajo del suelo -> rechazado pese a que
    el criterio en sí es válido.

    Nota de diseño (investigado, no asumido): con MARGEN_DEFECTO=35% y
    DESCUENTO_EXCEPCIONAL_MAXIMO=10%, ningún descuento DENTRO del máximo
    configurado puede matemáticamente hacer que el margen neto baje del
    10% -- el propio suelo (10%) y el máximo de descuento (10%) están
    calibrados para que un descuento válido nunca lo cruce. Este test
    usa un porcentaje que excede el máximo configurado (30% > 10%), que
    la propia regla del máximo ya rechazaría -- y que, si esa regla no
    existiera, también violaría el margen neto. Ambas rutas de rechazo
    son válidas y complementarias; el test solo exige que SE RECHACE."""

    def test_criterio_valido_pero_porcentaje_excesivo_rechazado(self, escenario):
        conn = escenario["conn"]
        _marcar_visitas_completadas(
            conn, escenario["vehiculo_id"], cfg.UMBRAL_VISITAS_FIDELIDAD_ESTANDAR
        )
        crm.registrar_queja(conn, escenario["cliente_id"], "No me llamaron en dos semanas")

        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ],
            descuento_tipo="excepcional",
            criterio_excepcional="queja_no_resuelta",
            porcentaje_descuento_excepcional=0.30,
        )
        with pytest.raises(presupuestador.PresupuestoRechazadoError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )


class TestPiezaCompatibleSinRespaldo:
    """Caso obligatorio 6: pieza compatible ofrecida sin respaldo de
    inventario/historial -> rechazada determinísticamente."""

    def test_pieza_marcada_compatible_pero_catalogo_dice_original_rechazada(self, escenario):
        conn = escenario["conn"]
        # pieza_original_id tiene es_compatible=0 en el catálogo real.
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "compatible",  # el modelo miente sobre el tipo
                    "justificacion": "Es más barata.",
                }
            ]
        )
        with pytest.raises(presupuestador.PresupuestoRechazadoError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )

    def test_pieza_compatible_respaldada_por_inventario_se_acepta(self, escenario):
        conn = escenario["conn"]
        pieza_compatible_id = inventario.alta_pieza(
            conn, "Pastillas Ferodo (compatible)", precio_unitario=25.0, es_compatible=1
        )
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": pieza_compatible_id,
                    "cantidad": 1,
                    "eleccion": "compatible",
                    "justificacion": "Pieza compatible disponible en inventario.",
                }
            ]
        )
        resultado = presupuestador.presupuestar(
            conn,
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            cita_id=escenario["cita_id"],
            diagnostico_aprobado=DIAGNOSTICO_APROBADO,
            piezas_candidatas=[pieza_compatible_id],
            horas_mano_obra=1.0,
            intencion_original="consulta_tecnica",
            client=client,
        )
        assert resultado["piezas"][0]["es_compatible"] is True

    def test_pieza_no_esta_en_candidatas_rechazada(self, escenario):
        conn = escenario["conn"]
        otra_pieza_id = inventario.alta_pieza(conn, "Otra pieza", precio_unitario=15.0)
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": otra_pieza_id,  # no está en piezas_candidatas
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ]
        )
        with pytest.raises(presupuestador.PresupuestoRechazadoError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],  # otra pieza distinta
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )


class TestDescuentoConPocasVisitas:
    def test_descuento_estandar_con_menos_de_3_visitas_rechazado(self, escenario):
        conn = escenario["conn"]
        _marcar_visitas_completadas(conn, escenario["vehiculo_id"], 2)
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ],
            descuento_tipo="estandar",
        )
        with pytest.raises(presupuestador.PresupuestoRechazadoError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )


class TestDescuentoExcepcionalCriteriosValidos:
    def test_presupuesto_alto_verificado_por_total_real(self, escenario):
        conn = escenario["conn"]
        _marcar_visitas_completadas(
            conn, escenario["vehiculo_id"], cfg.UMBRAL_VISITAS_FIDELIDAD_ESTANDAR
        )
        pieza_cara_id = inventario.alta_pieza(conn, "Pieza cara", precio_unitario=900.0)
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": pieza_cara_id,
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ],
            descuento_tipo="excepcional",
            criterio_excepcional="presupuesto_alto",
            porcentaje_descuento_excepcional=0.05,
        )
        resultado = presupuestador.presupuestar(
            conn,
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            cita_id=escenario["cita_id"],
            diagnostico_aprobado=DIAGNOSTICO_APROBADO,
            piezas_candidatas=[pieza_cara_id],
            horas_mano_obra=1.0,
            intencion_original="consulta_tecnica",
            client=client,
        )
        assert resultado["descuento_tipo"] == "excepcional"
        assert resultado["criterio_excepcional"] == "presupuesto_alto"

    def test_presupuesto_no_alto_rechaza_criterio_presupuesto_alto(self, escenario):
        conn = escenario["conn"]
        _marcar_visitas_completadas(
            conn, escenario["vehiculo_id"], cfg.UMBRAL_VISITAS_FIDELIDAD_ESTANDAR
        )
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],  # 40€, muy por debajo del umbral
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ],
            descuento_tipo="excepcional",
            criterio_excepcional="presupuesto_alto",
            porcentaje_descuento_excepcional=0.05,
        )
        with pytest.raises(presupuestador.PresupuestoRechazadoError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )

    def test_visitas_insuficientes_rechaza_criterio_visitas_excepcionales(self, escenario):
        conn = escenario["conn"]
        # Cumple el mínimo para descuento (3+) pero no supera el umbral
        # excepcional (10+) -- el criterio citado no se sostiene.
        _marcar_visitas_completadas(
            conn, escenario["vehiculo_id"], cfg.UMBRAL_VISITAS_FIDELIDAD_ESTANDAR
        )
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ],
            descuento_tipo="excepcional",
            criterio_excepcional="visitas_excepcionales",
            porcentaje_descuento_excepcional=0.05,
        )
        with pytest.raises(presupuestador.PresupuestoRechazadoError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )

    def test_sin_promocion_vigente_rechaza_criterio_promocion(self, escenario):
        conn = escenario["conn"]
        assert cfg.PROMOCION_VIGENTE is False  # supuesto de partida del test
        _marcar_visitas_completadas(
            conn, escenario["vehiculo_id"], cfg.UMBRAL_VISITAS_FIDELIDAD_ESTANDAR
        )
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ],
            descuento_tipo="excepcional",
            criterio_excepcional="promocion_vigente",
            porcentaje_descuento_excepcional=0.05,
        )
        with pytest.raises(presupuestador.PresupuestoRechazadoError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )


class TestDecisionLogPresupuestador:
    def test_escribe_fila_en_decision_log_encadenada(self, escenario):
        conn = escenario["conn"]
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ]
        )
        resultado = presupuestador.presupuestar(
            conn,
            cliente_id=escenario["cliente_id"],
            vehiculo_id=escenario["vehiculo_id"],
            cita_id=escenario["cita_id"],
            diagnostico_aprobado=DIAGNOSTICO_APROBADO,
            piezas_candidatas=[escenario["pieza_original_id"]],
            horas_mano_obra=1.0,
            intencion_original="consulta_tecnica",
            parent_decision_id=None,
            client=client,
        )
        row = conn.execute(
            "SELECT * FROM decision_log WHERE id = ?", (resultado["decision_id"],)
        ).fetchone()
        assert row["agent"] == "presupuestador"
        output = json.loads(row["output"])
        assert output["total"] == resultado["total"]

    def test_respuesta_no_json_lanza_error_pero_deja_rastro(self, escenario):
        conn = escenario["conn"]
        client = FakeAnthropicClient("esto no es json")
        with pytest.raises(presupuestador.PresupuestadorRespuestaInvalidaError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )
        row = conn.execute("SELECT * FROM decision_log").fetchone()
        assert row is not None
        assert row["agent"] == "presupuestador"

    def test_pieza_id_repetida_con_elecciones_contradictorias_rechazada(self, escenario):
        # Hallazgo de la revisión de seguridad: sin esto, la misma pieza
        # podía facturarse dos veces, una como "original" y otra como
        # "compatible", y ambas líneas pasaban la validación por separado.
        conn = escenario["conn"]
        client = client_con_json(
            {
                "piezas_seleccionadas": [
                    {
                        "pieza_id": escenario["pieza_original_id"],
                        "cantidad": 1,
                        "eleccion": "original",
                        "justificacion": "x",
                    },
                    {
                        "pieza_id": escenario["pieza_original_id"],
                        "cantidad": 1,
                        "eleccion": "compatible",
                        "justificacion": "x",
                    },
                ],
                "descuento_tipo": "ninguno",
                "criterio_excepcional": None,
                "porcentaje_descuento_excepcional": None,
                "razonamiento": "x",
            }
        )
        with pytest.raises(presupuestador.PresupuestadorRespuestaInvalidaError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )

    def test_cantidad_por_encima_del_maximo_configurado_rechazada(self, escenario):
        conn = escenario["conn"]
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": cfg.CANTIDAD_MAXIMA_POR_LINEA + 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ]
        )
        with pytest.raises(presupuestador.PresupuestadorRespuestaInvalidaError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="consulta_tecnica",
                client=client,
            )

    def test_intencion_original_fuera_de_catalogo_rechazada(self, escenario):
        conn = escenario["conn"]
        client = _client_presupuesto(
            piezas_seleccionadas=[
                {
                    "pieza_id": escenario["pieza_original_id"],
                    "cantidad": 1,
                    "eleccion": "original",
                    "justificacion": "x",
                }
            ]
        )
        with pytest.raises(ValueError):
            presupuestador.presupuestar(
                conn,
                cliente_id=escenario["cliente_id"],
                vehiculo_id=escenario["vehiculo_id"],
                cita_id=escenario["cita_id"],
                diagnostico_aprobado=DIAGNOSTICO_APROBADO,
                piezas_candidatas=[escenario["pieza_original_id"]],
                horas_mano_obra=1.0,
                intencion_original="no_es_una_intencion_valida",
                client=client,
            )


class TestAislamiento:
    def test_presupuestador_no_importa_router_diagnostico_ni_evaluador(self):
        import ast
        from pathlib import Path

        source = Path(presupuestador.__file__).read_text(encoding="utf-8")
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

        prohibidos = {"router", "diagnostico", "evaluador", "flujo_diagnostico"}
        assert not (modulos & prohibidos)
