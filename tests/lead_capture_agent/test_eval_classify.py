from backend.agents.lead_capture_agent.eval.classify import (
    classify,
    count_deliveries,
    faithfulness_flags,
    first_email_request,
    first_send_turn,
    looks_english,
    marker_leaked,
)

P1 = {"expected": "send", "confirm_turn": 4, "email": "a@b.example"}
NO = {"expected": "no_send", "confirm_turn": None, "email": None}


def t(*steps, email="a@b.example"):
    return [{"step_after": s, "email_after": email} for s in steps]


def test_correcto():
    assert classify(P1, t("start", "start", "start", "send")) == "correct"


def test_prematuro():
    assert classify(P1, t("start", "start", "send", "send")) == "premature"


def test_falso_negativo():
    assert classify(P1, t(*["start"] * 4)) == "false_negative"


def test_email_equivocado_no_es_correcto():
    # Un lead con email incorrecto es inutilizable para el tenant.
    assert (
        classify(P1, t("start", "start", "start", "send", email="x@y.example")) == "false_negative"
    )


def test_falso_positivo():
    assert classify(NO, t("start", "send", "send", "send")) == "false_positive"


def test_no_send_correcto():
    assert classify(NO, t(*["start"] * 4)) == "correct"


def test_primer_turno_de_envio():
    assert first_send_turn(t("start", "start", "send", "send")) == 3
    assert first_send_turn(t(*["start"] * 4)) is None


def test_entregas_duplicadas():
    assert count_deliveries(t("start", "start", "send", "send")) == 2


def test_marca_completa():
    assert marker_leaked("ok <<<SEND_LEAD>>>")


def test_marca_parcial_al_final():
    assert marker_leaked("Thanks <<<SEND_")


def test_sin_marca():
    assert not marker_leaked("Use << carefully")
    assert not marker_leaked("Thanks!")


def test_ingles():
    assert looks_english("Hi! How can I help you with your project today?")


def test_espanol():
    assert not looks_english("¡Hola! ¿En qué puedo ayudarte hoy con tu proyecto?")


def test_primera_peticion_de_email():
    assert first_email_request([{"visible": "Hi"}, {"visible": "What's your e-mail?"}]) == 2
    assert first_email_request([{"visible": "Hi"}]) is None


def test_flags():
    knowledge = "más de 40 clientes, sede en Madrid"
    assert "40" not in faithfulness_flags("We have 40 clients", knowledge)
    assert "12" in faithfulness_flags("We are 12 people", knowledge)
    assert "Acme" in faithfulness_flags("We worked with Acme.", knowledge)
    assert "Madrid" not in faithfulness_flags("We are in Madrid.", knowledge)
