"""flujo_completo.py — orquestación end-to-end (hito 8, ÚLTIMO HITO).

Conecta flujo_diagnostico.py (hito 6) + agenda.py (hito 2) +
flujo_presupuesto.py (hito 7) en un único punto de entrada, sin
reescribir ni un ápice de la lógica de ningún agente ni herramienta —
pura orquestación sobre módulos ya construidos y probados por separado.

Recorrido completo, según taller-multiagente-arranque.md: Router →
Diagnóstico → Evaluador → (si aprobado) cita vía agenda.py →
Presupuestador → Evaluador → presupuesto final.

Dos puntos donde el flujo se detiene antes de llegar al final:
- Router deriva a "escalado_humano_inmediato" (urgencia, hito 4): el
  flujo se detiene ahí, exactamente igual que en flujo_diagnostico.py —
  Diagnóstico, Evaluador y Presupuestador NUNCA se llaman.
- El Evaluador no aprueba el diagnóstico (veredicto "rechazado" o
  "escalado_humano"): el flujo se detiene ahí — NUNCA se crea una cita
  ni se genera un presupuesto para un diagnóstico que el Evaluador no
  aprobó. Este es el caso obligatorio de rechazo del hito 8 (discos de
  freno + 10.000 km).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import agenda, crm, flujo_diagnostico, flujo_presupuesto, langfuse_utils

DESTINO_URGENCIA = "escalado_humano_inmediato"


def procesar_flujo_completo(
    conn: sqlite3.Connection,
    mensaje: str,
    cliente_id: int,
    vehiculo_id: int,
    fecha_hora_cita: str | None = None,
    duracion_cita_minutos: int = 60,
    piezas_candidatas: list[int] | None = None,
    horas_mano_obra: float | None = None,
    router_client: Any = None,
    diagnostico_client: Any = None,
    evaluador_diagnostico_client: Any = None,
    presupuestador_client: Any = None,
    evaluador_presupuesto_client: Any = None,
) -> dict:
    """Recorre el flujo completo: Router → Diagnóstico → Evaluador →
    (si aprobado) cita vía agenda.py → Presupuestador → Evaluador.

    `fecha_hora_cita`/`piezas_candidatas`/`horas_mano_obra` solo son
    necesarios si el flujo llega hasta pedir cita/presupuesto (Router
    deriva a "diagnostico" Y el Evaluador aprueba el diagnóstico) — si el
    flujo se detiene antes (urgencia, destino no conectado, diagnóstico
    rechazado/escalado), nunca se usan y pueden omitirse. Si el flujo SÍ
    llega ahí y falta alguno, se lanza `ValueError` con un mensaje claro,
    en vez de fallar más adelante con un error genérico de otro módulo.

    `cliente_id` se valida al principio (mismo principio que la
    validación de `vehiculo_id` ya existente dentro de
    `flujo_diagnostico.procesar_mensaje` desde el hito 6) — para no dejar
    filas de `decision_log` huérfanas si el cliente no existe. Además se
    verifica que `vehiculo_id` pertenezca realmente a `cliente_id`
    (hallazgo de la revisión de seguridad del hito 8): sin esta
    comprobación, un llamante podía emparejar el vehículo de un cliente
    con el `cliente_id` de otro para heredar su historial de fidelidad
    (visitas/quejas) en el cálculo de descuento del Presupuestador, sin
    ser dueño real de ese vehículo.

    Devuelve {"router", "diagnostico", "evaluador_diagnostico", "cita_id",
    "presupuestador", "evaluador_presupuesto", "resultado_final"}. Los
    campos posteriores al punto donde se detuvo el flujo quedan `None`.
    `resultado_final` es uno de: "escalado_humano_inmediato",
    "sin_conectar", el veredicto del Evaluador sobre el diagnóstico si no
    fue "aprobado", o el veredicto final del Evaluador sobre el
    presupuesto.

    Si el Presupuestador o el Evaluador del presupuesto fallan tras haber
    creado la cita (hallazgo de la revisión de seguridad del hito 8:
    antes esa cita quedaba huérfana en estado "pendiente", bloqueando el
    hueco del vehículo sin ninguna forma de recuperarlo desde el valor de
    retorno), la cita se cancela vía `agenda.cancelar_cita` antes de
    relanzar la excepción original.

    `*_client` son inyectables para tests (evita llamadas reales a la API
    en cualquiera de los cinco pasos)."""
    crm.obtener_cliente(conn, cliente_id)  # lanza ClienteNoEncontradoError si no existe
    vehiculo = crm.obtener_vehiculo(
        conn, vehiculo_id
    )  # lanza VehiculoNoEncontradoError si no existe
    if vehiculo["cliente_id"] != cliente_id:
        raise ValueError(f"El vehículo {vehiculo_id} no pertenece al cliente {cliente_id}.")

    with langfuse_utils.traza_interaccion(
        "interaccion_cliente", metadata={"cliente_id": cliente_id, "vehiculo_id": vehiculo_id}
    ) as raiz:
        resultado_diagnostico_flujo = flujo_diagnostico.procesar_mensaje(
            conn,
            mensaje,
            vehiculo_id=vehiculo_id,
            router_client=router_client,
            diagnostico_client=diagnostico_client,
            evaluador_client=evaluador_diagnostico_client,
        )

        base = {
            "router": resultado_diagnostico_flujo["router"],
            "diagnostico": resultado_diagnostico_flujo["diagnostico"],
            "evaluador_diagnostico": resultado_diagnostico_flujo["evaluador"],
            "cita_id": None,
            "presupuestador": None,
            "evaluador_presupuesto": None,
        }

        if resultado_diagnostico_flujo["resultado_final"] in (DESTINO_URGENCIA, "sin_conectar"):
            resultado = {**base, "resultado_final": resultado_diagnostico_flujo["resultado_final"]}
            raiz.completar_span(output={"resultado_final": resultado["resultado_final"]})
            return resultado

        veredicto_diagnostico = resultado_diagnostico_flujo["evaluador"]["veredicto"]
        if veredicto_diagnostico != "aprobado":
            resultado = {**base, "resultado_final": veredicto_diagnostico}
            raiz.completar_span(output={"resultado_final": resultado["resultado_final"]})
            return resultado

        if fecha_hora_cita is None:
            raise ValueError(
                "fecha_hora_cita es obligatorio: el diagnóstico fue aprobado, el flujo necesita "
                "crear una cita antes de poder presupuestar."
            )
        if not piezas_candidatas or horas_mano_obra is None:
            raise ValueError(
                "piezas_candidatas (no vacío) y horas_mano_obra son obligatorios: el diagnóstico "
                "fue aprobado, el flujo necesita generar un presupuesto."
            )
        if horas_mano_obra < 0:
            raise ValueError(f"horas_mano_obra no puede ser negativo: {horas_mano_obra!r}.")
        if duracion_cita_minutos <= 0:
            raise ValueError(f"duracion_cita_minutos debe ser positivo: {duracion_cita_minutos!r}.")

        cita_id = agenda.crear_cita(
            conn, vehiculo_id, fecha_hora_cita, mensaje, duracion_minutos=duracion_cita_minutos
        )
        base["cita_id"] = cita_id

        try:
            resultado_presupuesto_flujo = flujo_presupuesto.procesar_presupuesto(
                conn,
                cliente_id=cliente_id,
                vehiculo_id=vehiculo_id,
                cita_id=cita_id,
                diagnostico_aprobado=resultado_diagnostico_flujo["diagnostico"],
                piezas_candidatas=piezas_candidatas,
                horas_mano_obra=horas_mano_obra,
                intencion_original=resultado_diagnostico_flujo["router"]["intencion"],
                parent_decision_id=resultado_diagnostico_flujo["evaluador"]["decision_id"],
                presupuestador_client=presupuestador_client,
                evaluador_client=evaluador_presupuesto_client,
            )
        except Exception:
            # La cita ya está comprometida (commit propio de agenda.crear_cita);
            # si el paso de presupuesto falla, no debe quedar bloqueando el
            # hueco del vehículo sin ninguna forma de recuperarla desde aquí.
            agenda.cancelar_cita(conn, cita_id)
            raise

        resultado = {
            **base,
            "presupuestador": resultado_presupuesto_flujo["presupuestador"],
            "evaluador_presupuesto": resultado_presupuesto_flujo["evaluador"],
            "resultado_final": resultado_presupuesto_flujo["resultado_final"],
        }
        raiz.completar_span(output={"resultado_final": resultado["resultado_final"]})
        return resultado
