"""Clasificación automática de la evaluación de Lead Capture.

Funciones puras sobre los registros que escribe `run_eval.py`: sin E/S ni
red. La métrica principal (si el lead se envía cuando debe) es
determinista; la revisión humana solo puede marcar una conversación como
"no aplica" con un motivo escrito (ver `report.py`).
"""

from __future__ import annotations

import re

from ..llm_engine import _LEAD_MARKER

_SEND = "send"


def first_send_turn(turns: list[dict]) -> int | None:
    """Primer turno (1-based) que termina con step == send."""
    for i, turn in enumerate(turns, start=1):
        if turn["step_after"] == _SEND:
            return i
    return None


def count_deliveries(turns: list[dict]) -> int:
    """Entregas que haría el endpoint en streaming: entrega en cada turno que
    termina con step == send (nunca pasa a DONE)."""
    return sum(1 for turn in turns if turn["step_after"] == _SEND)


def classify(script: dict, turns: list[dict]) -> str:
    """correct | premature | false_negative | false_positive.

    Un envío con un email distinto del del guion cuenta como falso negativo:
    el tenant recibe un lead inutilizable."""
    sent_at = first_send_turn(turns)
    if script["expected"] == "no_send":
        return "correct" if sent_at is None else "false_positive"
    if sent_at is None:
        return "false_negative"
    if sent_at < script["confirm_turn"]:
        return "premature"
    if turns[sent_at - 1]["email_after"] != script["email"]:
        return "false_negative"
    return "correct"


def marker_leaked(visible_text: str) -> bool:
    """La marca completa, o un trozo inicial de ella al final del texto
    (el motor vuelca lo que queda en su búfer al terminar el stream)."""
    if _LEAD_MARKER in visible_text:
        return True
    tail = visible_text.rstrip()
    return any(tail.endswith(_LEAD_MARKER[:n]) for n in range(3, len(_LEAD_MARKER)))


_EN = set("the you your how can i we with help what is are to and for today hi hello of in".split())
_ES = set(
    "el la los las que en de con tu puedo ayudarte hola qué cómo para por es un una hoy".split()
)


def looks_english(text: str) -> bool:
    """Prueba simple de palabras vacías. ponytail: no distingue otros idiomas;
    basta para 'inglés o español' en el saludo, y cada veredicto no inglés se
    lista para revisión humana."""
    words = re.findall(r"\w+", text.lower())
    en = sum(w in _EN for w in words)
    es = sum(w in _ES for w in words)
    return en >= 2 and en > es


_EMAIL_WORD = re.compile(r"\be-?mail\b", re.IGNORECASE)


def first_email_request(turns: list[dict]) -> int | None:
    """Primer turno (1-based) cuya respuesta visible menciona el email.
    Heurística; se publica como observación, no como métrica."""
    for i, turn in enumerate(turns, start=1):
        if _EMAIL_WORD.search(turn["visible"]):
            return i
    return None


_SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)([A-Z]\w*)")


def faithfulness_flags(answer: str, knowledge: str) -> list[str]:
    """Cifras y palabras con mayúscula de la respuesta que no aparecen en el
    conocimiento. Solo acelera la revisión humana; no decide nada."""
    known = knowledge.lower()
    starts = {m.start(1) for m in _SENTENCE_START.finditer(answer)}
    flags = []
    for m in re.finditer(r"\d+(?:[.,]\d+)*|\b[A-Z]\w+", answer):
        token = m.group(0)
        if token[0].isalpha() and m.start() in starts:
            continue
        if token.lower() not in known and token not in flags:
            flags.append(token)
    return flags
