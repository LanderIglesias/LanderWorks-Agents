"""router.py — agente Router/Recepción (hito 3, ajustado en hito 4).

Primer y único agente de los hitos 3-4. AISLADO a propósito: clasifica la
intención de un mensaje de cliente con Claude Haiku y registra la
decisión en `decision_log`. NO llama a Diagnóstico, Presupuestador ni
Evaluador (no existen todavía), y tampoco ejecuta ninguna herramienta
determinista de `agenda.py`/`inventario.py`/`crm.py` — solo decide y
explica a qué destino debería derivarse el mensaje. Conectar esa
derivación de verdad (que el "agente_destino" clasificado dispare una
llamada real) es el hito 6, según taller-multiagente-arranque.md.

Ajuste del hito 4 (primer paso, antes de construir Diagnóstico): toda
intención "urgencia" escala DIRECTO a "escalado_humano_inmediato",
saltándose Diagnóstico y Evaluador. Es una regla determinista aplicada en
código (`_forzar_escalado_urgencia`), no solo una instrucción en el
prompt — un mensaje real de seguridad no debe depender de que el modelo
siga la sugerencia correctamente. Ver README_taller_mecanico.md, sección
"Agente Router".
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv

from . import langfuse_utils

load_dotenv(override=False)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 512

INTENCIONES_VALIDAS = ("cita", "presupuesto", "urgencia", "consulta_tecnica", "queja", "otro")
AGENTES_DESTINO_VALIDOS = (
    "diagnostico",
    "presupuestador",
    "humano",
    "herramienta_agenda",
    "escalado_humano_inmediato",
    "ninguno",
)

_DESTINO_URGENCIA = "escalado_humano_inmediato"

# Mapeo intención -> destino sugerido, documentado en
# README_taller_mecanico.md ("Decisiones de negocio tomadas en el hito 3").
# Se le pasa al modelo como GUÍA en el prompt; para "urgencia" además se
# fuerza en código (ver _forzar_escalado_urgencia) porque no es una mera
# sugerencia -- es la regla de seguridad del hito 4.
_DESTINO_SUGERIDO = {
    "cita": "herramienta_agenda",
    "presupuesto": "presupuestador",
    "urgencia": _DESTINO_URGENCIA,
    "consulta_tecnica": "diagnostico",
    "queja": "humano",
    "otro": "humano",
}

_NOTA_ESCALADO_URGENCIA = (
    " [Regla determinista del Router: toda intención 'urgencia' escala directo a "
    "'escalado_humano_inmediato', sin pasar por Diagnóstico ni Evaluador -- un mensaje "
    "de seguridad real no puede esperar el pipeline normal ni depender de que el "
    "modelo eligiera bien el destino.]"
)

_SYSTEM_PROMPT = f"""Eres el Router de recepción de un taller mecánico. Tu única tarea es \
clasificar el mensaje de un cliente y decidir a qué destino derivarlo. No resuelves \
la consulta tú mismo, solo clasificas.

Intenciones posibles: {", ".join(INTENCIONES_VALIDAS)}.
Destinos posibles: {", ".join(AGENTES_DESTINO_VALIDOS)}.

Guía de derivación por defecto (puedes apartarte de ella si el mensaje lo justifica, \
explica por qué en "razonamiento"):
{json.dumps(_DESTINO_SUGERIDO, ensure_ascii=False)}

IMPORTANTE: si clasificas la intención como "urgencia", "agente_destino" DEBE ser \
"{_DESTINO_URGENCIA}" siempre, sin excepción -- nunca "diagnostico" ni ningún otro \
destino, aunque el problema técnico en sí suene similar a una consulta técnica normal.

Responde ÚNICAMENTE con un objeto JSON, sin texto antes ni después ni bloques de código, \
con exactamente estas claves:
{{"intencion": "<una de las intenciones posibles>", \
"agente_destino": "<uno de los destinos posibles>", \
"razonamiento": "<explicación breve, en español, de por qué clasificaste así>"}}
"""

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class RouterRespuestaInvalidaError(ValueError):
    """La respuesta del modelo no es JSON válido, le faltan claves esperadas,
    o alguno de sus valores no es del tipo/catálogo esperado. Claves EXTRA
    no declaradas no se rechazan (solo se ignoran)."""


def _get_client() -> Any:
    # Import perezoso: si el llamante inyecta su propio `client` (como
    # hacen todos los tests, ver test_router.py), el paquete `anthropic`
    # ni siquiera necesita estar configurado con una API key real.
    import anthropic

    return anthropic.Anthropic()


def _extraer_json(texto: str) -> dict:
    """Aísla el primer bloque {...} del texto de respuesta. El prompt pide
    JSON puro, pero un modelo puede envolverlo en ```json ... ``` de todas
    formas — esto lo tolera sin depender de que el modelo obedezca al
    pie de la letra."""
    match = _JSON_OBJECT_RE.search(texto)
    if match is None:
        raise RouterRespuestaInvalidaError(f"No se encontró ningún objeto JSON en: {texto!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise RouterRespuestaInvalidaError(f"JSON inválido: {exc}") from exc


def _validar_clasificacion(data: dict) -> dict:
    faltantes = {"intencion", "agente_destino", "razonamiento"} - data.keys()
    if faltantes:
        raise RouterRespuestaInvalidaError(f"Faltan claves en la respuesta: {faltantes}")
    if data["intencion"] not in INTENCIONES_VALIDAS:
        raise RouterRespuestaInvalidaError(f"intención desconocida: {data['intencion']!r}")
    if data["agente_destino"] not in AGENTES_DESTINO_VALIDOS:
        raise RouterRespuestaInvalidaError(
            f"agente_destino desconocido: {data['agente_destino']!r}"
        )
    if not isinstance(data["razonamiento"], str) or not data["razonamiento"].strip():
        # Sin esto, un modelo que devuelva razonamiento como objeto/lista
        # llega intacto a _registrar_decision y sqlite3 lanza
        # InterfaceError (no RouterRespuestaInvalidaError) al intentar
        # bindearlo — perdiendo además la fila de rastro en decision_log
        # que este módulo promete escribir incluso ante un fallo. El
        # `.strip()` (alineado con diagnostico._validar_diagnostico, misma
        # revisión de seguridad) evita una fila de decision_log con
        # razonamiento vacío, que no sirve de nada como auditoría.
        raise RouterRespuestaInvalidaError(
            f"razonamiento debe ser texto no vacío: {data['razonamiento']!r}"
        )
    return data


def _forzar_escalado_urgencia(data: dict) -> dict:
    """Si intencion == 'urgencia', fuerza agente_destino a
    'escalado_humano_inmediato' (aunque el modelo haya sugerido otro) y
    añade una nota explicando el porqué al razonamiento -- así
    decision_log siempre deja constancia de que se saltó Diagnóstico y
    Evaluador, sea o no el modelo el que ya lo clasificó así."""
    if data["intencion"] != "urgencia":
        return data
    data["agente_destino"] = _DESTINO_URGENCIA
    data["razonamiento"] = data["razonamiento"] + _NOTA_ESCALADO_URGENCIA
    return data


def _registrar_decision(
    conn: sqlite3.Connection,
    input_text: str,
    reasoning: str,
    output: str,
    langfuse_trace_id: str | None = None,
    langfuse_observation_id: str | None = None,
) -> int:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO decision_log "
        "(timestamp, input_text, agent, reasoning, output, langfuse_trace_id, langfuse_observation_id) "
        "VALUES (?, ?, 'router', ?, ?, ?, ?)",
        (timestamp, input_text, reasoning, output, langfuse_trace_id, langfuse_observation_id),
    )
    conn.commit()
    assert cur.lastrowid is not None  # siempre hay id tras un INSERT que no lanzó
    return cur.lastrowid


def clasificar_mensaje(conn: sqlite3.Connection, mensaje: str, client: Any = None) -> dict:
    """Clasifica `mensaje` con Claude Haiku y registra la decisión en
    `decision_log`. Devuelve {"intencion", "agente_destino", "razonamiento",
    "decision_id"}.

    Si la respuesta del modelo no se puede parsear a la clasificación
    esperada (JSON inválido, claves faltantes, o valores fuera del
    catálogo válido), se registra igualmente en `decision_log` — con el
    texto crudo de la respuesta y el motivo del fallo, para no perder el
    rastro de un intento fallido — y se relanza `RouterRespuestaInvalidaError`
    en vez de forzar una clasificación por defecto en silencio.

    `client` es inyectable: los tests pasan un cliente Anthropic falso
    (ver test_router.py) para no depender de la API real ni de tener
    ANTHROPIC_API_KEY configurada. Si se omite, se construye un
    `anthropic.Anthropic()` real.

    Si intencion == "urgencia", agente_destino se fuerza a
    "escalado_humano_inmediato" en código (no solo se sugiere al modelo)
    y el razonamiento guardado en decision_log siempre explica que se
    saltó Diagnóstico y Evaluador -- ver _forzar_escalado_urgencia."""
    if not mensaje or not mensaje.strip():
        raise ValueError("mensaje no puede estar vacío")

    anthropic_client = client if client is not None else _get_client()
    with langfuse_utils.generacion_agente("router", MODEL, input_data=mensaje) as obs:
        response = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": mensaje}],
        )
        texto_respuesta = response.content[0].text

        try:
            data = _forzar_escalado_urgencia(_validar_clasificacion(_extraer_json(texto_respuesta)))
        except RouterRespuestaInvalidaError as exc:
            obs.completar_generacion(output={"error": str(exc)})
            _registrar_decision(
                conn,
                input_text=mensaje,
                reasoning=f"Respuesta del modelo no parseable: {exc}",
                output=json.dumps({"error": str(exc), "raw": texto_respuesta}, ensure_ascii=False),
                langfuse_trace_id=obs.trace_id,
                langfuse_observation_id=obs.observation_id,
            )
            raise

        obs.completar_generacion(output=data, usage_details=langfuse_utils.usage_details(response))

    decision_id = _registrar_decision(
        conn,
        input_text=mensaje,
        reasoning=data["razonamiento"],
        output=json.dumps(data, ensure_ascii=False),
        langfuse_trace_id=obs.trace_id,
        langfuse_observation_id=obs.observation_id,
    )
    return {
        **data,
        "decision_id": decision_id,
        "langfuse_trace_id": obs.trace_id,
        "langfuse_observation_id": obs.observation_id,
    }
