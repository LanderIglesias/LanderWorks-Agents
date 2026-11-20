"""Tests del resumen de métricas de la evaluación de Document Intelligence (sin red)."""

from backend.agents.doc_intel_agent.eval.report import summarise

DOCS = [
    {"key": "HS", "file": "hubspot_tos.pdf"},
    {"key": "SF", "file": "salesforce_msa.pdf"},
    {"key": "FW", "file": "freshworks_tos.pdf"},
]


def _fact(page, evidence):
    return {"text": "f", "pages": [page], "evidence": evidence, "terms": [["30", "thirty"]]}


def _item(doc, page, evidence):
    return {
        "doc": doc,
        "expected": "30 days",
        "expect_refusal": False,
        "forbidden": [],
        "facts": [_fact(page, evidence)],
    }


QUESTIONS = {
    "documents": DOCS,
    "questions": [
        {
            "id": "Q1",
            "type": "extraction",
            "route": "ask",
            "question": "?",
            "items": [_item("HS", 9, "notify you at least thirty")],
        },
        {
            "id": "Q2",
            "type": "comparison",
            "route": "compare",
            "question": "?",
            "items": [
                _item("HS", 11, "hs cure clause"),
                _item("SF", 8, "sf cure clause"),
                _item("FW", 12, "fw cure clause"),
            ],
        },
    ],
}


def _answer(doc, text, file, page, content):
    return {
        "doc": doc,
        "answer": text,
        "sources": [],
        "chunks_text": [{"filename": file, "page": page, "content": content}],
    }


def _compare_answers():
    return [
        _answer("HS", "30 days (Page 11).", "hubspot_tos.pdf", 11, "the hs cure clause"),
        _answer("SF", "30 days (Page 8).", "salesforce_msa.pdf", 8, "the sf cure clause"),
        _answer("FW", "30 days (Page 12).", "freshworks_tos.pdf", 12, "the fw cure clause"),
    ]


RESULTS = {
    "meta": {},
    "records": [
        {
            "id": "Q1",
            "run": 1,
            "route": "ask",
            "answers": [
                _answer(
                    None,
                    "HubSpot gives thirty days' notice (page 8).",
                    "hubspot_tos.pdf",
                    8,
                    "we will notify you at least thirty (30) days",
                )
            ],
        },
        {"id": "Q2", "run": 1, "route": "compare", "answers": _compare_answers()},
        {
            "id": "Q1",
            "run": 2,
            "route": "ask",
            "answers": [
                _answer(None, "HubSpot gives notice (page 9).", "hubspot_tos.pdf", 9, "nothing")
            ],
        },
        {"id": "Q2", "run": 2, "route": "compare", "answers": _compare_answers()},
    ],
}


def test_summary_counts():
    s = summarise(QUESTIONS, RESULTS)
    assert s["items_total"] == 8
    assert s["grades"] == {"correcta": 7, "parcial": 0, "incorrecta": 1}
    assert s["by_type"]["comparison"] == {"correcta": 6, "parcial": 0, "incorrecta": 0}
    assert s["citation"] == {"exact": 7, "adjacent": 1, "wrong": 0, "n/a": 0}
    assert s["failure_split"] == {
        "not_retrieved": 0,
        "retrieved_adjacent": 1,
        "retrieved_cited_wrong": 0,
    }
    assert s["compare_all_three_right"] == {"1": 1, "2": 1}
    assert s["unstable_items"] == [["Q1", "HS"]]


def test_human_grade_overrides_auto():
    human = [{"id": "Q1", "run": 2, "doc": "HS", "grade": "parcial"}]
    s = summarise(QUESTIONS, RESULTS, human)
    assert s["grades"] == {"correcta": 7, "parcial": 1, "incorrecta": 0}
