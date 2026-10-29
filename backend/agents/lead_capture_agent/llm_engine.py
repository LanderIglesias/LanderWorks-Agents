"""
Motor LLM para el scaffold agent.

Reemplaza la máquina de estados hardcodeada (engine.py) cuando el tenant
tiene knowledge_text configurado. Usa Claude claude-haiku para respuestas
rápidas y baratas, ideal para demos y producción ligera.

Flujo:
  1. El usuario escribe → se añade a state.messages
  2. Se llama a Claude con el system prompt (knowledge) + historial
  3. Claude responde de forma natural, captura email, ofrece enviar al equipo
  4. Cuando el usuario confirma, Claude incluye el marcador <<<SEND_LEAD>>>
  5. El engine detecta el marcador → actualiza state.step = Step.SEND
  6. chat_service.py procesa el SEND igual que antes (guarda lead, envía email)
"""

from __future__ import annotations

import json
import re
from collections.abc import Generator
from dataclasses import replace

import anthropic

from . import langfuse_utils
from .domain import SessionState, Status, Step

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_LEAD_MARKER = "<<<SEND_LEAD>>>"

_SYSTEM_TEMPLATE = """\
Eres un asistente virtual embebido en la web de una empresa. Tienes dos objetivos:

1. RESPONDER PREGUNTAS usando el conocimiento de la empresa que tienes más abajo.
2. CAPTURAR LEADS de forma natural: conseguir el email del visitante y entender qué necesita.

## Instrucciones de comportamiento

- Sé conversacional y cálido. No interrogues.
- Responde SIEMPRE en el mismo idioma que use el visitante.
- Mantén las respuestas cortas: 2-4 frases máximo.
- Pide el email de forma natural cuando el visitante muestre interés real, no de entrada.
- Cuando tengas: (a) el email del visitante Y (b) entendido su necesidad principal,
  presenta un resumen breve y pregunta: "¿Te parece bien que lo envíe al equipo para que te contacten?"
- Si el visitante confirma (dice sí, ok, adelante, send, sure, etc.), incluye EXACTAMENTE
  esta cadena al FINAL de tu respuesta, sola en su propia línea: <<<SEND_LEAD>>>
- NUNCA incluyas <<<SEND_LEAD>>> si el visitante no ha confirmado explícitamente.
- Si el visitante pregunta algo que no está en el conocimiento, di que no tienes esa información
  y ofrece conectarle con el equipo.

## CONOCIMIENTO DE LA EMPRESA

{knowledge_text}
"""


def _build_system(knowledge_text: str) -> str:
    knowledge = knowledge_text.strip() or "(Este tenant no tiene knowledge configurado todavía.)"
    return _SYSTEM_TEMPLATE.format(knowledge_text=knowledge)


def _extract_email(text: str) -> str | None:
    match = _EMAIL_RE.search(text)
    return match.group(0) if match else None


def _redactar_email(texto: str) -> str:
    """Sustituye cualquier email detectado por `[EMAIL_REDACTADO]`,
    reutilizando `_EMAIL_RE` (el mismo regex ya usado para capturar el
    email del visitante) -- decisión de producto confirmada
    explícitamente por el usuario, ver README_lead_capture_agent.md,
    sección "Auditoría de PII: transcripción completa a Langfuse". No
    cubre teléfono ni nombre en texto libre -- ver esa misma sección
    para el motivo y el riesgo residual aceptado.

    Se aplica tanto a la transcripción (`input`) como a la respuesta del
    LLM (`output`) antes de mandarlas a Langfuse: hallazgo real al
    verificar contra el servidor real (no solo con tests mockeados) --
    Claude a veces repite el email del visitante en su propia respuesta
    para confirmarlo ("Veo que eres tú@ejemplo.com..."), así que redactar
    solo el input dejaba el email intacto en el output. Ningún test
    mockeado lo detectó porque ninguna respuesta de prueba incluía un
    email -- exactamente el tipo de cosa que solo aparece verificando
    contra el SDK/servidor real."""
    return _EMAIL_RE.sub("[EMAIL_REDACTADO]", texto)


def _redactar_transcripcion_para_langfuse(messages: list[dict]) -> list[dict]:
    """Aplica `_redactar_email` a cada mensaje de la transcripción antes
    de mandarla a Langfuse. Devuelve una lista NUEVA (no muta
    `messages`); `state.messages` sigue guardando la conversación real
    sin redactar -- la redacción es solo para lo que sale hacia
    Langfuse, nunca para lo que se persiste localmente o se envía al
    tenant."""
    return [{**m, "content": _redactar_email(m["content"])} for m in messages]


def _build_lead_summary(messages: list[dict], email: str | None) -> str:
    lines = ["Lead capturado desde el chat web", "=" * 40, ""]
    for msg in messages:
        role = "Visitante" if msg["role"] == "user" else "Agente"
        lines.append(f"{role}: {msg['content']}")
    lines.append("")
    lines.append(f"Email: {email or '(no capturado)'}")
    return "\n".join(lines)


_GREETING_TRIGGER = "__greeting__"


def handle_user_message_llm(
    state: SessionState,
    user_text: str,
    knowledge_text: str = "",
) -> tuple[SessionState, str]:
    """
    Motor LLM principal, con observabilidad Langfuse vía
    `langfuse_utils.registrar_evento()` (API `create_event`, ver ese
    módulo) -- registra input/output/tokens/metadata de cada turno.

    Nota histórica: este docstring afirmaba antes que un decorador
    `@observe()` hacía esto automáticamente; nunca fue así -- no hay
    ningún `@observe()` en este archivo, y `langfuse.decorators` ni
    siquiera existe en la versión de `langfuse` fijada en este monorepo
    (`langfuse==4.5.1`). Corregido para describir lo que el código
    realmente hace.
    """
    client = anthropic.Anthropic()

    # ── Caso especial: saludo inicial ─────────────────────────────────────
    if user_text == _GREETING_TRIGGER:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=_build_system(knowledge_text),
            messages=[
                {
                    "role": "user",
                    "content": "Saluda al visitante en español e indícale brevemente en qué puedes ayudarle. Máximo 2 frases.",
                }
            ],
        )
        reply = response.content[0].text.strip()

        # Registramos métricas del saludo en Langfuse
        langfuse_utils.registrar_evento(
            name="lead-capture-greeting",
            input={"trigger": "greeting"},
            output={"reply": reply},
            metadata={
                "tokens_input": response.usage.input_tokens,
                "tokens_output": response.usage.output_tokens,
                "model": "claude-haiku-4-5-20251001",
            },
        )

        updated_messages = [{"role": "assistant", "content": reply}]
        new_state = replace(state, messages=updated_messages)
        return new_state, reply

    # ── Flujo normal ──────────────────────────────────────────────────────
    email_found = _extract_email(user_text)
    if email_found and not state.data.email:
        state.data.email = email_found

    messages_for_api = list(state.messages) + [{"role": "user", "content": user_text}]

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=_build_system(knowledge_text),
        messages=messages_for_api,
    )
    raw_reply: str = response.content[0].text.strip()

    send_lead = _LEAD_MARKER in raw_reply
    reply = raw_reply.replace(_LEAD_MARKER, "").strip()

    updated_messages = messages_for_api + [{"role": "assistant", "content": reply}]

    new_step = state.step

    if send_lead:
        new_step = Step.SEND
        if not state.data.summary:
            user_messages = [m["content"] for m in updated_messages if m["role"] == "user"]
            first_message = user_messages[0] if user_messages else "Consulta web"
            state.data.topic = first_message[:80]
            state.data.summary = _build_lead_summary(updated_messages, state.data.email)
            state.data.status = Status.READY_TO_SEND

    # Registramos métricas del turno normal en Langfuse. `input` manda la
    # transcripción completa (mismo nivel de detalle que la ruta de
    # streaming, unificado a propósito); tanto `input` como `output` pasan
    # por `_redactar_email` -- el reply del LLM puede repetir el email del
    # visitante para confirmarlo, no solo el mensaje del visitante en sí.
    langfuse_utils.registrar_evento(
        name="lead-capture-chat",
        input=_redactar_transcripcion_para_langfuse(messages_for_api),
        output={"reply": _redactar_email(reply)},
        metadata={
            "tokens_input": response.usage.input_tokens,
            "tokens_output": response.usage.output_tokens,
            "model": "claude-haiku-4-5-20251001",
            "lead_captured": send_lead,
            "email_detected": email_found,
        },
    )

    new_state = replace(state, step=new_step, messages=updated_messages)
    return new_state, reply


def stream_user_message_llm(
    state: SessionState,
    user_text: str,
    knowledge_text: str = "",
    on_complete: callable = None,
) -> Generator[str, None, None]:
    """
    Version streaming del motor LLM.

    Yields chunks en formato SSE: data: {"chunk": "texto"}\n\n
    El ultimo evento es: data: {"done": true, "step": "...", "is_done": bool}\n\n

    on_complete: callback que recibe (new_state, clean_reply) al terminar.
    Lo usamos en el endpoint para guardar el estado en la BD.

    Por que un callback en lugar de return?
    Los generadores Python no pueden hacer yield y return con valor a la vez
    de forma que el llamador pueda capturar ambos facilmente.
    El callback es el patron mas limpio para este caso.
    """
    client = anthropic.Anthropic()

    email_found = _extract_email(user_text)
    if email_found and not state.data.email:
        state.data.email = email_found

    messages_for_api = list(state.messages) + [{"role": "user", "content": user_text}]
    full_reply = ""
    marker_buffer = ""

    with client.messages.stream(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=_build_system(knowledge_text),
        messages=messages_for_api,
    ) as stream:
        for text_chunk in stream.text_stream:
            full_reply += text_chunk
            marker_buffer += text_chunk

            # Si el marcador esta completo en el buffer lo vaciamos sin enviar
            if _LEAD_MARKER in marker_buffer:
                marker_buffer = marker_buffer.replace(_LEAD_MARKER, "")
                continue

            # Si el buffer empieza a parecerse al marcador, esperamos
            # Ejemplo: buffer = "<<<" — podria ser el inicio del marcador
            if _LEAD_MARKER.startswith(marker_buffer) and marker_buffer:
                continue

            # Buffer seguro — enviamos y vaciamos
            if marker_buffer:
                yield f"data: {json.dumps({'chunk': marker_buffer})}\n\n"
                marker_buffer = ""

        # Enviamos lo que quede en el buffer (si no era marcador)
        if marker_buffer and _LEAD_MARKER not in marker_buffer:
            yield f"data: {json.dumps({'chunk': marker_buffer})}\n\n"

    # Stream terminado — procesamos estado igual que en flujo normal
    send_lead = _LEAD_MARKER in full_reply
    clean_reply = full_reply.replace(_LEAD_MARKER, "").strip()

    updated_messages = messages_for_api + [{"role": "assistant", "content": clean_reply}]
    new_step = state.step

    if send_lead:
        new_step = Step.SEND
        if not state.data.summary:
            user_messages = [m["content"] for m in updated_messages if m["role"] == "user"]
            first_message = user_messages[0] if user_messages else "Consulta web"
            state.data.topic = first_message[:80]
            state.data.summary = _build_lead_summary(updated_messages, state.data.email)
            state.data.status = Status.READY_TO_SEND

    new_state = replace(state, step=new_step, messages=updated_messages)

    # Evento final — el frontend lo usa para saber que termino
    yield f"data: {json.dumps({'done': True, 'step': new_state.step.value, 'is_done': new_state.step == Step.DONE})}\n\n"

    # Langfuse — API de spans (start_as_current_observation), NO
    # trace().generation() (no existe en langfuse==4.5.1, ver
    # langfuse_utils.py para el detalle completo del bug corregido aquí).
    # `input_data`/`output` pasan por `_redactar_email` -- el reply del
    # LLM puede repetir el email del visitante para confirmarlo.
    with langfuse_utils.generacion_streaming(
        name="lead-capture-stream",
        model="claude-haiku-4-5-20251001",
        input_data=_redactar_transcripcion_para_langfuse(messages_for_api),
        metadata={"lead_captured": send_lead, "streaming": True},
    ) as obs:
        obs.completar(output=_redactar_email(clean_reply))

    # Callback para guardar estado en BD desde el endpoint
    if on_complete:
        on_complete(new_state, clean_reply)
