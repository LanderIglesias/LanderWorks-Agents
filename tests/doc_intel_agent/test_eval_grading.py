"""Tests de los helpers de corrección de la evaluación de Document Intelligence (sin red)."""

from backend.agents.doc_intel_agent.eval.grading import (
    auto_grade,
    citation_status,
    cited_pages,
    facts_hit_by_chunks,
    normalise,
)

FILES = {"hubspot_tos.pdf": "HS", "salesforce_msa.pdf": "SF", "freshworks_tos.pdf": "FW"}

TRAP = {"doc": None, "expect_refusal": True, "facts": [], "forbidden": ["99.95"]}

E3_LIKE = {
    "doc": "FW",
    "expect_refusal": False,
    "forbidden": [],
    "facts": [
        {"text": "14 days", "pages": [12], "evidence": "x", "terms": [["14", "fourteen"]]},
        {
            "text": "3 months",
            "pages": [13],
            "evidence": "y",
            "terms": [["3 months", "three months"]],
        },
    ],
}


def test_normalise_ligatures_and_quotes():
    assert normalise("Speciﬁed Customerʼs  Data") == "specified customer's data"


def test_cited_pages_engine_format():
    answer = "Fees rise with notice [Document: hubspot_tos.pdf | Page: 9]."
    assert cited_pages(answer, None, FILES) == {"HS": {9}}


def test_cited_pages_default_doc_for_compare():
    assert cited_pages("The notice is 30 days (Page 8).", "SF", FILES) == {"SF": {8}}


def test_cited_pages_ranges_and_lists():
    assert cited_pages("See pages 12-13.", "FW", FILES) == {"FW": {12, 13}}
    assert cited_pages("See pages 14 and 21.", "FW", FILES) == {"FW": {14, 21}}
    assert cited_pages("See p. 5.", "FW", FILES) == {"FW": {5}}
    assert cited_pages("See pages 14, 21.", "FW", FILES) == {"FW": {14, 21}}


def test_cited_pages_attributes_to_named_doc():
    answer = "HubSpot (page 46) commits to uptime. Salesforce does not say."
    assert cited_pages(answer, None, FILES) == {"HS": {46}}


def test_cited_pages_without_doc_goes_to_unknown():
    assert cited_pages("It is on page 3.", None, FILES) == {"?": {3}}


def test_citation_status_exact_adjacent_wrong_na():
    item = {
        "doc": "FW",
        "facts": [
            {"pages": [12], "evidence": "a", "terms": []},
            {"pages": [13], "evidence": "b", "terms": []},
        ],
    }
    assert citation_status(item, {"FW": {12, 13}}) == "exact"
    assert citation_status(item, {"FW": {12}}) == "adjacent"
    assert citation_status(item, {"FW": {20}}) == "wrong"
    assert citation_status(item, {"HS": {12, 13}}) == "wrong"
    assert citation_status(TRAP, {"HS": {46}}) == "n/a"


def test_auto_grade_trap_refusal_vs_forbidden():
    assert (
        auto_grade(TRAP, "I couldn't find information about that in this document.") == "correcta"
    )
    assert (
        auto_grade(TRAP, "Salesforce doesn't state it; HubSpot commits to 99.95%.") == "incorrecta"
    )
    assert auto_grade(TRAP, "Salesforce guarantees 99.9% uptime.") == "incorrecta"


def test_auto_grade_partial():
    assert auto_grade(E3_LIKE, "You have 14 days to export it.") == "parcial"
    assert auto_grade(E3_LIKE, "Fourteen days, then up to three months.") == "correcta"
    assert auto_grade(E3_LIKE, "Thirty days.") == "incorrecta"


def test_facts_hit_by_chunks():
    item = {
        "facts": [
            {"pages": [1], "evidence": "the specified Customer's data", "terms": []},
            {"pages": [2], "evidence": "never retrieved", "terms": []},
        ]
    }
    chunks = [{"filename": "x.pdf", "page": 1, "content": "and the  speciﬁed Customerʼs data here"}]
    assert facts_hit_by_chunks(item, chunks) == [True, False]
