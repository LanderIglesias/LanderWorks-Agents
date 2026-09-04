"""diagnostico.py — agente Diagnóstico (hito 4, segundo paso).

AISLADO: se prueba con mensajes de prueba fijos (`test_diagnostico.py`,
cliente Anthropic mockeado, más `test_diagnostico_live.py` contra la API
real). No se conecta al Router ni al Evaluador todavía — eso es el hito 6,
según taller-multiagente-arranque.md. Sí usa `crm.py` (hito 2) para leer
el historial y los datos del vehículo — esa es una herramienta
determinista, no otro agente; "aislado" aquí significa "sin conectar a
otros AGENTES", no "sin usar las herramientas ya construidas" (así lo
pidió explícitamente el encargo de este hito: "usa crm.py, no dupliques
esa lógica").
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv

from . import crm, langfuse_utils

load_dotenv(override=False)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 768

NIVELES_CONFIANZA_VALIDOS = ("alta", "media", "baja")

_SYSTEM_PROMPT = """Eres el agente de Diagnóstico de un taller mecánico. Recibes los \
síntomas que describe un cliente, opcionalmente el historial y los datos de su \
vehículo, y opcionalmente códigos OBD. Tu única tarea es proponer un diagnóstico \
preliminar -- no resuelves nada tú mismo, no reservas citas, no das precios.

Debes:
1. Proponer causas probables, ORDENADAS de la más probable a la menos probable.
2. Indicar qué revisar primero (la comprobación más barata/rápida que confirmaría \
o descartaría la causa más probable).
3. Dar un nivel de confianza explícito: "alta", "media" o "baja". Usa "media" o \
"baja" cuando el diagnóstico definitivo requiera una inspección física que no \
puedes hacer a distancia -- no inventes certeza que no tienes.

Responde ÚNICAMENTE con un objeto JSON, sin texto antes ni después ni bloques de \
código, con exactamente estas claves:
{"causas_probables": ["<causa más probable>", "<siguiente>", ...], \
"revisar_primero": "<qué revisar primero>", \
"confianza": "alta" | "media" | "baja", \
"razonamiento": "<explicación breve, en español, de tu diagnóstico>"}
"""

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class DiagnosticoRespuestaInvalidaError(ValueError):
    """La respuesta del modelo no es JSON válido, le faltan claves esperadas,
    o alguno de sus valores no es del tipo/catálogo esperado."""


def _get_client() -> Any:
    # Import perezoso: si el llamante inyecta su propio `client` (como
    # hacen todos los tests), el paquete `anthropic` ni siquiera necesita
    # estar configurado con una API key real.
    import anthropic

    return anthropic.Anthropic()


def _neutralizar_delimitadores(texto: str) -> str:
    """Sustituye < y > por variantes visualmente similares (‹ ›), mismo
    patrón que evaluador._neutralizar_delimitadores (replicado aquí, no
    importado, para preservar el aislamiento entre agentes). Hallazgo de
    la revisión de seguridad del hito 8: `cita['motivo']` -- texto libre
    que en última instancia puede originarse en algo que el cliente
    escribió al pedir esa cita -- se interpolaba en el prompt de
    Diagnóstico sin ninguna neutralización, a diferencia de evaluador.py
    (que sí la aplica al mismo campo desde el hito 5)."""
    return texto.replace("<", "‹").replace(">", "›")


def _construir_contexto(
    conn: sqlite3.Connection,
    sintomas: str,
    vehiculo_id: int | None,
    codigos_obd: list[str] | None,
) -> str:
    """Arma el mensaje que se envía al modelo: síntomas + contexto del
    vehículo (vía crm.py, sin duplicar su lógica de acceso a datos) +
    códigos OBD si los hay."""
    partes = [f"Síntomas descritos por el cliente: {sintomas}"]

    if vehiculo_id is not None:
        vehiculo = crm.obtener_vehiculo(conn, vehiculo_id)
        partes.append(
            "Vehículo: {marca} {modelo} ({anio}), {km} km".format(
                marca=vehiculo["marca"],
                modelo=vehiculo["modelo"],
                anio=vehiculo["anio"] or "año desconocido",
                km=vehiculo["kilometraje"],
            )
        )

        historial = crm.historial_vehiculo(conn, vehiculo_id)
        if historial:
            lineas_historial = [
                f"- {cita['fecha_hora']}: {_neutralizar_delimitadores(cita['motivo'])} "
                f"(estado: {cita['estado']})"
                for cita in historial
            ]
            partes.append("Historial de citas de este vehículo:\n" + "\n".join(lineas_historial))
        else:
            partes.append("Historial de citas de este vehículo: sin citas previas.")

    if codigos_obd:
        partes.append("Códigos OBD reportados por el cliente: " + ", ".join(codigos_obd))

    return "\n\n".join(partes)


def _extraer_json(texto: str) -> dict:
    match = _JSON_OBJECT_RE.search(texto)
    if match is None:
        raise DiagnosticoRespuestaInvalidaError(f"No se encontró ningún objeto JSON en: {texto!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise DiagnosticoRespuestaInvalidaError(f"JSON inválido: {exc}") from exc


def _validar_diagnostico(data: dict) -> dict:
    faltantes = {"causas_probables", "revisar_primero", "confianza", "razonamiento"} - data.keys()
    if faltantes:
        raise DiagnosticoRespuestaInvalidaError(f"Faltan claves en la respuesta: {faltantes}")

    causas = data["causas_probables"]
    if not isinstance(causas, list) or not causas:
        raise DiagnosticoRespuestaInvalidaError(
            f"causas_probables debe ser una lista no vacía, se recibió: {causas!r}"
        )
    if not all(isinstance(c, str) and c.strip() for c in causas):
        raise DiagnosticoRespuestaInvalidaError(
            f"causas_probables debe contener solo texto no vacío: {causas!r}"
        )

    if not isinstance(data["revisar_primero"], str) or not data["revisar_primero"].strip():
        raise DiagnosticoRespuestaInvalidaError(
            f"revisar_primero debe ser texto no vacío: {data['revisar_primero']!r}"
        )

    if data["confianza"] not in NIVELES_CONFIANZA_VALIDOS:
        raise DiagnosticoRespuestaInvalidaError(f"confianza desconocida: {data['confianza']!r}")

    if not isinstance(data["razonamiento"], str) or not data["razonamiento"].strip():
        raise DiagnosticoRespuestaInvalidaError(
            f"razonamiento debe ser texto no vacío: {data['razonamiento']!r}"
        )

    return data


def _registrar_decision(
    conn: sqlite3.Connection,
    input_text: str,
    reasoning: str,
    output: str,
    parent_decision_id: int | None = None,
    langfuse_trace_id: str | None = None,
    langfuse_observation_id: str | None = None,
) -> int:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO decision_log "
        "(timestamp, input_text, agent, reasoning, output, parent_decision_id, "
        "langfuse_trace_id, langfuse_observation_id) "
        "VALUES (?, ?, 'diagnostico', ?, ?, ?, ?, ?)",
        (
            timestamp,
            input_text,
            reasoning,
            output,
            parent_decision_id,
            langfuse_trace_id,
            langfuse_observation_id,
        ),
    )
    conn.commit()
    assert cur.lastrowid is not None  # siempre hay id tras un INSERT que no lanzó
    return cur.lastrowid


def diagnosticar(
    conn: sqlite3.Connection,
    sintomas: str,
    vehiculo_id: int | None = None,
    codigos_obd: list[str] | None = None,
    parent_decision_id: int | None = None,
    client: Any = None,
) -> dict:
    """Propone un diagnóstico preliminar con Claude Haiku a partir de
    síntomas en lenguaje natural, opcionalmente enriquecido con el
    historial y los datos del vehículo (vía crm.py) y códigos OBD.
    Registra la decisión en `decision_log` (agent='diagnostico').

    Devuelve {"causas_probables", "revisar_primero", "confianza",
    "razonamiento", "decision_id"}.

    `parent_decision_id`, si se pasa, encadena esta fila con la del
    decision_log de la decisión que originó esta llamada (típicamente la
    del Router que derivó el mensaje aquí) -- usado por la capa de
    orquestación del hito 6 (`flujo_diagnostico.py`) para que la cadena
    Router → Diagnóstico → Evaluador sea reconstruible de extremo a
    extremo vía parent_decision_id. Añadido en el hito 6 sin tocar el
    resto de la lógica de este módulo.

    Si `vehiculo_id` no existe, propaga `crm.VehiculoNoEncontradoError` tal
    cual (no se traduce a otro tipo de error) -- ese vehículo simplemente
    no existe, no es una respuesta inválida del modelo.

    Si la respuesta del modelo no se puede parsear a la estructura
    esperada, se registra igual en `decision_log` (con el texto crudo y el
    motivo del fallo) y se relanza `DiagnosticoRespuestaInvalidaError`, en
    vez de forzar un diagnóstico por defecto en silencio -- mismo patrón
    que router.clasificar_mensaje.

    `client` es inyectable para tests (evita llamadas reales a la API)."""
    if not sintomas or not sintomas.strip():
        raise ValueError("sintomas no puede estar vacío")

    contenido = _construir_contexto(conn, sintomas, vehiculo_id, codigos_obd)

    anthropic_client = client if client is not None else _get_client()
    # `input` enviado a Langfuse: exactamente `sintomas`, igual que
    # `input_text` en decision_log -- NO el `contenido` completo (que
    # añade marca/modelo/kilometraje/historial). Ver README, "Auditoría
    # de PII en Langfuse": no son PII propiamente, pero la disciplina de
    # minimización es "Langfuse ve lo mismo que decision_log, nunca más",
    # no una decisión caso por caso de qué campo adicional parece inocuo.
    with langfuse_utils.generacion_agente(
        "diagnostico", MODEL, input_data=sintomas, metadata={"vehiculo_id": vehiculo_id}
    ) as obs:
        response = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": contenido}],
        )
        texto_respuesta = response.content[0].text

        try:
            data = _validar_diagnostico(_extraer_json(texto_respuesta))
        except DiagnosticoRespuestaInvalidaError as exc:
            obs.completar_generacion(output={"error": str(exc)})
            try:
                _registrar_decision(
                    conn,
                    input_text=sintomas,
                    reasoning=f"Respuesta del modelo no parseable: {exc}",
                    output=json.dumps(
                        {"error": str(exc), "raw": texto_respuesta}, ensure_ascii=False
                    ),
                    parent_decision_id=parent_decision_id,
                    langfuse_trace_id=obs.trace_id,
                    langfuse_observation_id=obs.observation_id,
                )
            except sqlite3.Error:
                # No enmascarar el DiagnosticoRespuestaInvalidaError real por un
                # parent_decision_id inexistente (mismo fix aplicado en
                # evaluador.py tras la revisión de seguridad del hito 5).
                pass
            raise

        obs.completar_generacion(output=data, usage_details=langfuse_utils.usage_details(response))

    decision_id = _registrar_decision(
        conn,
        input_text=sintomas,
        reasoning=data["razonamiento"],
        output=json.dumps(data, ensure_ascii=False),
        parent_decision_id=parent_decision_id,
        langfuse_trace_id=obs.trace_id,
        langfuse_observation_id=obs.observation_id,
    )
    return {
        **data,
        "decision_id": decision_id,
        "langfuse_trace_id": obs.trace_id,
        "langfuse_observation_id": obs.observation_id,
    }
