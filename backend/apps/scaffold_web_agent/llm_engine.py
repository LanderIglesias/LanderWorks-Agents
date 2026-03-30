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

import re
from dataclasses import replace

import anthropic

from .domain import SessionState, Status, Step

# Regex para detectar emails en el texto del usuario
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Marcador que Claude incluye cuando el usuario confirma enviar el lead.
# Usamos algo poco probable de aparecer en texto normal.
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
    """Construye el system prompt inyectando el knowledge del tenant."""
    knowledge = knowledge_text.strip() or "(Este tenant no tiene knowledge configurado todavía.)"
    return _SYSTEM_TEMPLATE.format(knowledge_text=knowledge)


def _extract_email(text: str) -> str | None:
    """Extrae el primer email válido del texto, si existe."""
    match = _EMAIL_RE.search(text)
    return match.group(0) if match else None


def _build_lead_summary(messages: list[dict], email: str | None) -> str:
    """
    Construye el resumen del lead a partir del historial de conversación.
    Este texto es el que se guarda en la BD y se envía al inbox del tenant.
    """
    lines = ["Lead capturado desde el chat web", "=" * 40, ""]
    for msg in messages:
        role = "Visitante" if msg["role"] == "user" else "Agente"
        lines.append(f"{role}: {msg['content']}")
    lines.append("")
    lines.append(f"Email: {email or '(no capturado)'}")
    return "\n".join(lines)


# Mensaje especial que envía el widget al abrirse por primera vez.
# El engine lo intercepta para generar un saludo con el LLM sin que
# el usuario haya escrito nada.
_GREETING_TRIGGER = "__greeting__"


def handle_user_message_llm(
    state: SessionState,
    user_text: str,
    knowledge_text: str = "",
) -> tuple[SessionState, str]:
    """
    Motor LLM principal. Sustituye a handle_user_message() de engine.py
    cuando el tenant tiene knowledge_text configurado.

    Args:
        state: Estado actual de la sesión (incluye historial en state.messages)
        user_text: Mensaje del usuario (o __greeting__ para el saludo inicial)
        knowledge_text: Texto de conocimiento del tenant (de la BD)

    Returns:
        (new_state, reply): Estado actualizado + respuesta del agente
    """
    client = anthropic.Anthropic()

    # ── Caso especial: saludo inicial ─────────────────────────────────────
    # El widget envía "__greeting__" al abrirse por primera vez.
    # Claude genera el saludo basándose en el knowledge del tenant.
    # El mensaje especial NO se guarda en el historial — solo la respuesta.
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
        # Guardamos solo la respuesta del asistente, no el trigger interno
        updated_messages = [{"role": "assistant", "content": reply}]
        new_state = replace(state, messages=updated_messages)
        return new_state, reply

    # ── Flujo normal ──────────────────────────────────────────────────────

    # 1. Detectar email en el mensaje del usuario
    email_found = _extract_email(user_text)
    if email_found and not state.data.email:
        state.data.email = email_found

    # 2. Construir lista de mensajes para la API (historial + mensaje actual)
    messages_for_api = list(state.messages) + [{"role": "user", "content": user_text}]

    # 3. Llamar a Claude Haiku
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=_build_system(knowledge_text),
        messages=messages_for_api,
    )
    raw_reply: str = response.content[0].text.strip()

    # 4. Detectar marcador de lead confirmado
    send_lead = _LEAD_MARKER in raw_reply
    reply = raw_reply.replace(_LEAD_MARKER, "").strip()

    # 5. Guardar el turno completo en el historial
    updated_messages = messages_for_api + [{"role": "assistant", "content": reply}]

    # 6. Actualizar estado
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
    return new_state, reply
