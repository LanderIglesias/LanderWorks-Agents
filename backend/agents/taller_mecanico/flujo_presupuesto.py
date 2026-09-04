"""flujo_presupuesto.py — orquestación Presupuestador → Evaluador (hito 7).

Mismo patrón que `flujo_diagnostico.py` (hito 6): conecta dos agentes ya
construidos SIN modificar su lógica interna, en un módulo de
orquestación separado — `presupuestador.py` y `evaluador.py` siguen sin
importarse entre sí (verificado con un test AST), este es el único
módulo que importa a los dos.

A diferencia de `flujo_diagnostico.py`, aquí no hay atajo de urgencia
que gestionar: la exclusión mutua urgencia/descuento ya la aplica
`presupuestador.py` internamente (regla determinista, no de
orquestación) antes de que este módulo entre en juego.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import evaluador, langfuse_utils, presupuestador


def procesar_presupuesto(
    conn: sqlite3.Connection,
    cliente_id: int,
    vehiculo_id: int,
    cita_id: int,
    diagnostico_aprobado: dict,
    piezas_candidatas: list[int],
    horas_mano_obra: float,
    intencion_original: str,
    parent_decision_id: int | None = None,
    presupuestador_client: Any = None,
    evaluador_client: Any = None,
) -> dict:
    """Genera un presupuesto (`presupuestador.presupuestar()`) y lo pasa
    por el Evaluador (`evaluador.evaluar_presupuesto()`), encadenados vía
    `parent_decision_id` en `decision_log`.

    Si `presupuestador.presupuestar()` rechaza el presupuesto por una
    regla de negocio dura (`presupuestador.PresupuestoRechazadoError`) o
    por una respuesta del modelo mal formada
    (`presupuestador.PresupuestadorRespuestaInvalidaError`), la excepción
    se propaga tal cual y el Evaluador NUNCA se invoca — un presupuesto
    que no pasó las reglas duras no llega a evaluarse, se corrige o se
    descarta antes.

    Devuelve {"presupuestador": {...}, "evaluador": {...},
    "resultado_final": <veredicto del Evaluador>}.

    `parent_decision_id`, si se pasa, encadena la fila del Presupuestador
    con la decisión que originó esta llamada (típicamente el diagnóstico
    aprobado). `*_client` son inyectables para tests."""
    with langfuse_utils.traza_interaccion(
        "flujo_presupuesto", metadata={"cliente_id": cliente_id, "vehiculo_id": vehiculo_id}
    ) as raiz:
        resultado_presupuestador = presupuestador.presupuestar(
            conn,
            cliente_id=cliente_id,
            vehiculo_id=vehiculo_id,
            cita_id=cita_id,
            diagnostico_aprobado=diagnostico_aprobado,
            piezas_candidatas=piezas_candidatas,
            horas_mano_obra=horas_mano_obra,
            intencion_original=intencion_original,
            parent_decision_id=parent_decision_id,
            client=presupuestador_client,
        )

        presupuesto_output = {
            "piezas": resultado_presupuestador["piezas"],
            "coste_piezas": resultado_presupuestador["coste_piezas"],
            "margen_aplicado": resultado_presupuestador["margen_aplicado"],
            "precio_venta_piezas": resultado_presupuestador["precio_venta_piezas"],
            "mano_obra_horas": resultado_presupuestador["mano_obra_horas"],
            "mano_obra_total": resultado_presupuestador["mano_obra_total"],
            "descuento_tipo": resultado_presupuestador["descuento_tipo"],
            "descuento_porcentaje": resultado_presupuestador["descuento_porcentaje"],
            "criterio_excepcional": resultado_presupuestador["criterio_excepcional"],
            "total": resultado_presupuestador["total"],
            "razonamiento": resultado_presupuestador["razonamiento"],
            # Necesarios para que evaluador.py pueda adjuntar su veredicto
            # como SCORE de Langfuse sobre ESTA observación (la del
            # Presupuestador), no solo registrarlo en decision_log.
            "langfuse_trace_id": resultado_presupuestador.get("langfuse_trace_id"),
            "langfuse_observation_id": resultado_presupuestador.get("langfuse_observation_id"),
        }

        resultado_evaluador = evaluador.evaluar_presupuesto(
            conn,
            diagnostico_aprobado=diagnostico_aprobado,
            presupuesto_output=presupuesto_output,
            cliente_id=cliente_id,
            vehiculo_id=vehiculo_id,
            parent_decision_id=resultado_presupuestador["decision_id"],
            client=evaluador_client,
        )

        # Hallazgo de la revisión de seguridad: sin esto, la fila real de
        # `presupuestos` se queda en 'borrador' para siempre, y nada distingue
        # en la BD un presupuesto aprobado de uno que el Evaluador rechazó o
        # escaló -- el veredicto solo quedaba en decision_log. El esquema no
        # tiene un estado 'escalado_humano' (solo borrador/aprobado/rechazado/
        # enviado, DDL del hito 1); "escalado_humano" se guarda como
        # 'rechazado' porque comparte la propiedad que de verdad importa aquí:
        # no debe enviarse al cliente sin más acción.
        nuevo_estado = "aprobado" if resultado_evaluador["veredicto"] == "aprobado" else "rechazado"
        conn.execute(
            "UPDATE presupuestos SET estado = ? WHERE id = ?",
            (nuevo_estado, resultado_presupuestador["presupuesto_id"]),
        )
        conn.commit()

        resultado = {
            "presupuestador": resultado_presupuestador,
            "evaluador": resultado_evaluador,
            "resultado_final": resultado_evaluador["veredicto"],
        }
        raiz.completar_span(output={"resultado_final": resultado["resultado_final"]})
        return resultado
