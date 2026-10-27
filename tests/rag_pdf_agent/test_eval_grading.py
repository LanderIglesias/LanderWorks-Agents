"""Tests de la corrección automática del script de evaluación (sin llamadas a modelos)."""

from __future__ import annotations

from backend.agents.rag_pdf_agent.eval.run_eval import grade, retrieval_metrics

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


def test_retrieval_pagina_correcta_sin_la_cifra():
    # Caso Q8: se recupera la página 11, pero no el chunk que tiene la cifra.
    q = {"page": 11, "type": "cifra_con_trampa", "numbers": ["3604841"], "terms": []}
    chunks = [{"page": 11, "text": "Ingresos: 237.294,59 €"}, {"page": 3, "text": "Otro"}]
    assert retrieval_metrics(q, chunks) == {
        "pages_found": 1,
        "pages_expected": 1,
        "numbers_found": 0,
        "numbers_expected": 1,
    }


def test_retrieval_varias_paginas_y_casos_sin_aplicar():
    chunks = [{"page": 5, "text": "36.048,41 €"}, {"page": 7, "text": "12"}]
    q_multi = {"page": [5, 20], "type": "multi_salto", "numbers": [], "terms": []}
    assert retrieval_metrics(q_multi, chunks) == {"pages_found": 1, "pages_expected": 2}
    # Los dígitos de dos chunks distintos no se juntan en una cifra falsa ("4112")
    q_cifra = {"page": 5, "type": "dato_exacto", "numbers": ["4112"], "terms": []}
    assert retrieval_metrics(q_cifra, chunks)["numbers_found"] == 0
    # En 'calculo' el total no está en el texto: no se mide
    q_suma = {"page": 5, "type": "calculo", "numbers": ["999"], "terms": []}
    assert "numbers_found" not in retrieval_metrics(q_suma, chunks)
    assert retrieval_metrics({"page": None}, chunks) is None
