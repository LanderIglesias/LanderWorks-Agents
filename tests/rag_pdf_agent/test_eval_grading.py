"""Tests de la corrección automática del script de evaluación (sin llamadas a modelos)."""

from __future__ import annotations

from backend.agents.rag_pdf_agent.eval.blind import blind_export
from backend.agents.rag_pdf_agent.eval.grades_report import (
    join,
    mode,
    question_diff,
    summary,
)
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


def test_blind_export_agrupa_respuestas_iguales_y_oculta_la_configuracion():
    def rec(config, repeat, qid, answer):
        return {
            "config": config,
            "repeat": repeat,
            "id": qid,
            "type": "dato_exacto",
            "question": f"P{qid}",
            "expected": f"E{qid}",
            "answer": answer,
            "auto_grade": "correcta",
        }

    records = [
        rec("A", 1, 1, "x"),
        rec("A", 2, 1, "x"),
        rec("B", 1, 1, "x"),  # misma respuesta en otra configuración: una sola entrada
        rec("B", 2, 1, "y"),
        rec("A", 1, 2, "x"),  # mismo texto en otra pregunta: entrada distinta
    ]
    items, key = blind_export(records)

    assert len(items) == 3
    assert all("config" not in i and "auto_grade" not in i for i in items)
    # La clave devuelve cada una de las 5 apariciones exactamente una vez
    apariciones = sorted((o["config"], o["repeat"]) for occ in key.values() for o in occ)
    assert len(apariciones) == 5 and set(key) == {i["blind_id"] for i in items}
    x1 = next(i["blind_id"] for i in items if i["question_id"] == 1 and i["answer"] == "x")
    assert key[x1] == [
        {"config": "A", "repeat": 1},
        {"config": "A", "repeat": 2},
        {"config": "B", "repeat": 1},
    ]
    # Semilla fija: el mismo orden en cada ejecución
    assert blind_export(records) == (items, key)


def _report_fixture():
    # b1 (Q1, parcial) aparece en A, B y C; la regla puso más nota en A, menos en B, igual en C.
    # Q2: A y B dieron la misma respuesta (b2, correcta); C otra (b3, incorrecta).
    auto = {("A", 1): "correcta", ("B", 1): "incorrecta", ("C", 1): "parcial"}
    records = [{"config": c, "repeat": r, "id": 1, "auto_grade": g} for (c, r), g in auto.items()]
    records += [
        {"config": "A", "repeat": 1, "id": 2, "auto_grade": "correcta"},
        {"config": "B", "repeat": 1, "id": 2, "auto_grade": "correcta"},
        {"config": "C", "repeat": 1, "id": 2, "auto_grade": "incorrecta"},
    ]
    items = [{"blind_id": "b1", "question_id": 1}, {"blind_id": "b2", "question_id": 2}]
    items.append({"blind_id": "b3", "question_id": 2})
    key = {
        "b1": [{"config": c, "repeat": 1} for c in "ABC"],
        "b2": [{"config": c, "repeat": 1} for c in "AB"],
        "b3": [{"config": "C", "repeat": 1}],
    }
    grades = [
        {"blind_id": b, "grade": g, "extra_claims": b == "b2", "rounding_only": False}
        for b, g in [("b1", "parcial"), ("b2", "correcta"), ("b3", "incorrecta")]
    ]
    return records, items, key, grades


def test_grades_report_reparte_la_nota_y_detecta_subidas_y_bajadas():
    rows = join(*_report_fixture())
    # La nota de b1 llega a sus 3 apariciones, y cada aparición tiene una sola fila
    assert [(r["config"], r["grade"]) for r in rows if r["blind_id"] == "b1"] == [
        ("A", "parcial"),
        ("B", "parcial"),
        ("C", "parcial"),
    ]
    assert len(rows) == 6
    s = summary(rows)
    assert (s["A"]["lower"], s["A"]["higher"]) == (1, 0)
    assert (s["B"]["lower"], s["B"]["higher"]) == (0, 1)
    assert (s["C"]["lower"], s["C"]["higher"]) == (0, 0)
    assert s["A"]["n"] == 2 and s["A"]["extra_claims"] == 1 and s["C"]["incorrecta"] == 1
    assert question_diff(rows, "A", "B") == []
    assert question_diff(rows, "A", "C") == [(2, ["correcta"], ["incorrecta"])]


def test_question_diff_compara_la_moda_y_las_pasadas():
    def rows(config, qid, grades):
        return [
            {"config": config, "repeat": i, "qid": qid, "grade": g} for i, g in enumerate(grades)
        ]

    # L tiene 1 pasada y A y B tienen 3; en Q2 B difiere de A en una pasada, no en la moda
    r = []
    for qid, b_grades in [(1, ["correcta"] * 3), (2, ["correcta", "correcta", "parcial"])]:
        r += rows("A", qid, ["correcta"] * 3) + rows("B", qid, b_grades)
        r += rows("L", qid, ["correcta"])
    assert question_diff(r, "A", "L") == []  # misma moda; distinto número de pasadas
    assert question_diff(r, "A", "B") == [
        (2, ["correcta"] * 3, ["correcta", "correcta", "parcial"])
    ]
    assert mode(["correcta", "parcial", "incorrecta"]) == "mixed"
    assert mode(["correcta", "parcial", "parcial"]) == "parcial"


def test_grades_report_exclude_quita_la_pregunta_y_ajusta_n():
    s = summary(join(*_report_fixture(), exclude={1}))
    assert {c: v["n"] for c, v in s.items()} == {"A": 1, "B": 1, "C": 1}
    assert all(v["higher"] == v["lower"] == 0 for v in s.values())
    assert s["A"]["correcta"] == 1 and s["A"]["parcial"] == 0
