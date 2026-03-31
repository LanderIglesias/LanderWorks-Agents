import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from openai import OpenAI
from unidecode import unidecode

from .config import settings
from .metrics import log_event
from .rag import search
from .store import (
    cleanup_sessions,
    enqueue_handoff,
    get_state,
    reset_state,
    save_lead,
    save_state,
    touch_state,
)
from .tools import (
    ahora_iso,
    canned_faq_answer,
    clasifica_intencion,
    clasifica_tratamiento,
    clasifica_urgencia,
    detect_faq_keys,
    detectar_sintomas_urgentes,
    extract_booking_fields,
    normaliza_tel,
    user_tried_phone_but_invalid,
)

client = OpenAI(api_key=settings.OPENAI_API_KEY)

_NEWLINES = re.compile(r"(\\n\\n+|[ \t]*\n[ \t]*\n+)")
_SPACES = re.compile(r"[ \t]{2,}")
HANDOFF_KIND_EXPLICIT_HUMAN = "explicit_human"
HANDOFF_KIND_STRUCTURED = "followup_structured"
HANDOFF_KIND_FREE = "followup_free"
HANDOFF_KIND_URGENT = "urgent"
HANDOFF_KIND_BOOKING_FINAL = "booking_final"

SYSTEM = """Eres el asistente virtual de una clínica dental en España. Atiendes igual que lo haría una persona de recepción.

Objetivos:
- Responde de forma clara, breve y profesional.
- Tono cercano y amable, sin sonar técnico ni robótico.
- No menciones nunca que eres una IA o modelo automático.
- Contesta todas las partes de la pregunta del usuario. Si hay varias, responde en 2–3 párrafos o viñetas.
- Da precios solo si existen en los datos; usa “orientativo” si no hay precio fijo.
- En casos de dolor fuerte, flemón, sangrado abundante o urgencia clara: recomienda valoración inmediata y ofrece cita rápida.
- Si el usuario quiere cita: recoge nombre, teléfono, tratamiento y urgencia.
- Nada de humor, emojis o tecnicismos innecesarios.
- Tu estilo debe ser: natural, cercano y profesional, como un recepcionista con experiencia.
- Si el usuario pregunta una sola cosa (p.ej. horario, precio, dirección), responde con 1–2 frases y no añadas información extra.
"""


def wants_human(text: str) -> bool:
    t = (text or "").strip().lower()

    # Señales explícitas de humano (tienen que estar)
    human_phrases = [
        "hablar con una persona",
        "hablar con alguien",
        "quiero hablar con una persona",
        "quiero hablar con alguien",
        "persona real",
        "humano",
        "operador",
        "llamadme",
        "llámame",
        "que me llamen",
        "quiero que me llamen",
        "prefiero que me llamen",
        "me puede llamar alguien",
        "me podéis llamar",
        "me podeis llamar",
        "quiero que me contactéis",
        "quiero que me contacteis",
    ]

    # Si no hay ninguna frase explícita, NO es humano.
    if not any(p in t for p in human_phrases):
        return False

    # Pero si también es claramente una solicitud de cita, solo lo consideramos humano
    # si incluye "hablar con..." (o similar). Evita falsos positivos por "cita".
    booking_markers = [
        "cita",
        "pedir cita",
        "reservar",
        "agendar",
        "quiero una cita",
        "quiero pedir una cita",
        "quiero coger una cita",
    ]
    is_booking = any(b in t for b in booking_markers)

    # Si es booking y NO viene con el patrón fuerte "hablar con", no derivar a humano.
    strong_human = any(x in t for x in ["hablar con una persona", "hablar con alguien"])

    if is_booking and not strong_human:
        return False

    return True


FAQ_DEDUPE_WINDOW = timedelta(minutes=10)


def _now_iso_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _parse_iso_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _trim_reply(text: str, max_chars: int = 180) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t

    cut = t[:max_chars].rstrip()

    # intenta cortar en final de frase si existe
    m = re.search(r"(.+?[\.!\?])\s+[^\s].*$", cut, flags=re.S)
    if m and len(m.group(1)) > 120:
        cut = m.group(1).rstrip()

    return cut.rstrip(". ").rstrip() + "…"


def time_greeting() -> str:
    h = datetime.now(ZoneInfo("Europe/Madrid")).hour  # usa hora del servidor
    if 6 <= h < 13:
        return "¡Buenos días!"
    if 13 <= h < 21:
        return "¡Buenas tardes!"
    return "¡Buenas noches!"


def resume_phrase(n: int) -> str:
    variants = [
        "Perfecto, para seguir con la cita,",
        "Genial. Entonces, para continuar,",
        "De acuerdo. Volviendo a la cita,",
        "Perfecto. Retomando la cita,",
        "Gracias. Para continuar con la cita,",
    ]
    return variants[min(n - 1, len(variants) - 1)]


def hay_sintomas_urgentes(msg: str) -> bool:
    sx = detectar_sintomas_urgentes(msg)
    return any(sx.values())


def treatment_implies_low_urgency(trat: str | None) -> bool:
    t = unidecode((trat or "").lower()).strip()

    low = [
        "limpieza",
        "blanqueamiento",
        "revision",
        "revisión",
        "higiene",
        "estetica",
        "estética",
        "carillas",
        "ortodoncia",
        "invisalign",
        "retenedor",
        "férula",
        "ferula",
        "revision general",
        "revisión general",
        "revision anual",
        "revisión anual",
    ]
    return any(k in t for k in low)


def treatment_may_be_urgent(trat: str | None) -> bool:
    t = unidecode((trat or "").lower()).strip()

    urgent = [
        "dolor",
        "sangrado",
        "hinchazon",
        "hinchazón",
        "flemon",
        "flemón",
        "infeccion",
        "infección",
        "absceso",
        "urgencia",
        "fractura",
        "roto",
        "rota",
        "traumatismo",
        "golpe",
        "inflamacion",
        "inflamación",
        "fuerte",
        "dolor fuerte",
    ]
    return any(k in t for k in urgent)


FAQ_REPEAT_WINDOW = timedelta(minutes=5)


def maybe_dedupe_faq_reply(st, faq_keys: list[str], reply: str) -> str:
    return reply


def is_cancel(text: str) -> bool:
    t = (text or "").strip().lower()
    t = unidecode(t)
    t = re.sub(r"[^\w\sáéíóúüñ]", "", t)
    t = re.sub(r"\s+", " ", t).strip()

    # Frases de cancelación / abandono (claras)
    cancel_phrases = {
        "olvidalo",
        "da igual olvidalo",
        "mejor no",
        "cancelar",
        "cancela",
        "cancelalo",
        "no quiero",
        "ya no quiero",
        "no hace falta",
        "paso",
        "déjalo",
        "dejalo",
        "no me interesa",
        "no quiero dar datos",
        "no te voy a dar el telefono",
        "no te dare el telefono",
    }

    if t in cancel_phrases:
        return True

    # Patrones comunes
    if any(
        p in t
        for p in [
            "olvid",  # olvídalo / olvidar
            "cancel",  # cancelar / cancelación
            "mejor no",  # mejor no
            "da igual",  # da igual
            "no quiero seguir",
            "no quiero dar el telefono",
            "no te voy a dar el telefono",
            "no voy a dar el telefono",
        ]
    ):
        return True

    return False


def is_refusal(text: str) -> bool:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\sáéíóúüñ]", "", t)
    refusals = [
        "no te voy a dar",
        "no te lo voy a dar",
        "no quiero darte",
        "no te doy",
        "no lo doy",
        "no pienso darte",
        "no voy a darte",
        "no te dare",
        "no te daré",
        "no doy mi telefono",
        "no doy mi teléfono",
        "no te doy el telefono",
        "no te doy el teléfono",
    ]
    return any(p in t for p in refusals)


def is_question_like(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False

    low = unidecode(t.lower())

    # 1) Signos de pregunta
    if "?" in low or "¿" in low:
        return True

    # 2) Arranques clásicos
    starters = (
        "que",
        "qué",
        "cual",
        "cuál",
        "cuanto",
        "cuánto",
        "cuando",
        "cuándo",
        "donde",
        "dónde",
        "como",
        "cómo",
        "teneis",
        "tenéis",
        "aceptais",
        "aceptáis",
        "hay",
        "puedo",
        "se puede",
    )
    if any(low.startswith(s + " ") or low == s for s in starters):
        return True

    # 3) Preguntas “telegráficas” de WhatsApp (SIN signos)
    keywords = (
        "horario",
        "horarios",
        "precio",
        "precios",
        "adeslas",
        "seguros",
        "seguro",
        "financiacion",
        "financiación",
        "direccion",
        "dirección",
        "ubicacion",
        "ubicación",
        "parking",
        "aparcamiento",
        "cita",
        "disponibilidad",
        "cuando llamais",
        "cuando llamáis",
        "cuanto tardais",
        "cuánto tardáis",
    )
    return any(k in low for k in keywords)


def is_negative(text: str) -> bool:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\sáéíóúüñ]", "", t)
    negatives = {
        "no",
        "n",
        "nop",
        "nope",
        "para",
        "cancelar",
        "cancela",
        "mejor no",
        # EU
        "ez",
    }
    if t in negatives:
        return True
    for n in negatives:
        if t.startswith(n + " "):
            return True

    # NUEVO: rechazo explícito
    if any(
        p in t
        for p in [
            "no te voy a dar",
            "no voy a dar",
            "no quiero dar",
            "prefiero no dar",
            "olvidalo",
            "olvídalo",
        ]
    ):
        return True

    return False


def is_affirmative(text: str) -> bool:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\sáéíóúüñ]", "", t)

    affirmatives = {
        "si",
        "sí",
        "s",
        "vale",
        "ok",
        "oka",
        "okay",
        "perfecto",
        "confirmo",
        "confirmado",
        "de acuerdo",
        "dale",
        "venga",
        "correcto",
        "bien",
        "claro",
        "por supuesto",
        "desde luego",
        "afirmativo",
        "adelante",
        # EU
        "noski",
        "bai",
        # NUEVOS (confirmación natural)
        "listo",
        "asi listo",
        "así listo",
        "asi esta bien",
        "así está bien",
        "esta bien",
        "está bien",
        "asi",
        "así",
        "dejalo asi",
        "déjalo así",
        "asi esta perfecto",
        "así está perfecto",
        "perfecto asi",
        "perfecto así",
        "todo correcto",
        "todo bien",
        "ok perfecto",
    }

    if t in affirmatives:
        return True

    for a in affirmatives:
        if t.startswith(a + " "):
            return True

    return False


def is_hold(text: str) -> bool:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\sáéíóúüñ]", "", t)

    holds = {
        "espera",
        "esperame",
        "espérame",
        "un segundo",
        "un momento",
        "dame un minuto",
        "un minuto",
        "ahora no",
        "luego",
        "luego te digo",
        "ahora te digo",
        "ahora mismo no",
        "déjame",
        "dejame",
        "perdona",
        "perdon",
    }

    if t in holds:
        return True
    for h in holds:
        if t.startswith(h + " "):
            return True
    return False


def is_indifferent(text: str) -> bool:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\sáéíóúüñ]", "", t)

    phrases = {
        "me da igual",
        "da igual",
        "lo que sea",
        "como quieras",
        "cualquiera",
        "indiferente",
        "sin preferencia",
        "no tengo preferencia",
        "me es igual",
    }

    if t in phrases:
        return True
    for p in phrases:
        if p in t:
            return True
    return False


def is_pure_greeting(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False

    # Normaliza: minúsculas, sin acentos, sin puntuación rara
    t = unidecode(raw.lower())
    t = re.sub(r"[^\w\s]", " ", t)  # quita puntuación / emojis -> espacio
    t = re.sub(r"\s+", " ", t).strip()

    greetings = {
        # ES
        "hola",
        "buenas",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "hey",
        "holi",
        "que tal",
        "qué tal",
        "buen dia",
        "buen día",
        # EU (todo en minúsculas)
        "kaixo",
        "egun on",
        "arratsalde on",
        "gabon",
        "aupi",
        "aupa",
        "eguerdion",
        "eguerdi on",
        "gab on",
    }

    # Si contiene palabras que indican intención, NO es saludo puro
    intent_keywords = [
        "cita",
        "horario",
        "precio",
        "direccion",
        "telefono",
        "dolor",
        "urgente",
        "urgencia",
        "consulta",
        "quiero",
        "necesito",
        "tengo",
        "me duele",
    ]

    if any(k in t for k in intent_keywords):
        return False

    # match exacto
    if t in greetings:
        return True

    # combos típicos: "hola buenas", "hola buenos dias", etc.
    parts = t.split()
    if 1 <= len(parts) <= 3:
        # Permitimos combinaciones donde cada palabra sea parte de un saludo conocido
        # (p.ej. ["hola", "buenos", "dias"])
        # Para esto, permitimos el caso especial "buenos dias"/"buenas tardes"/"buenas noches"
        joined = " ".join(parts)
        if joined in greetings:
            return True

        # Caso: "hola" + ("buenos dias" / "buenas tardes" / "buenas noches" / "buenas")
        if parts[0] in {"hola", "hey", "holi"}:
            rest = " ".join(parts[1:])
            if rest in greetings:
                return True
        # Caso: "buenas" + "hola"
        if parts[-1] in {"hola"} and " ".join(parts[:-1]) in greetings:
            return True

    return False


_THANKS_RE = re.compile(
    r"^(?:muchas\s+)?gracias(?:\s+)?(?:!|\.)?$"
    r"|^gracias\s+(?:tio|tía|crack|majo|genial)?(?:!|\.)?$"
    r"|^thank(s| you)(?:!|\.)?$"
    r"|^eskerrik\s+asko(?:!|\.)?$"
    r"|^mila\s+esker(?:!|\.)?$"
    r"|^eskerrak(?:!|\.)?$"
    r"|^esker(?:!|\.)?$"
    r"|^eskerrik(?:!|\.)?$",
    re.IGNORECASE,
)


def is_thanks(text: str) -> bool:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)

    # combos típicos (ES + EU)
    if re.search(
        r"\b(ok|vale|perfecto|genial|bien|de acuerdo)\b.*\b(gracias|eskerrik asko|mila esker|eskerrak|esker)\b",
        t,
    ):
        return True

    if len(t) > 25:
        return False
    return bool(_THANKS_RE.match(t))


def is_appt_change_request(text: str) -> bool:
    t = unidecode((text or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    patterns = [
        "cambiar cita",
        "modificar cita",
        "reprogramar",
        "aplazar",
        "mover la cita",
        "cambiar mi cita",
        "cancelar cita",
        "anular cita",
    ]
    return any(p in t for p in patterns)


def is_goodbye(text: str) -> bool:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\sáéíóúüñ]", "", t)
    goodbyes = {
        "adios",
        "adiós",
        "hasta luego",
        "hasta pronto",
        "buenas noches",
        "buenas",
        "chao",
        "chau",
        "agur",
    }
    return t in goodbyes


def is_neutral_human(text: str) -> bool:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\sáéíóúüñ👍😂😅😄]", "", t)

    neutrals = {
        # afirmaciones blandas
        "ok",
        "vale",
        "perfecto",
        "genial",
        "bien",
        "de acuerdo",
        "gracias",
        "thanks",
        # emojis
        "👍",
        "👌",
        # risas
        "jaja",
        "jajaja",
        "jeje",
        "jejeje",
        "😂",
        "😅",
        "😄",
        # pausas
        "luego",
        "ahora no",
        "más tarde",
        "mas tarde",
        # saludos (CLAVE para no romper el flujo)
        "hola",
        "buenas",
        "buenos dias",
        "buenos días",
        "buenas tardes",
        "buenas noches",
    }

    # match exacto
    if t in neutrals:
        return True

    # match por prefijo (ej: "buenas tardes!", "vale gracias")
    for n in neutrals:
        if t.startswith(n + " "):
            return True

    return False


def _is_when_calling_question(text: str) -> bool:
    t = unidecode((text or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    patterns = [
        r"\bcuando\b.*\b(llam|contact)\b",
        r"\bme\s*llam(a|ais|an)\b",
        r"\bhoy\b.*\b(llam|contact)\b",
        r"\ba\s*que\s*hora\b.*\bllam\b",
    ]
    return any(re.search(p, t) for p in patterns)


def _handoff_eta_reply() -> str:
    return (
        "Recepción lo revisa y te contactará lo antes posible dentro de su horario. "
        "Si te viene bien hoy, dímelo y lo dejo anotado como preferencia."
    )


def build_context(user_msg: str) -> tuple[list[str], list[str]]:
    """Crea el contexto para el LLM y recopila las fuentes."""
    # Subimos k para que, cuando el usuario pregunte varias cosas (ej. horario + dirección),
    # entren en contexto varios bloques del markdown (horarios, dirección, aparcamiento, etc.).
    results, _best = search(user_msg, k=6)  # antes k=3

    ctx: list[str] = []
    srcs: list[str] = []
    for r in results:
        src = r.get("source", "unknown")
        snip = r.get("snippet", "")
        ctx.append(f"[{src}]\n{snip}")
        srcs.append(src)
    return ctx, srcs


def answer_with_rag(user_msg: str, ctx: list[str]) -> str:
    if not ctx:
        return "No tengo esa información ahora mismo. Si quieres, te lo confirma recepción."

    user_content = (
        f"Ahora: {ahora_iso()}.\n" f"Usuario: {user_msg}\n\n" "Contexto:\n" + "\n---\n".join(ctx)
    )

    try:
        res = client.chat.completions.create(
            model=settings.MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
        )
        return (res.choices[0].message.content or "").strip()

    except Exception:
        return (
            "Ahora mismo no puedo acceder a esa información. Si quieres, te lo confirma recepción."
        )


# --- FAQ key canonicalization + priority ---


def _canonical_faq_key(k: str) -> str:
    k = (k or "").strip().lower()
    # Canon de keys del bot
    canon = {
        "horarios": "horario",
        "hora": "horario",
        "horas": "horario",
        "precio": "precios",
        "tarifa": "precios",
        "tarifas": "precios",
        "politicas": "políticas",
    }
    return canon.get(k, k)


def _sort_faq_keys(keys: list[str]) -> list[str]:
    """
    Orden determinista por prioridad UX:
      horario > direccion/contacto > resto > precios al final
    """
    if not keys:
        return []

    # 1) Canon + dedupe preservando aparición
    seen = set()
    canon_keys: list[str] = []
    for k in keys:
        ck = _canonical_faq_key(k)
        if ck and ck not in seen:
            seen.add(ck)
            canon_keys.append(ck)

    # 2) Priority map (número más bajo = más prioritario)
    prio = {
        "horario": 0,
        "direccion": 1,
        "contacto": 2,
        "urgencias": 3,
        "tratamientos": 4,
        "seguros": 5,
        "pagos": 6,
        "políticas": 7,
        "parking": 8,
        "precios": 99,
    }

    # 3) Orden estable
    return sorted(canon_keys, key=lambda k: (prio.get(k, 50), k))


def answer_no_rag(_: str) -> str:
    return (
        "Puedo ayudarte a solicitar una cita. "
        "Recogeré tus datos (nombre, teléfono y motivo) y se los pasaré a recepción para que te llamen y la coordinen contigo."
    )


def answer_with_canned_or_rag(user_msg: str) -> tuple[str, list[str], float]:
    """
    1) Intenta responder con FAQs "enlatadas" (puede combinar varias: horario + dirección, etc.).
    2) Si no detecta ninguna FAQ conocida, cae a RAG normal.
    Devuelve: (respuesta, fuentes, confianza)
    """

    raw_keys = detect_faq_keys(user_msg)

    # Normalizamos a lista de strings
    if raw_keys is None:
        faq_keys: list[str] = []
    elif isinstance(raw_keys, str):
        faq_keys = [raw_keys]
    else:
        faq_keys = list(raw_keys)

    # PRIORIDAD: horario > resto > precios al final
    faq_keys = _sort_faq_keys(faq_keys)

    # Heurística: si parece una sola pregunta, limitamos a 1 FAQ
    low = (user_msg or "").lower()
    multi = (" y " in low) or (low.count("?") >= 2)
    if not multi and len(faq_keys) > 1:
        faq_keys = [faq_keys[0]]

    # 2) Si hay FAQs, intentamos responder solo con eso
    if faq_keys:
        parts: list[str] = []
        sources: list[str] = []
        print("DEBUG agent | faq_keys:", faq_keys)
        for k in faq_keys:
            txt, srcs = canned_faq_answer(k, user_msg)
            print("DEBUG agent | canned_faq_answer:", k, "=>", repr(txt), repr(srcs))
            if txt:
                parts.append(txt)
            if srcs:
                sources.extend(srcs)

        if parts:
            unique_sources = list(dict.fromkeys(sources))
            reply = "\n\n".join(parts)
            return reply, unique_sources, 1.0

    # 3) Fallback: usamos RAG "normal"
    ctx, srcs = build_context(user_msg)
    # Corregido: answer_with_rag solo toma 2 parámetros (user_msg, ctx)
    reply = answer_with_rag(user_msg, ctx)
    return reply, srcs, 0.5  # confianza media al ir por RAG


def answer_faq_if_any(user_msg: str) -> tuple[str, list[str]] | None:
    keys = detect_faq_keys(user_msg) or []
    if isinstance(keys, str):
        keys = [keys]
    else:
        keys = list(keys)

    keys = _sort_faq_keys(keys)

    low = (user_msg or "").lower()
    multi = (" y " in low) or (low.count("?") >= 2)
    if not multi and keys:
        keys = [keys[0]]
    parts: list[str] = []
    srcs: list[str] = []
    for k in keys:
        txt, s = canned_faq_answer(k, user_msg)
        if txt:
            parts.append(txt)
        if s:
            srcs.extend(s)

    if not parts:
        return None

    unique_sources = list(dict.fromkeys(srcs))
    return ("\n".join(parts), unique_sources)


RouteName = Literal[
    "BOOKING",
    "FAQ",
    "URGENT",
    "HANDOFF",
    "HUMAN_REQUEST",
    "SMALLTALK",
    "FALLBACK",
]


@dataclass
class RouteDecision:
    name: RouteName
    reason: str
    faq_keys: list[str] | None = None


def route_message(sender_id: str, user_msg: str, st) -> RouteDecision:
    raw = user_msg or ""
    low = raw.lower().strip()
    norm = unidecode(low)
    norm = re.sub(r"\s+", " ", norm).strip()

    # 0) Si ya estamos dentro del flujo de booking, NO salgas a SMALLTALK/FAQ/FALLBACK
    # Esto evita que un emoji / "ok" / ruido rompa el flujo (tests edge cases).
    step = getattr(st, "step", "idle")
    if step in ("name", "phone", "treatment", "urgency", "when"):
        return RouteDecision("BOOKING", "in_booking_flow")

    # 0.2) Smalltalk ultra-prioritario: si es saludo/thanks/adiós puro, NO lo mandes a booking
    if is_pure_greeting(raw) or is_thanks(raw) or is_goodbye(raw):
        return RouteDecision("SMALLTALK", "smalltalk")

    # 0.1) Si el usuario pide humano explícitamente, manda (incluso en booking)
    # (Si quieres que en booking NO corte y solo encole, dime y lo ajustamos)
    if wants_human(raw):
        return RouteDecision("HUMAN_REQUEST", "explicit_human_phrase")

    # A) Si estás en booking (no idle/handoff) => booking
    if st.step not in {"idle", "handoff"} and getattr(st, "status", "") != "needs_human":
        return RouteDecision("BOOKING", "in_booking_flow")

    # B) Si estás en handoff mode => HANDOFF
    if st.step == "handoff" or getattr(st, "status", "") == "needs_human":
        return RouteDecision("HANDOFF", "in_handoff_mode")

    # C) Cancel fuera de flujo
    if is_cancel(raw):
        return RouteDecision("SMALLTALK", "cancel_outside_flow")

    # D) Petición de cambiar/cancelar cita => NO booking (recepción)
    if is_appt_change_request(raw):
        return RouteDecision("HUMAN_REQUEST", "appt_change_request")

    # E) Urgencia gana a todo (fuera de booking/handoff)
    urg = clasifica_urgencia(raw)
    is_symptom_urgent = False
    try:
        sx = detectar_sintomas_urgentes(raw)
        is_symptom_urgent = any(sx.values()) if isinstance(sx, dict) else bool(sx)
    except Exception:
        is_symptom_urgent = False

    if urg == "alta" or is_symptom_urgent:
        return RouteDecision("URGENT", "urgent_detected")

    # F-1) Marcadores de dolor -> al menos BOOKING (para capturar datos)
    pain_markers = ["duele", "me duele", "dolor", "muela", "molar", "encía", "encias"]
    if any(k in norm for k in pain_markers):
        return RouteDecision("BOOKING", "pain_marker")

    # F) Señales duras de booking por datos (nombre/tel/tratamiento)
    if user_tried_phone_but_invalid(raw):
        return RouteDecision("BOOKING", "phone_attempt_invalid")

    try:
        ex = extract_booking_fields(raw) or {}
    except Exception:
        ex = {}

    has_phone = bool(ex.get("telefono")) or bool(normaliza_tel(raw))
    has_name = bool(ex.get("nombre"))
    has_treatment = bool(ex.get("tratamiento"))

    # "booking fuerte" (solo si realmente quiere pedir cita)
    wants_booking_strong = bool(
        re.search(
            r"\b(cita|citas)\b.*\b(pedir|reservar|agendar|agenciar|coger|sacar|solicitar|programar)\b"
            r"|\b(pedir|reservar|agendar|agenciar|coger|sacar|solicitar|programar)\b.*\b(cita|citas)\b"
            r"|\bquiero\b.*\b(cita|citas)\b"
            r"|\bnecesito\b.*\b(cita|citas)\b",
            norm,
        )
    )

    # ✅ Tratamiento SOLO no dispara booking (evita que "horario y precios de limpieza" se vaya a booking)
    if has_phone or has_name or (has_treatment and wants_booking_strong):
        return RouteDecision("BOOKING", "booking_data_present")

    # G) Intención
    intent = clasifica_intencion(raw)

    # H) FAQ determinista (con prioridad sobre "cita" si ES una pregunta)
    try:
        fk = detect_faq_keys(raw) or []
    except Exception:
        fk = []
    if isinstance(fk, str):
        fk = [fk]
    else:
        fk = list(fk)

    # "booking fuerte": solo si hay acción explícita de agendar/solicitar
    BOOKING_ACTION_RE = (
        r"\b(cita|citas)\b.*\b(pedir|reservar|agendar|agenciar|coger|sacar|solicitar|programar)\b"
        r"|\b(pedir|reservar|agendar|agenciar|coger|sacar|solicitar|programar)\b.*\b(cita|citas)\b"
    )

    wants_booking_strong = bool(re.search(BOOKING_ACTION_RE, norm))

    # Si hay keys FAQ y el mensaje parece pregunta, vamos a FAQ aunque el intent diga "cita",
    # siempre que NO sea booking fuerte (acción explícita).
    if fk and is_question_like(raw) and not wants_booking_strong:
        return RouteDecision("FAQ", "faq_question_over_booking", faq_keys=fk)

    # Si hay keys FAQ y NO es pregunta, también vamos a FAQ (por ejemplo: "horario", "precios")
    if fk:
        return RouteDecision("FAQ", "faq_keys_detected", faq_keys=fk)

    # I) Booking por keywords / intent
    wants_booking = wants_booking_strong
    if wants_booking or intent == "cita":
        return RouteDecision("BOOKING", "booking_intent")

    # J) Humano por intent (aunque no haya frase fuerte)
    if intent == "humano":
        return RouteDecision("HUMAN_REQUEST", "human_intent_classifier")

    # K) Blindaje: si parece pregunta, no puede acabar en FALLBACK.
    # Esto evita que preguntas tipo "Qué horarios tenéis?" se conviertan en pitch de booking.
    if is_question_like(raw):
        return RouteDecision("FAQ", "question_like_never_fallback", faq_keys=[])

    return RouteDecision("FALLBACK", "default")


def _handoff_worth_persisting_free(text: str) -> bool:
    """
    Decide si un mensaje libre merece guardarse como followup en DB.
    Regla: solo si aporta contexto clínico/logístico REAL, o pide explícitamente que se pase a recepción.
    """
    raw = (text or "").strip()
    if not raw:
        return False

    low = unidecode(raw.lower())
    low = re.sub(r"\s+", " ", low).strip()

    # Muy corto => casi siempre ruido
    if len(low) < 12:
        return False

    # Petición explícita de "pasar/decir/anotar"
    explicit_pass = [
        "díselo",
        "diselo",
        "decidle",
        "decirselo",
        "pásaselo",
        "pasaselo",
        "apúntalo",
        "apuntalo",
        "anótalo",
        "anotalo",
        "para recepcion",
        "para recepción",
        "tenedlo en cuenta",
        "tenlo en cuenta",
        "que lo sepan",
    ]
    if any(p in low for p in explicit_pass):
        return True

    # Señales clínicas/logísticas relevantes (no FAQ)
    high_signal = [
        "me duele",
        "dolor",
        "sangra",
        "sangrado",
        "hinch",
        "flemon",
        "flemón",
        "infecc",
        "absceso",
        "fiebre",
        "inflamad",
        "no puedo",
        "me es imposible",
        "alerg",
        "embaraz",
        "anticoagul",
        "diabet",
        "medicación",
        "medicacion",
        "urgente",
        "trauma",
        "golpe",
        "fractur",
        "se me ha roto",
        "se me cayó",
        "se me cayo",
        "solo por la mañana",
        "solo por la tarde",
        "solo tardes",
        "solo mañanas",
        "solo mananas",
        "antes de",
        "después de",
        "despues de",
    ]
    if any(k in low for k in high_signal):
        return True

    return False


def handle_handoff_mode(sender_id: str, user_msg: str, st, _out) -> tuple[str, list[str]]:
    raw = user_msg or ""

    # 0) Cancelación => reset
    if is_cancel(raw):
        reset_state(sender_id)
        return _out(
            "De acuerdo, lo dejamos aquí. Si más adelante quieres retomar la cita o tienes una duda, escríbeme.",
            [],
        )

    # 1) Preguntas típicas de "cuándo me llamáis" => respuesta dedicada (y NO encolar)
    if _is_when_calling_question(raw):
        return _out(_handoff_eta_reply(), [])

    # 2) Si es pregunta (con o sin FAQ keys) => contestar con canned/RAG y NO encolar
    #    Esto arregla: descuentos, precios, financiación, etc.
    if is_question_like(raw):
        reply, srcs, _conf = answer_with_canned_or_rag(raw)
        reply = clean_reply(reply)
        # Aquí no tienes decision.faq_keys; puedes recalcular detect_faq_keys(raw)
        keys = detect_faq_keys(raw) or []
        reply = maybe_dedupe_faq_reply(st, keys, reply)
        save_state(sender_id, st)
        return _out(ux_trim(reply), srcs)

    # 2.5) Respuestas cortas con "tratamiento" (ej: "Empaste") no son ruido.
    # Si estamos en handoff y el usuario da una palabra clínica, contestamos como FAQ de precio/contexto.
    if not is_question_like(raw):
        try:
            trat = clasifica_tratamiento(raw)
        except Exception:
            trat = None

        if trat or (
            len(raw.strip()) <= 20
            and any(
                k in unidecode(raw.lower())
                for k in ["empaste", "limpieza", "caries", "endodoncia", "implante", "ortodoncia"]
            )
        ):
            q = f"precio {raw}".strip()
            reply, srcs, _conf = answer_with_canned_or_rag(q)
            reply = clean_reply(reply)
            save_state(sender_id, st)
            return _out(ux_trim(reply), srcs)

    # 3) Gracias / despedida / neutrales => NO encolar
    if is_thanks(raw):
        return _out(
            "De nada. En cuanto recepción lo revise, te contactarán. Si quieres añadir algo, escríbelo por aquí.",
            [],
        )
    if is_goodbye(raw):
        return _out(
            f"{time_greeting()} En cuanto recepción lo revise, te contactarán. Un saludo.",
            [],
        )
    if is_neutral_human(raw) or _looks_like_noise(raw):
        return _out(
            "Perfecto. Si quieres añadir algún detalle para recepción (disponibilidad, seguro, motivo, etc.), dímelo por aquí.",
            [],
        )

    # 4) Urgencia detectada en handoff => aconsejar y encolar como followup_structured
    try:
        urg = clasifica_urgencia(raw)
    except Exception:
        urg = None
    try:
        sx = detectar_sintomas_urgentes(raw)
        sintomas_urg = any(sx.values()) if isinstance(sx, dict) else bool(sx)
    except Exception:
        sintomas_urg = False

    if urg == "alta" or sintomas_urg:
        enqueue_handoff(sender_id, raw, meta={"kind": "urgent", "step": "handoff"})
        return _out(
            "Por lo que comentas, conviene valorarlo cuanto antes. "
            "Si hay dolor fuerte, hinchazón o sangrado, lo ideal es que te vean hoy. "
            "Si puedes, dime tu teléfono (si no lo tienes ya enviado) y lo marco como urgente para recepción.",
            [],
        )

    # 5) Datos nuevos => actualizar estado + encolar estructurado
    try:
        ex = extract_booking_fields(raw) or {}
    except Exception:
        ex = {}

    tel_norm = normaliza_tel(raw)
    if tel_norm and not ex.get("telefono"):
        ex["telefono"] = tel_norm

    updated = False

    if ex.get("nombre") and (not st.nombre or st.nombre.strip() == ""):
        st.nombre = ex["nombre"]
        updated = True
    if ex.get("telefono") and (not st.telefono or st.telefono.strip() == ""):
        st.telefono = ex["telefono"]
        updated = True
    if ex.get("tratamiento") and (not st.tratamiento or st.tratamiento.strip() == ""):
        st.tratamiento = ex["tratamiento"]
        updated = True
    if ex.get("urgencia") and (not st.urgencia or st.urgencia.strip() == ""):
        st.urgencia = ex["urgencia"]
        updated = True
    if ex.get("preferencia") and (not st.preferencia or st.preferencia.strip() == ""):
        st.preferencia = ex["preferencia"]
        updated = True

    if updated:
        save_state(sender_id, st)
        enqueue_handoff(
            sender_id,
            handoff_summary(st),
            meta={"kind": "followup_structured", "step": "handoff"},
        )
        return _out(
            "Perfecto, queda anotado para recepción. Si quieres añadir algún detalle más, dímelo por aquí.",
            [],
        )

    # 6) Si no es pregunta, ni datos, ni ruido => encolar libre (una vez) y responder sin bucle
    if _handoff_worth_persisting_free(raw):
        enqueue_handoff(sender_id, raw, meta={"kind": "followup_free", "step": "handoff"})
        return _out("Perfecto, lo dejo anotado para recepción.", [])

    # Si no aporta nada, no ensucies la DB
    return _out(
        "Perfecto. Si quieres añadir algún detalle útil para recepción (motivo, disponibilidad, seguro, urgencia), escríbelo por aquí.",
        [],
    )


def _coerce_dt_utc(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    if isinstance(v, str):
        try:
            # soporta ISO con o sin Z
            s = v.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except Exception:
            return None
    return None


def respond(user_msg: str, sender: str | None = None) -> tuple[str, list[str]]:
    cleanup_sessions()
    sender_id = sender or "web-demo"

    log_event("msg_in", user_msg, sender_id)

    st = get_state(sender_id)
    now = datetime.now(UTC)

    prev = getattr(st, "last_seen", None)
    if prev and getattr(prev, "tzinfo", None) is None:
        prev = prev.replace(tzinfo=UTC)

    # TTL: idle/handoff = 12h | booking = 30min
    ttl = timedelta(hours=12) if st.step in ("idle", "handoff") else timedelta(minutes=30)

    # Expiró → reset y CORTA (no proceses el mensaje actual)
    if prev and (now - prev) > ttl:
        was_booking = st.step not in ("idle", "handoff")

        reset_state(sender_id)
        st = get_state(sender_id)

        # SOLO en booking queremos “Retomamos…”.
        # En idle/handoff, seguimos el flujo normal (p.ej. "hola" => menú).
        if was_booking:
            return (
                "Retomamos desde cero. ¿Quieres pedir una cita o tienes una duda?",
                [],
            )

    def _out(reply: str, sources: list[str] | None = None):
        if sources is None:
            sources = []
        log_event("msg_out", reply, sender_id, meta={"sources": sources})
        touch_state(sender_id, now)
        return (reply, sources)

    print("DEBUG RESP state:", sender_id, st.step)

    decision = route_message(sender_id, user_msg, st)
    log_event(
        "route",
        "",
        sender_id,
        meta={
            "name": decision.name,
            "reason": decision.reason,
            "step": getattr(st, "step", None),
        },
    )
    print("DEBUG ROUTE:", decision.name, decision.reason)

    if decision.name == "BOOKING":
        reply, sources = handle_booking(sender_id, user_msg)
        touch_state(sender_id, now)
        return reply, sources

    if decision.name == "HANDOFF":
        reply, sources = handle_handoff_mode(sender_id, user_msg, st, _out)
        # handle_handoff_mode usa _out, pero por seguridad dejamos esto (no rompe nada)
        touch_state(sender_id, now)
        return reply, sources

    if decision.name == "HUMAN_REQUEST":
        reply, sources = handle_human_request(sender_id, user_msg, st, _out)
        touch_state(sender_id, now)
        return reply, sources

    if decision.name == "URGENT":
        reply, sources = handle_urgent(sender_id, user_msg, _out)
        touch_state(sender_id, now)
        return reply, sources

    if decision.name == "FAQ":
        # firma determinista de la FAQ (para dedupe)
        try:
            keys = detect_faq_keys(user_msg) or []
            if isinstance(keys, str):
                keys = [keys]
            else:
                keys = list(keys)
        except Exception:
            keys = []

        keys = _sort_faq_keys(keys)
        sig = "|".join(keys[:2]) if keys else "rag"

        last_dt = _parse_iso_utc(getattr(st, "last_faq_at", None))
        if (
            getattr(st, "last_faq_sig", None) == sig
            and last_dt
            and (now - last_dt) <= FAQ_DEDUPE_WINDOW
        ):
            # NO repitas el tocho
            msg = "Te lo acabo de indicar arriba."
            return _out(msg, getattr(st, "last_faq_sources", []) or [])

        reply, srcs, _conf = answer_with_canned_or_rag(user_msg)
        reply = clean_reply(reply)
        reply = _trim_reply(clean_reply(reply), max_chars=180)

        # guarda memoria FAQ para dedupe
        st.last_faq_sig = sig
        st.last_faq_sources = srcs or []
        st.last_faq_at = _now_iso_utc()
        save_state(sender_id, st)

        return _out(reply, srcs)

    if decision.name == "SMALLTALK":
        return handle_smalltalk(sender_id, user_msg, _out, st)

    return _out(answer_no_rag(user_msg), [])


def clean_reply(text: str) -> str:
    if not text:
        return ""
    # normaliza saltos de línea “escapados” y reales
    t = text.replace("\\n", "\n")
    t = _NEWLINES.sub("\n", t)  # colapsa múltiples saltos
    t = _SPACES.sub(" ", t).strip()  # colapsa espacios
    return t


MAX_UX_CHARS = 900
TRUNC_SUFFIX = "\n\n…"


def ux_trim(text: str, max_chars: int = MAX_UX_CHARS) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t

    # Corte “limpio”: intenta cortar en salto de línea / punto cercano
    cut = max_chars - len(TRUNC_SUFFIX)
    if cut < 50:
        return (t[:max_chars]).rstrip() + "…"

    candidate = t[:cut]

    # Preferimos cortar en el último salto de línea razonable
    nl = candidate.rfind("\n")
    if nl > cut * 0.6:
        candidate = candidate[:nl].rstrip()
    else:
        # O en el último punto
        dot = candidate.rfind(". ")
        if dot > cut * 0.6:
            candidate = candidate[: dot + 1].rstrip()

    return candidate.rstrip() + TRUNC_SUFFIX


def handle_smalltalk(sender_id: str, user_msg: str, _out, st) -> tuple[str, list[str]]:
    # Cancel fuera de flujo
    if is_cancel(user_msg):
        reset_state(sender_id)
        return _out(
            "De acuerdo. Si en algún momento quieres pedir cita o hacer una consulta, dime y te ayudo.",
            [],
        )

    if is_pure_greeting(user_msg):

        def greeting_from_user(text: str) -> str | None:
            t = (text or "").strip().lower()
            t = re.sub(r"[^\w\sáéíóúüñ]", "", t)

            # ES
            if "buenas tardes" in t:
                return "¡Buenas tardes!"
            if "buenas noches" in t:
                return "¡Buenas noches!"
            if "buenos dias" in t or "buenos días" in t:
                return "¡Buenos días!"

            # EU
            if "kaixo" in t:
                return "Kaixo!"
            if "egun on" in t:
                return "Egun on!"
            if "arratsalde on" in t:
                return "Arratsalde on!"
            if "gabon" in t:
                return "Gabon!"
            if "Aupi" in t:
                return "Aupa!"
            return None

        g = greeting_from_user(user_msg) or time_greeting()
        return _out(
            f"{g} ¿En qué puedo ayudarte?\n"
            "1) Solicitar una cita (te llamarán para coordinarla)\n"
            "2) Horario / dirección / contacto\n"
            "3) Tengo dolor o una urgencia (te orientamos y avisamos a recepción)",
            [],
        )

    if is_thanks(user_msg):
        return _out("¡De nada! Si necesitas algo más, aquí estoy.", [])

    if is_goodbye(user_msg):
        return _out(f"{time_greeting()} Si necesitas algo más, escríbenos cuando quieras.", [])

    # Fallback smalltalk
    return _out("Dime, ¿en qué puedo ayudarte?", [])


def _looks_like_noise(text: str) -> bool:
    """Mensajes típicos que no aportan nada en modo handoff."""
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    noise = {
        "ok",
        "vale",
        "perfecto",
        "genial",
        "bien",
        "de acuerdo",
        "ok gracias",
        "vale gracias",
        "gracias",
        "gracias!",
        "thanks",
        "listo",
        "hecho",
        "okey",
        "oki",
    }
    if t in noise:
        return True
    # también corta cosas tipo "ok." "vale!" etc
    if len(t) <= 6 and re.fullmatch(r"[a-záéíóúüñ!. ]+", t):
        return True
    return False


def handle_urgent(sender_id: str, user_msg: str, _out) -> tuple[str, list[str]]:
    st = get_state(sender_id)
    raw = user_msg or ""

    # Detecta urgencia por síntomas (tu tool) o por clasificador
    urgent = False
    sx = None
    try:
        sx = detectar_sintomas_urgentes(raw)
        urgent = any(sx.values()) if isinstance(sx, dict) else bool(sx)
    except Exception:
        urgent = False

    urg = clasifica_urgencia(raw) or ("alta" if urgent else None)
    if urg == "alta":
        st.urgencia = "alta"

    # Intenta extraer datos si vienen en el primer mensaje
    try:
        ex = extract_booking_fields(raw) or {}
    except Exception:
        ex = {}

    tel_norm = normaliza_tel(raw)
    if tel_norm and not ex.get("telefono"):
        ex["telefono"] = tel_norm

    if ex.get("nombre") and not st.nombre:
        st.nombre = ex["nombre"]
    if ex.get("telefono") and not st.telefono:
        st.telefono = ex["telefono"]
    if ex.get("tratamiento") and not st.tratamiento:
        st.tratamiento = ex["tratamiento"]

    # Si no tenemos tratamiento, marca uno genérico de urgencia
    if not st.tratamiento:
        st.tratamiento = "urgencia / dolor"

    # Si falta nombre/teléfono, pídelo en modo claro (pero NO te quedes en booking)
    missing = []
    if not st.nombre:
        missing.append("nombre")
    if not st.telefono:
        missing.append("teléfono")

    # Encola SIEMPRE a recepción con lo que haya (modo urgente)
    summary = handoff_summary(st)
    enqueue_handoff(
        sender_id,
        summary,
        meta={"kind": "urgent", "step": getattr(st, "step", "idle")},
    )

    # Deja al usuario en handoff-mode para que pueda añadir cosas
    try:
        st.status = "needs_human"
    except Exception:
        pass
    st.step = "handoff"
    save_state(sender_id, st)

    if missing:
        return _out(
            "Por lo que comentas, conviene valorarlo cuanto antes. "
            "Voy a avisar a recepción ahora.\n\n"
            f"¿Me dejas tu {(' y '.join(missing))}? ",
            [],
        )

    return _out(
        "Por lo que comentas, conviene valorarlo cuanto antes. "
        "Aviso a recepción para que te llamen lo antes posible.",
        [],
    )


def handle_human_request(sender_id: str, user_msg: str, st, _out) -> tuple[str, list[str]]:
    if is_appt_change_request(user_msg):
        # No vendemos humo: no modificamos desde el bot
        # Solo derivamos a recepción
        enqueue_handoff(
            sender_id,
            f"Usuario solicita cambio/cancelación de cita. Mensaje: {user_msg}",
            meta={
                "kind": "explicit_human",
                "step": getattr(st, "step", "idle"),
                "reason": "appt_change_request",
            },
        )

        try:
            st.status = "needs_human"
        except Exception:
            pass
        st.step = "handoff"
        save_state(sender_id, st)

        return _out(
            "Para cambios o cancelaciones de cita tiene que gestionarlo recepción. "
            "Dime tu nombre y tu teléfono y se lo paso para que te llamen.",
            [],
        )

    # Aprovecha lo que venga en el mensaje
    extracted = extract_booking_fields(user_msg) or {}
    if extracted.get("nombre") and not st.nombre:
        st.nombre = extracted["nombre"]
    if extracted.get("telefono") and not st.telefono:
        st.telefono = extracted["telefono"]
    if extracted.get("tratamiento") and not st.tratamiento:
        st.tratamiento = extracted["tratamiento"]
    if extracted.get("urgencia") and not st.urgencia:
        st.urgencia = extracted["urgencia"]
    if extracted.get("preferencia") and not st.preferencia:
        st.preferencia = extracted["preferencia"]

    # Encola resumen a recepción aunque falten cosas
    summary = handoff_summary(st)

    has_any = any(
        [
            bool((st.nombre or "").strip()),
            bool((st.telefono or "").strip()),
            bool((st.tratamiento or "").strip()),
        ]
    )

    enqueue_handoff(
        sender_id,
        summary if has_any else "Usuario solicita hablar con recepción.",
        meta={"kind": "explicit_human", "step": getattr(st, "step", "idle")},
    )

    # Estado a handoff
    try:
        st.status = "needs_human"
    except Exception:
        pass
    st.faq_interrupts = 0
    st.step = "handoff"
    save_state(sender_id, st)

    missing = []
    if not st.nombre:
        missing.append("nombre")
    if not st.telefono:
        missing.append("teléfono")

    if missing:
        return _out(
            "De acuerdo. Te paso con recepción.\n\n¿Me dejas tu " + " y ".join(missing) + "?",
            [],
        )

    return _out("De acuerdo. Te paso con recepción para que te atienda una persona.", [])


def handoff_summary(st) -> str:
    nombre = (st.nombre or "").strip() or "—"
    tel = (st.telefono or "").strip() or "—"
    trat = (st.tratamiento or "").strip() or "—"
    urg = (st.urgencia or "").strip() or "baja"
    pref = (st.preferencia or "").strip() or "sin preferencia"

    return (
        "Solicitud de contacto para cita\n"
        f"Nombre: {nombre}\n"
        f"Tel: {tel}\n"
        f"Motivo: {trat}\n"
        f"Urgencia: {urg}\n"
        f"Preferencia: {pref}\n"
    )


def handle_booking(sender: str, user_msg: str) -> tuple[str, list[str]]:
    st = get_state(sender)
    print("DEBUG HB enter:", sender, "step=", st.step, "msg=", user_msg)

    def _first_name(full: str | None) -> str:
        t = (full or "").strip()
        if not t:
            return ""
        return t.split()[0].title()

    def _hb(
        reply: str,
        sources: list[str] | None = None,
        outcome: str | None = None,
        outcome_meta: dict | None = None,
        persist: bool = True,
    ) -> tuple[str, list[str]]:
        if sources is None:
            sources = []
        step = getattr(st, "step", None)

        if persist:
            save_state(sender, st)

        log_event("msg_out", reply, sender, meta={"sources": sources, "step": step})

        if outcome:
            log_event(f"outcome:{outcome}", "", sender, meta=outcome_meta or {"step": step})

        return (reply, sources)

    def _pending_prompt(step: str) -> str:
        if step == "name":
            return "Para seguir con la cita, ¿me dices tu nombre y apellido?"
        if step == "phone":
            return "Para seguir con la cita, ¿me dejas un teléfono de 9 dígitos, por favor?"
        if step == "treatment":
            return "Para seguir con la cita, ¿cuál es el motivo? (limpieza, implantes, dolor, revisión…)"
        if step == "urgency":
            return "Para seguir con la cita, ¿es algo urgente? (dolor fuerte, sangrado o hinchazón)"
        if step == "when":
            return "Para seguir con la cita, ¿tienes preferencia de horario? (mañanas/tardes/hoy/mañana o una hora aproximada)"
        return "Para seguir con la cita, dime lo que te falte por indicar."

    # --- BLINDAJE: cancelar flujo ---
    if st.step != "idle" and is_cancel(user_msg):
        reset_state(sender)
        # IMPORTANTÍSIMO: no persistas el 'st' viejo
        return _hb(
            "Perfecto, lo dejamos aquí. Si más adelante quieres retomarlo, dímelo y seguimos.",
            [],
            outcome="booking_cancelled",
            persist=False,
        )

    # --- BLINDAJE: negativa explícita en teléfono ---
    if st.step == "phone" and is_refusal(user_msg):
        st.phone_refusals = (st.phone_refusals or 0) + 1
        save_state(sender, st)

        if st.phone_refusals >= 2:
            # Salida elegante y cierre
            reset_state(sender)
            return _hb(
                "Entendido. Sin un teléfono no puedo dejar la cita registrada. "
                "Si prefieres, puedes llamarnos y te lo gestionan por teléfono.",
                ["backend/data/dental_faq.md"],
                outcome="phone_refused",
            )

        return _hb(
            "Entiendo. Para que recepción pueda confirmarte la cita necesitamos un teléfono de contacto. "
            "Si no te viene bien, también puedes llamarnos directamente. ¿Me lo facilitas?",
            ["backend/data/dental_faq.md"],
            outcome="phone_refusal_1",
        )

    # 0) Timeout booking (robusto incluso si last_seen viene como str)
    now = datetime.now(UTC)
    prev = _coerce_dt_utc(getattr(st, "last_seen", None))

    if prev and (now - prev) > timedelta(minutes=30):
        reset_state(sender)
        # IMPORTANTE: NO reinicies booking en este mismo turno
        # Queremos que el usuario “vuelva a empezar” desde idle.
        return _hb(
            "Retomamos desde cero. ¿Quieres pedir una cita o tienes una duda?",
            [],
            outcome="timeout",
        )

    def _finalize_to_handoff() -> tuple[str, list[str]]:
        # Asegura mínimos razonables
        if not st.urgencia:
            st.urgencia = "baja"
        if not st.preferencia:
            st.preferencia = "sin preferencia"

        # 1) Guardar lead (opcional pero útil para métricas/CRM)
        notes = []
        if st.preferencia:
            notes.append(f"Pref: {st.preferencia}")
        if st.urgencia:
            notes.append(f"Urg: {st.urgencia}")

        trat = (st.tratamiento or "").strip()
        if notes:
            trat = f"{trat} | " + " | ".join(notes)

        lead_id = None
        try:
            lead_id = save_lead(
                st.nombre or "",
                st.telefono or "",
                trat,
                st.urgencia or "baja",
                "whatsapp",
            )
        except Exception as e:
            print("DEBUG save_lead failed:", e)

        # 2) Encolar handoff a recepción
        summary = handoff_summary(st)
        enqueue_handoff(
            sender,
            summary,
            meta={
                "kind": "booking_final",
                "lead_id": lead_id,
                "nombre": st.nombre,
                "telefono": st.telefono,
                "tratamiento": st.tratamiento,
                "urgencia": st.urgencia,
                "preferencia": st.preferencia,
                "step": st.step,
            },
        )
        # --- NOTIFY (Sheets + Email) en background: NUNCA bloquea el reply a Twilio ---
        try:
            import threading

            from .notify import send_handoff_email, send_handoff_to_sheets

            payload = {
                "kind": "booking_final",
                "lead_id": lead_id,
                "nombre": st.nombre,
                "telefono": st.telefono,
                "tratamiento": st.tratamiento,
                "urgencia": st.urgencia,
                "preferencia": st.preferencia,
                "sender": sender,
            }

            subject = f"[Dental Agent] Nuevo lead ({st.urgencia or 'normal'}) - {st.nombre or 'Sin nombre'}"
            body = (
                "Nuevo lead\n"
                f"- Nombre: {st.nombre}\n"
                f"- Teléfono: {st.telefono}\n"
                f"- Motivo: {st.tratamiento}\n"
                f"- Urgencia: {st.urgencia}\n"
                f"- Preferencia: {st.preferencia}\n"
                f"- Sender: {sender}\n"
                f"- Lead ID: {lead_id}\n"
            )

            def _notify_bg():
                try:
                    sheets_ok = send_handoff_to_sheets(payload)
                    print(f"[SHEETS] ok={sheets_ok}")
                except Exception as e:
                    print(f"[SHEETS] ERROR: {type(e).__name__}: {e}")

            try:
                email_ok = send_handoff_email(subject, body)
                print(f"[EMAIL] ok={email_ok}")
            except Exception as e:
                print(f"[EMAIL] ERROR: {type(e).__name__}: {e}")

            threading.Thread(target=_notify_bg, daemon=True).start()

        except Exception as e:
            print(f"[NOTIFY] ERROR (ignored): {type(e).__name__}: {e}")

        # 3) Cerrar flujo automático y dejar en handoff
        try:
            st.status = "needs_human"
        except Exception:
            pass
        st.faq_interrupts = 0
        st.step = "handoff"
        save_state(sender, st)

        return _hb(
            "Perfecto, ya tengo los datos. Se lo paso a recepción para que te llamen y coordinen la cita.",
            [],
            outcome="handoff_enqueued",
            outcome_meta={"lead_id": lead_id},
        )

    # 1) Derivación a humano en cualquier punto
    if wants_human(user_msg):
        # Si el usuario pide humano, igual mandamos lo que tengamos
        extracted = extract_booking_fields(user_msg) or {}
        if extracted.get("nombre") and not st.nombre:
            st.nombre = extracted["nombre"]
        if extracted.get("telefono") and not st.telefono:
            st.telefono = extracted["telefono"]
        if extracted.get("tratamiento") and not st.tratamiento:
            st.tratamiento = extracted["tratamiento"]
        if extracted.get("urgencia") and not st.urgencia:
            st.urgencia = extracted["urgencia"]
        if extracted.get("preferencia") and not st.preferencia:
            st.preferencia = extracted["preferencia"]

        # Si faltan datos mínimos, pedimos solo nombre/teléfono. Si ya están, handoff directo.
        missing = []
        if not st.nombre:
            missing.append("nombre")
        if not st.telefono:
            missing.append("teléfono")

        summary = handoff_summary(st)

        has_any = any(
            [
                bool((st.nombre or "").strip()),
                bool((st.telefono or "").strip()),
                bool((st.tratamiento or "").strip()),
                bool((st.preferencia or "").strip()),
                bool((st.urgencia or "").strip()),
            ]
        )

        enqueue_handoff(
            sender,
            summary if has_any else "Usuario solicita hablar con recepción.",
            meta={"kind": "explicit_human", "step": st.step},
        )

        st.faq_interrupts = 0
        st.step = "handoff"
        save_state(sender, st)

        if missing:
            return _hb(
                "De acuerdo. Para que recepción te llame, dime tu nombre y un teléfono de contacto, por favor.",
                [],
                outcome="needs_human",
                outcome_meta={"step": "handoff"},
            )

        return _hb(
            "De acuerdo. Recepción se pondrá en contacto contigo lo antes posible.",
            [],
            outcome="needs_human",
            outcome_meta={"step": "handoff"},
        )

    # 1.5) FAQ en medio del booking: responder breve y retomar el dato pendiente (SIN cambiar st.step)
    if st.step != "idle":
        try:
            faq_keys = detect_faq_keys(user_msg) or []
        except Exception:
            faq_keys = []

        if st.step == "treatment" and clasifica_tratamiento(user_msg):
            faq_keys = []

        if st.step == "phone" and normaliza_tel(user_msg):
            faq_keys = []

        # Evita colisión "mañana/tarde" (preferencia) vs FAQ "horario"
        if st.step == "when":
            ex_when = extract_booking_fields(user_msg) or {}
            if (
                ex_when.get("preferencia")
                or is_indifferent(user_msg)
                or is_neutral_human(user_msg)
                or is_hold(user_msg)
            ):
                faq_keys = []

        # FAQ en medio del flujo SOLO si el mensaje parece pregunta
        if faq_keys:
            if st.step == "when":
                if "?" not in (user_msg or "") and "¿" not in (user_msg or ""):
                    faq_keys = []
            else:
                if not is_question_like(user_msg):
                    faq_keys = []

        if faq_keys:
            # Heurística: si no es multi-pregunta, respondemos solo la primera
            low = (user_msg or "").lower()
            multi = (" y " in low) or (low.count("?") >= 2)
            if not multi:
                faq_keys = faq_keys[:1]
            else:
                faq_keys = faq_keys[:2]  # máximo 2 para no soltar biblia

            parts: list[str] = []
            srcs: list[str] = []
            for k in faq_keys:
                txt, s = canned_faq_answer(k, user_msg)
                if txt:
                    parts.append(txt)
                if s:
                    srcs.extend(s)

            if parts:
                faq_text = "\n".join(parts).strip()
                srcs = list(dict.fromkeys(srcs))

                # contador de interrupciones FAQ durante booking
                st.faq_interrupts = (getattr(st, "faq_interrupts", 0) or 0) + 1
                lead_in = resume_phrase(st.faq_interrupts)

                return _hb(f"{faq_text}\n\n{lead_in} {_pending_prompt(st.step)}", srcs)

    # 2) “Espera / pausa” (solo si ya estamos en flujo)
    if st.step != "idle" and is_hold(user_msg):
        # Si cancela, corta
        if is_cancel(user_msg):
            reset_state(sender)
            return _hb(
                "De acuerdo, lo dejamos aquí. Si más adelante quieres pedir cita, escríbeme y lo retomamos.",
                [],
                outcome="booking_cancelled",
                outcome_meta={"step": st.step},
                persist=False,
            )

        # Pausa normal: no respondas FAQs aquí (se gestionan en 1.5)
        return _hb("Sin problema. Cuando puedas, dime y seguimos con la cita.", [])

    # 3) Extracción automática (no pisa lo existente)
    # IMPORTANTE: en step=name NO llamamos a extract_booking_fields (puede bloquear/LLM/timeout Twilio).
    if st.step == "name":
        # --- BLINDAJE: en step=name, smalltalk NO puede ser nombre ---
        if is_pure_greeting(user_msg) or is_thanks(user_msg) or is_goodbye(user_msg):
            return _hb("Para seguir con la cita, dime tu nombre y apellido, por favor.", [])

        extracted = {}
    else:
        extracted = extract_booking_fields(user_msg)

    if not isinstance(extracted, dict):
        extracted = {}

    print("DEBUG extracted type:", type(extracted), "value:", extracted)

    if extracted.get("nombre") and not st.nombre:
        st.nombre = extracted["nombre"]
    if extracted.get("telefono") and not st.telefono:
        st.telefono = extracted["telefono"]
    if extracted.get("tratamiento") and not st.tratamiento:
        st.tratamiento = extracted["tratamiento"]
    if extracted.get("urgencia") and not st.urgencia:
        st.urgencia = extracted["urgencia"]
    if extracted.get("preferencia") and not st.preferencia:
        st.preferencia = extracted["preferencia"]

    print(
        "DEBUG st after:",
        st.nombre,
        st.telefono,
        st.tratamiento,
        st.urgencia,
        st.preferencia,
    )

    # AUTO-AVANCE: si ya tenemos nombre+tel+motivo, seguimos el flujo para completar urgencia/preferencia
    if st.nombre and st.telefono and st.tratamiento and st.step == "idle":
        if not st.urgencia:
            if treatment_implies_low_urgency(st.tratamiento) and not treatment_may_be_urgent(
                st.tratamiento
            ):
                st.urgencia = "baja"
                st.step = "when"
                st.neutral_hits = 0
                return _hb(
                    "¿Tienes preferencia de horario? (mañanas/tardes/hoy/mañana o una hora aproximada)",
                    [],
                )

            st.step = "urgency"
            return _hb(
                "¿Es algo urgente? Dime si hay dolor fuerte, sangrado o hinchazón (o si no es urgente).",
                [],
            )

        if not st.preferencia:
            st.step = "when"
            st.neutral_hits = 0
            return _hb(
                "¿Tienes preferencia de horario? (mañanas/tardes/hoy/mañana o una hora aproximada)",
                [],
            )

        return _finalize_to_handoff()

    # 4) Arranque del flujo

    if st.step == "idle":
        extracted0 = extract_booking_fields(user_msg) or {}
        tel0 = normaliza_tel(user_msg)
        if tel0 and not extracted0.get("telefono"):
            extracted0["telefono"] = tel0

        if extracted0.get("nombre") and not st.nombre:
            st.nombre = extracted0["nombre"]
        if extracted0.get("telefono") and not st.telefono:
            st.telefono = extracted0["telefono"]
        if extracted0.get("tratamiento") and not st.tratamiento:
            st.tratamiento = extracted0["tratamiento"]
        if extracted0.get("urgencia") and not st.urgencia:
            st.urgencia = extracted0["urgencia"]
        if extracted0.get("preferencia") and not st.preferencia:
            st.preferencia = extracted0["preferencia"]

    if st.step == "idle":
        if not st.nombre:
            st.step = "name"
            return _hb("Perfecto, ¿me dices tu nombre y apellido?", [])

        if not st.telefono:
            st.step = "phone"
            # Si el usuario intentó dar teléfono pero es inválido, dilo claro
            if user_tried_phone_but_invalid(user_msg):
                return _hb(
                    f"Gracias, {_first_name(st.nombre)}. Ese número no me cuadra. "
                    "Envíame un teléfono válido de 9 dígitos (por ejemplo 612345678), por favor.",
                    [],
                )
            return _hb(f"Gracias, {_first_name(st.nombre)}. ¿Me dejas un teléfono de contacto?", [])

        if not st.tratamiento:
            st.step = "treatment"
            return _hb(
                "¿Por qué motivo es la cita? (limpieza, implantes, dolor, revisión…)",
                [],
            )

        if not st.urgencia:
            st.step = "urgency"
            return _hb("¿Es algo urgente? Dime si hay dolor fuerte, sangrado o hinchazón.", [])

        # Preferencia: la pedimos una vez si no está
        if not st.preferencia:
            st.step = "when"
            st.neutral_hits = 0  # reutilizamos neutral_hits como contador de repregunta en when
            return _hb(
                "¿Tienes preferencia de horario? (mañanas/tardes/hoy/mañana o una hora aproximada)",
                [],
            )

        return _finalize_to_handoff()

    # 5) Pasos individuales
    if st.step == "name":
        # --- BLINDAJE: en step=name, smalltalk NO puede ser nombre ---
        if is_pure_greeting(user_msg) or is_thanks(user_msg) or is_goodbye(user_msg):
            return _hb("Para seguir con la cita, dime tu nombre y apellido, por favor.", [])

        # Si el usuario responde con urgencia/preferencia/ruido, NO lo trates como nombre
        low = unidecode((user_msg or "").lower())

        # Preferencias tipo "por la tarde/mañana/hoy/mañana"
        try:
            ex = extract_booking_fields(user_msg) or {}
        except Exception:
            ex = {}

        looks_like_pref = bool(ex.get("preferencia"))
        looks_like_urgent = (
            ("urgente" in low) or ("urgencia" in low) or (clasifica_urgencia(user_msg) == "alta")
        )

        # Palabras que nunca deben ser nombre
        banned_name_tokens = [
            "urgente",
            "urgencia",
            "dolor",
            "muela",
            "sangra",
            "sangrado",
            "hinch",
            "flemon",
            "mañana",
            "manana",
            "tarde",
            "hoy",
            "cita",
        ]
        looks_like_not_name = any(t in low for t in banned_name_tokens)

        if looks_like_pref or looks_like_urgent or looks_like_not_name:
            return _hb("Para seguir, dime solo tu nombre, por favor.", [])

        # Si ya tenemos nombre (por extracción automática), avanzamos sin preguntar
        if st.nombre:
            st.step = (
                "phone"
                if not st.telefono
                else (
                    "treatment"
                    if not st.tratamiento
                    else (
                        "urgency"
                        if not st.urgencia
                        else ("when" if not st.preferencia else "handoff")
                    )
                )
            )
            # Reutiliza el mismo texto de cada paso
            if st.step == "phone":
                return _hb(
                    f"Gracias, {_first_name(st.nombre)}. ¿Me dejas un teléfono de contacto?", []
                )
            if st.step == "treatment":
                return _hb(
                    "¿Por qué motivo es la cita? (limpieza, implantes, dolor, revisión…)",
                    [],
                )
            if st.step == "urgency":
                return _hb(
                    "¿Es algo urgente? Dime si hay dolor fuerte, sangrado o hinchazón.",
                    [],
                )
            if st.step == "when":
                st.neutral_hits = 0
                return _hb(
                    "¿Tienes preferencia de horario? (mañanas/tardes/hoy/mañana o una hora aproximada)",
                    [],
                )
            return _finalize_to_handoff()

        # Si no tenemos nombre, entonces sí manejamos neutros/pausas
        if is_neutral_human(user_msg) or is_hold(user_msg):
            return _hb("Cuando puedas, dime tu nombre, por favor.", [])

        name = (user_msg or "").strip().split("\n")[0]
        name = re.split(
            r",|;|\s+y\s+| mi telefono| mi teléfono| telefono| teléfono| tel",
            name,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        name = re.sub(r"[^\w\sáéíóúüñ'-]", "", name).strip()

        if len(name) < 2 or any(ch.isdigit() for ch in name):
            return _hb("Perdona, dime tu nombre y apellido, por favor.", [])

        # EXIGE al menos 2 palabras (nombre + apellido)
        if len(name.split()) < 2:
            return _hb("Para registrarlo bien, dime tu nombre y apellido, por favor.", [])

        if len(name) > 40:
            return _hb("Dime tu nombre y apellido, por favor (por ejemplo: “Laura García”).", [])

        st.nombre = name.title()
        st.step = "phone"
        return _hb(f"Gracias, {_first_name(st.nombre)}. ¿Me dejas un teléfono de contacto?", [])

    if st.step == "phone":
        has_digits = bool(re.search(r"\d", user_msg or ""))
        tel = normaliza_tel(user_msg)

        if not tel:
            # No ha intentado dar un número, solo texto
            if not has_digits:
                st.step_retries = (getattr(st, "step_retries", 0) or 0) + 1
                save_state(sender, st)
                return _hb(
                    "Para continuar, necesito un teléfono de contacto de 9 dígitos (por ejemplo 612345678).",
                    [],
                )

            # Ha intentado dar un número pero es incorrecto
            return _hb(
                "Ese número no me cuadra. Envíame un teléfono válido (9 dígitos), por favor.",
                [],
            )

        # Teléfono correcto
        st.telefono = tel
        st.step = "treatment"
        st.step_retries = 0
        return _hb("¿Por qué motivo es la cita? (limpieza, implantes, dolor…)", [])

    if st.step == "treatment":
        low = unidecode((user_msg or "").lower())

        # Si el usuario responde con urgencia (sin motivo), no lo guardes como tratamiento
        if ("urgente" in low) or ("urgencia" in low) or (clasifica_urgencia(user_msg) == "alta"):
            st.urgencia = "alta"
            st.step = "when"
            st.neutral_hits = 0
            return _hb(
                "Entendido. ¿Tienes preferencia de horario? (mañanas/tardes/hoy/mañana o una hora aproximada)",
                [],
            )

        if is_neutral_human(user_msg) or is_hold(user_msg):
            return _hb(
                "Dime el motivo de la cita, por favor (limpieza, implantes, dolor, revisión…)",
                [],
            )

        if is_indifferent(user_msg):
            return _hb(
                "Vale. Para anotarlo bien, dime solo el motivo: limpieza, implantes, dolor, revisión…",
                [],
            )

        st.tratamiento = clasifica_tratamiento(user_msg) or (user_msg or "").strip().lower()
        # --- AUTO-URGENCIA: si el mensaje trae síntomas urgentes, no preguntes "¿es urgente?" ---
        if hay_sintomas_urgentes(user_msg) or treatment_may_be_urgent(st.tratamiento):
            st.urgencia = "alta"
            st.step = "when"
            st.neutral_hits = 0
            return _hb(
                "Entendido. Por lo que comentas, conviene valorarlo cuanto antes. "
                "¿Tienes preferencia de horario? (mañanas/tardes/hoy/mañana o una hora aproximada)",
                [],
            )
        # --- FIN AUTO-URGENCIA ---

        # Si el motivo es claramente electivo, no preguntes urgencia
        if treatment_implies_low_urgency(st.tratamiento) and not treatment_may_be_urgent(
            st.tratamiento
        ):
            st.urgencia = "baja"
            st.step = "when"
            st.neutral_hits = 0
            return _hb(
                "Perfecto. ¿Tienes preferencia de horario? (mañanas/tardes/hoy/mañana o una hora aproximada)",
                [],
            )

        # Si puede ser urgencia o es ambiguo, sí preguntamos
        st.step = "urgency"
        return _hb(
            "¿Es algo urgente? Dime si hay dolor fuerte, sangrado o hinchazón (o si no es urgente).",
            [],
        )

    if st.step == "urgency":
        if is_neutral_human(user_msg) or is_hold(user_msg):
            return _hb(
                "Dime si hay dolor fuerte, sangrado o hinchazón (o si no es urgente).",
                [],
            )

        # NUEVO: gestión de "no lo sé"
        t = (user_msg or "").lower()
        if any(x in t for x in ["no lo se", "no lo sé", "ni idea", "no estoy seguro", "depende"]):
            st.neutral_hits = (st.neutral_hits or 0) + 1
            if st.neutral_hits == 1:
                return _hb(
                    "Sin problema. ¿Tienes dolor fuerte, sangrado o hinchazón? (si no, lo marco como no urgente)",
                    [],
                )
            else:
                st.urgencia = "baja"

        if is_indifferent(user_msg):
            st.urgencia = "baja"
        else:
            st.urgencia = clasifica_urgencia(user_msg) or "baja"

        # Preferencia: solo dato útil para recepción (no proponemos horas)
        if not st.preferencia:
            st.step = "when"
            st.neutral_hits = 0
            if st.urgencia == "alta":
                return _hb(
                    "Entendido. Por lo que comentas, conviene valorarlo cuanto antes. "
                    "¿Tienes preferencia de horario? (mañanas/tardes/hoy/mañana o una hora aproximada)",
                    [],
                )
            return _hb(
                "¿Tienes preferencia de horario? (mañanas/tardes/hoy/mañana o una hora aproximada)",
                [],
            )

        return _finalize_to_handoff()

    if st.step == "when":
        txt = (user_msg or "").strip()

        # Si responde neutro / indiferente -> no bloqueamos
        if is_indifferent(txt) or is_neutral_human(txt) or is_hold(txt):
            st.preferencia = "sin preferencia"
            return _finalize_to_handoff()

        extracted2 = extract_booking_fields(txt) or {}
        pref = extracted2.get("preferencia")

        if not pref:
            # Solo UNA repregunta. Después, sin preferencia y handoff.
            st.neutral_hits = (st.neutral_hits or 0) + 1
            if st.neutral_hits >= 1:
                st.preferencia = "sin preferencia"
                return _finalize_to_handoff()

            return _hb("Perfecto. ¿Mañanas o tardes, o te da igual?", [])

        st.preferencia = pref
        return _finalize_to_handoff()

    # Fallback de seguridad
    st.step = "idle"
    return _hb(
        "Puedo ayudarte a gestionar una cita. ¿Quieres que empecemos?",
        [],
        outcome="abandoned",
    )
