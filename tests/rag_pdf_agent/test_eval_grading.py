"""Tests de la corrección automática del script de evaluación (sin llamadas a modelos)."""

from __future__ import annotations

from backend.agents.rag_pdf_agent.eval.run_eval import grade

Q_INGRESOS = {"numbers": ["23729459", "6062"], "terms": []}
Q_CONGRESO = {"numbers": ["15", "16"], "terms": [["noviembre"], ["malaga"]]}
Q_NO_DOC = {"expect_refusal": True, "numbers": [], "terms": []}


def test_cifras_con_formatos_distintos_son_correctas():
    assert grade(Q_INGRESOS, "Fueron 237.294,59 € y el 60,62% donaciones.") == "correcta"
    assert grade(Q_INGRESOS, "Ingresos: 237,294.59 EUR; donaciones 60.62 %") == "correcta"


def test_cifra_prevista_en_vez_de_real_es_incorrecta():
    assert grade(Q_INGRESOS, "Se previeron 240.650,44 € con un 63,14%.") == "incorrecta"


def test_solo_una_parte_es_parcial():
    assert grade(Q_INGRESOS, "Los ingresos fueron 237.294,59 €.") == "parcial"


def test_terminos_sin_tildes_ni_mayusculas():
    assert grade(Q_CONGRESO, "Se celebró el 15 y 16 de Noviembre en MÁLAGA.") == "correcta"


def test_negarse_solo_es_correcto_si_se_espera():
    refusal = "No encontré esa información en el documento."
    assert grade(Q_NO_DOC, refusal) == "correcta"
    assert grade(Q_NO_DOC, "Hay unas 2.500 personas con FQ en España.") == "incorrecta"
    assert grade(Q_INGRESOS, refusal) == "incorrecta"
