from datetime import UTC, datetime, timedelta

import pytest

from backend.agent import respond
from backend.store import get_state, reset_state, save_state


def run(sender, msgs):
    out = []
    for m in msgs:
        r, sources = respond(m, sender=sender)
        st = get_state(sender)
        out.append(
            (
                m,
                r,
                sources,
                st.step,
                st.nombre,
                st.telefono,
                st.tratamiento,
                st.urgencia,
                st.preferencia,
            )
        )
    return out


@pytest.mark.parametrize(
    "name,msgs,expect",
    [
        (
            "tel con espacios -> normaliza y avanza",
            ["Quiero cita", "Lander Iglesias", "612 345 678"],
            {"step_after": "treatment", "tel": "612345678"},
        ),
        (
            "tel con guiones -> normaliza y avanza",
            ["Quiero cita", "Lander Iglesias", "612-345-678"],
            {"step_after": "treatment", "tel": "612345678"},
        ),
        (
            "tel con prefijo +34 -> últimos 9",
            ["Quiero cita", "Lander Iglesias", "+34 612 345 678"],
            {"step_after": "treatment", "tel": "612345678"},
        ),
        (
            "tel dentro de frase -> extrae y avanza",
            ["Quiero cita", "Lander Iglesias", "mi número es 612 345 678"],
            {"step_after": "treatment", "tel": "612345678"},
        ),
        (
            "ruido en name (emoji) -> repregunta nombre",
            ["Quiero cita", "👍", "Lander Iglesias"],
            {"step_after": "phone", "must_contain": ["nombre"]},
        ),
        (
            "ruido en phone (ok) -> repregunta teléfono",
            ["Quiero cita", "Lander Iglesias", "ok", "612345678"],
            {
                "step_after": "treatment",
                "tel": "612345678",
                "must_contain": ["teléfono"],
            },
        ),
        (
            "audio placeholder en phone -> repregunta teléfono",
            ["Quiero cita", "Lander Iglesias", "te mando un audio", "612345678"],
            {
                "step_after": "treatment",
                "tel": "612345678",
                "must_contain": ["teléfono"],
            },
        ),
        (
            "mensaje partido nombre+tel -> completa",
            [
                "Quiero cita",
                "Manuel Iglesias",
                "675 701 597",
                "Dolor",
                "No es urgente",
                "Por la tarde",
            ],
            {"final_step": "handoff", "tel": "675701597"},
        ),
        (
            "booking + saludo en medio -> NO resetea y retoma",
            [
                "Quiero cita",
                "Hola",  # interrupción típica que antes rompía flujos
                "Lander Iglesias",
                "612345678",
                "Limpieza",
                "No es urgente",
                "Por la tarde",
            ],
            {
                "final_step": "handoff",
                "tel": "612345678",
                "urg": "baja",
                "must_contain": [
                    "nombre y apellido",  # debe seguir pidiendo nombre, no irse a cualquier lado
                ],
            },
        ),
        (
            "handoff + ruido ok -> mantiene handoff",
            [
                "Prefiero hablar con una persona",
                "ok",  # ruido típico: no debe romper ni resetear
            ],
            {
                "final_step": "handoff",
                "must_contain": [
                    "recepción",  # debe seguir en modo derivado
                ],
            },
        ),
        (
            "booking + faq interruption (precios) -> retoma y completa",
            [
                "Quiero cita",
                "¿Cuánto cuesta una limpieza?",
                "Lander Iglesias",
                "612345678",
                "Limpieza",
                "No es urgente",
                "Por la tarde",
            ],
            {
                "final_step": "handoff",
                "tel": "612345678",
                "urg": "baja",
                "must_contain": [
                    "€",
                    "limpieza",
                ],  # blando: que haya info de precio/limpieza
            },
        ),
        (
            "cancel a mitad de booking -> reset a idle",
            [
                "Quiero cita",
                "Lander Iglesias",
                "mejor no",
            ],
            {
                "final_step": "idle",
                "must_contain": ["dejamos", "lo dejamos", "de acuerdo"],  # blando
            },
        ),
        (
            "handoff + pregunta horario -> responde y mantiene handoff",
            [
                "Prefiero hablar con una persona",
                "¿A qué hora llamáis?",
            ],
            {
                "final_step": "handoff",
                "must_contain": [
                    "l-v",
                    "lunes",
                    "sáb",
                    "sabado",
                    "sábado",
                    "09:",
                ],  # blando
                "sources_required": True,
            },
        ),
        (
            "dolor -> booking completo",
            [
                "Hola",
                "Me duele la muela",
                "Manuel Iglesias",
                "675701597",
                "Es urgente",
                "Por la tarde",
            ],
            {
                "final_step": "handoff",
                "tel": "675701597",
                "urg": "alta",
            },
        ),
        (
            "telefono 10 digitos -> normaliza",
            ["Quiero cita", "Lander Iglesias", "6450000000"],
            {
                "step_after": "treatment",  # porque el tel se acepta
                "tel": "645000000",  # ultimos 9
            },
        ),
    ],
)
def test_whatsapp_edge_cases(name, msgs, expect):
    sender = f"scenario-{name}"
    reset_state(sender)

    trace = run(sender, msgs)
    last = trace[-1]
    _user, bot, sources, step, nombre, tel, trat, urg, pref = last

    if "final_step" in expect:
        assert step == expect["final_step"]

    if "step_after" in expect:
        assert step == expect["step_after"]

    if "tel" in expect:
        assert tel == expect["tel"]

    if "urg" in expect:
        assert urg == expect["urg"]

    if expect.get("sources_required"):
        assert sources  # sources del ÚLTIMO turno, sin mutar estado

    # blando: busca tokens en todo el texto del bot (ya tienes este bloque en tu archivo)
    if "must_contain" in expect:
        all_bot_text = "\n".join([(b or "") for (_u, b, _s, *_rest) in trace]).lower()
        assert any(tok.lower() in all_bot_text for tok in expect["must_contain"])


def test_booking_timeout_31min_resets_to_idle():
    """
    Si el usuario está en booking y pasan >30 min sin actividad,
    debe resetear el flujo y NO continuar pidiendo el dato anterior.
    """
    sender = "scenario-timeout-booking-31m"
    reset_state(sender)

    # Arranca booking -> se queda pidiendo nombre
    respond("Quiero cita", sender=sender)
    st = get_state(sender)
    assert st.step == "name"

    # Simula que el usuario se quedó colgado en booking hace 31 min
    st.last_seen = datetime.now(UTC) - timedelta(minutes=31)
    save_state(sender, st)

    # Ahora escribe cualquier cosa: debe resetear y decir que retoma desde cero
    reply, _ = respond("hola", sender=sender)
    st2 = get_state(sender)

    assert st2.step == "idle"
    assert "retomamos" in (reply or "").lower()


def test_booking_timeout_10min_does_not_reset():
    """
    Si han pasado pocos minutos, NO resetea: mantiene el paso en curso.
    """
    sender = "scenario-timeout-booking-10m"
    reset_state(sender)

    respond("Quiero cita", sender=sender)
    st = get_state(sender)
    assert st.step == "name"

    st.last_seen = datetime.now(UTC) - timedelta(minutes=10)
    save_state(sender, st)

    reply, _ = respond("Lander Iglesias", sender=sender)
    st2 = get_state(sender)

    # Debe avanzar a phone, no resetear a idle
    assert st2.step == "phone"
    assert "tel" in (reply or "").lower()


def test_idle_ttl_13h_resets_cleanly():
    """
    En idle, TTL = 12h. Si pasan 13h, resetea estado (no debe romper).
    """
    sender = "scenario-ttl-idle-13h"
    reset_state(sender)

    st = get_state(sender)
    st.step = "idle"
    st.last_seen = datetime.now(UTC) - timedelta(hours=13)
    save_state(sender, st)

    reply, _ = respond("hola", sender=sender)
    st2 = get_state(sender)

    assert st2.step == "idle"
    # El saludo debe funcionar “normal” (menú)
    assert "1)" in (reply or "")
    assert "2)" in (reply or "")
    assert "3)" in (reply or "")


def test_handoff_ttl_13h_resets_to_idle_and_no_handoff_mode():
    """
    En handoff, TTL = 12h. Si pasan 13h, debe salir de handoff.
    """
    sender = "scenario-ttl-handoff-13h"
    reset_state(sender)

    # Fuerza estado handoff
    st = get_state(sender)
    st.step = "handoff"
    st.status = "needs_human"
    st.last_seen = datetime.now(UTC) - timedelta(hours=13)
    save_state(sender, st)

    reply, _ = respond("ok", sender=sender)
    st2 = get_state(sender)

    assert st2.step == "idle"
    # En idle, 'ok' suele caer a fallback no-rag
    assert "cita" in (reply or "").lower()


def test_store_respects_last_seen_when_saving():
    sender = "scenario-store-last-seen"
    reset_state(sender)

    st = get_state(sender)
    st.step = "name"
    st.last_seen = datetime.now(UTC) - timedelta(minutes=31)
    save_state(sender, st)

    st2 = get_state(sender)
    assert st2.step == "name"
    assert st2.last_seen is not None
    assert (datetime.now(UTC) - st2.last_seen).total_seconds() > 30 * 60


def test_faq_priority_horario_before_precios():
    sender = "scenario-faq-priority"
    reset_state(sender)

    r, _ = respond("Horario y precios de limpieza", sender=sender)
    low = (r or "").lower()

    # Debe contener horario
    assert any(tok in low for tok in ("l-v", "lunes", "09:"))

    # Si menciona precios, horario debe aparecer antes que €
    if "€" in r:
        assert low.find("l-v") != -1 or "09:" in low or "lunes" in low
        # orden: algo de horario antes que €
        idx_h = min([i for i in [low.find("l-v"), low.find("lunes"), low.find("09:")] if i != -1])
        idx_e = r.find("€")
        assert idx_h < idx_e


def test_faq_repeat_dedupes_second_answer():
    sender = "scenario-faq-repeat"
    reset_state(sender)

    r1, _ = respond("Horario", sender=sender)
    r2, _ = respond("Horario", sender=sender)

    assert len(r2) < len(r1)  # segunda más corta
    assert "acabo de indicar" in (r2 or "").lower()


def test_faq_long_answer_is_trimmed():
    sender = "scenario-faq-trim"
    reset_state(sender)

    msg = "Dame horarios, dirección, contacto, seguros, formas de pago, financiación, precios y aparcamiento"
    r, _ = respond(msg, sender=sender)

    assert len(r) <= 950  # margen por saltos, etc.
    assert "…" in r  # indicador de recorte


def test_pain_strong_skips_urgency_question():
    sender = "scenario-auto-urgent-skip"
    reset_state(sender)

    respond("Quiero cita", sender=sender)
    respond("Lander Iglesias", sender=sender)
    respond("612345678", sender=sender)

    r, _ = respond("Tengo dolor muy fuerte en una muela", sender=sender)
    st = get_state(sender)

    assert st.urgencia == "alta"
    assert st.step == "when"
    assert "preferencia" in (r or "").lower() or "mañanas" in (r or "").lower()


def test_euskera_greeting_routes_to_smalltalk():
    sender = "scenario-eu-greet"
    reset_state(sender)

    r, _ = respond("Kaixo!", sender=sender)
    low = (r or "").lower()
    assert "¿en qué puedo ayudarte" in low


def test_euskera_thanks_routes_to_smalltalk():
    sender = "scenario-eu-thanks"
    reset_state(sender)

    r, _ = respond("Eskerrik asko", sender=sender)
    low = (r or "").lower()
    assert "de nada" in low or "eskerrik" in low or "a ti" in low
