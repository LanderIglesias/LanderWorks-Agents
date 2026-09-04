"""flujo_diagnostico.py — orquestación Router → Diagnóstico → Evaluador (hito 6).

Conecta los tres agentes ya construidos (router.py, diagnostico.py,
evaluador.py) SIN modificar su lógica interna de razonamiento (solo se
les añadió, en cada uno, un parámetro `parent_decision_id` opcional para
poder encadenarlos — la lógica de clasificación/diagnóstico/evaluación en
sí no cambió). La integración vive aquí, no dispersa dentro de cada
agente: este es el único módulo del paquete que importa a los tres.
router.py/diagnostico.py/evaluador.py siguen sin importarse entre sí
(verificado con tests AST en test_flujo_diagnostico.py) — cada uno sigue
siendo invocable de forma aislada, exactamente como en su propio hito.

Atajo de urgencia (hito 4), preservado sin cambios: si el Router
clasifica `agente_destino == "escalado_humano_inmediato"`, el flujo se
detiene ahí. Diagnóstico y Evaluador NUNCA se llaman para una urgencia
real.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import crm, diagnostico, evaluador, langfuse_utils, router

DESTINO_DIAGNOSTICO = "diagnostico"
DESTINO_URGENCIA = "escalado_humano_inmediato"


def procesar_mensaje(
    conn: sqlite3.Connection,
    mensaje: str,
    vehiculo_id: int | None = None,
    router_client: Any = None,
    diagnostico_client: Any = None,
    evaluador_client: Any = None,
) -> dict:
    """Clasifica `mensaje` con el Router y, según el destino resultante,
    conecta Diagnóstico → Evaluador en un único flujo trazado de extremo
    a extremo en `decision_log` vía `parent_decision_id`.

    - `agente_destino == "escalado_humano_inmediato"`: el flujo se
      detiene en el Router (atajo de urgencia del hito 4). Diagnóstico y
      Evaluador no se invocan.
    - `agente_destino == "diagnostico"`: se llama a
      `diagnostico.diagnosticar()` (encadenado al Router) y después a
      `evaluador.evaluar_diagnostico()` (encadenado a Diagnóstico), ambos
      con el mismo `vehiculo_id` -- cada uno consulta `crm.py` por su
      cuenta (no se comparte una única lectura ni una transacción), así
      que ven el mismo vehículo pero no necesariamente una fotografía
      atómica idéntica si algo lo modificara a mitad del flujo.
    - Cualquier otro destino (`herramienta_agenda`, `presupuestador`,
      `humano`, `ninguno`): no está conectado en este hito — se devuelve
      solo el resultado del Router.

    Devuelve {"router": {...}, "diagnostico": {...} | None,
    "evaluador": {...} | None, "resultado_final": str}, donde
    `resultado_final` es "escalado_humano_inmediato", "sin_conectar", o
    el `veredicto` del Evaluador (`aprobado`/`rechazado`/`escalado_humano`).

    Excepciones que se propagan tal cual (ninguna se traduce ni se
    envuelve): `ValueError` (mensaje vacío, desde router.py),
    `crm.VehiculoNoEncontradoError` (vehiculo_id no existe -- validado
    ANTES de llamar a ningún agente, ver nota abajo),
    `router.RouterRespuestaInvalidaError`,
    `diagnostico.DiagnosticoRespuestaInvalidaError`,
    `evaluador.EvaluadorRespuestaInvalidaError`.

    Nota sobre `vehiculo_id`: se valida su existencia una vez, al
    principio, antes de invocar a ningún agente -- así, si no existe, no
    queda una fila de Router escrita en decision_log sin explicación de
    por qué se abortó el resto del flujo (hallazgo de la revisión de
    seguridad de este hito). Diagnóstico y Evaluador vuelven a consultar
    `crm.py` cada uno por su cuenta con el mismo id (no se reutiliza una
    única lectura) -- ambos ven el mismo vehículo, pero no
    necesariamente una fotografía atómica idéntica si algo lo modificara
    a mitad del flujo (lecturas independientes en la misma conexión, no
    una transacción compartida entre las tres llamadas).

    `*_client` son inyectables para tests (evita llamadas reales a la API
    en cualquiera de los tres agentes)."""
    if vehiculo_id is not None:
        crm.obtener_vehiculo(conn, vehiculo_id)  # lanza VehiculoNoEncontradoError si no existe

    with langfuse_utils.traza_interaccion(
        "flujo_diagnostico", metadata={"vehiculo_id": vehiculo_id}
    ) as raiz:
        resultado_router = router.clasificar_mensaje(conn, mensaje, client=router_client)

        if resultado_router["agente_destino"] == DESTINO_URGENCIA:
            resultado = {
                "router": resultado_router,
                "diagnostico": None,
                "evaluador": None,
                "resultado_final": DESTINO_URGENCIA,
            }
            raiz.completar_span(output={"resultado_final": resultado["resultado_final"]})
            return resultado

        if resultado_router["agente_destino"] != DESTINO_DIAGNOSTICO:
            resultado = {
                "router": resultado_router,
                "diagnostico": None,
                "evaluador": None,
                "resultado_final": "sin_conectar",
            }
            raiz.completar_span(output={"resultado_final": resultado["resultado_final"]})
            return resultado

        resultado_diagnostico = diagnostico.diagnosticar(
            conn,
            sintomas=mensaje,
            vehiculo_id=vehiculo_id,
            parent_decision_id=resultado_router["decision_id"],
            client=diagnostico_client,
        )

        diagnostico_output = {
            "causas_probables": resultado_diagnostico["causas_probables"],
            "revisar_primero": resultado_diagnostico["revisar_primero"],
            "confianza": resultado_diagnostico["confianza"],
            "razonamiento": resultado_diagnostico["razonamiento"],
            # Necesarios para que evaluador.py pueda adjuntar su veredicto
            # como SCORE de Langfuse sobre ESTA observación (la de
            # Diagnóstico), no solo registrarlo en decision_log.
            "langfuse_trace_id": resultado_diagnostico.get("langfuse_trace_id"),
            "langfuse_observation_id": resultado_diagnostico.get("langfuse_observation_id"),
        }

        resultado_evaluador = evaluador.evaluar_diagnostico(
            conn,
            sintomas_originales=mensaje,
            diagnostico_output=diagnostico_output,
            vehiculo_id=vehiculo_id,
            parent_decision_id=resultado_diagnostico["decision_id"],
            client=evaluador_client,
        )

        resultado = {
            "router": resultado_router,
            "diagnostico": resultado_diagnostico,
            "evaluador": resultado_evaluador,
            "resultado_final": resultado_evaluador["veredicto"],
        }
        raiz.completar_span(output={"resultado_final": resultado["resultado_final"]})
        return resultado
