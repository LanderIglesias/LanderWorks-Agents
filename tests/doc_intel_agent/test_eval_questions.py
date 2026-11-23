"""Comprobaciones del set de evaluación de Document Intelligence (sin red ni base de datos)."""

import hashlib
import json
from functools import cache
from pathlib import Path

from pypdf import PdfReader

from backend.agents.doc_intel_agent.eval.grading import normalise

EVAL_DIR = Path(__file__).resolve().parents[2] / "backend" / "agents" / "doc_intel_agent" / "eval"
QUESTIONS = json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))
DOCS = {d["key"]: d for d in QUESTIONS["documents"]}


@cache
def _page_text(key: str, page: int) -> str:
    reader = PdfReader(EVAL_DIR / "data" / DOCS[key]["file"])
    return normalise(reader.pages[page - 1].extract_text() or "")


def _items():
    for q in QUESTIONS["questions"]:
        for item in q["items"]:
            yield q, item


def test_pdf_hashes_match():
    for doc in QUESTIONS["documents"]:
        data = (EVAL_DIR / "data" / doc["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == doc["sha256"], doc["file"]
        assert len(PdfReader(EVAL_DIR / "data" / doc["file"]).pages) == doc["pages"]


def test_question_set_shape():
    ids = [q["id"] for q in QUESTIONS["questions"]]
    expected_ids = (
        [f"E{i}" for i in range(1, 11)]
        + [f"C{i}" for i in range(1, 9)]
        + [f"T{i}" for i in range(1, 7)]
    )
    assert ids == expected_ids
    for q in QUESTIONS["questions"]:
        if q["route"] == "compare":
            assert [i["doc"] for i in q["items"]] == ["HS", "SF", "FW"], q["id"]
        else:
            assert q["route"] == "ask"
            assert len(q["items"]) == 1, q["id"]
        for item in q["items"]:
            for fact in item["facts"]:
                assert fact["pages"] and fact["terms"], (q["id"], fact["text"])
                for alternatives in fact["terms"]:
                    assert alternatives == [normalise(a) for a in alternatives], q["id"]


def test_every_evidence_is_on_its_page():
    for q, item in _items():
        for fact in item["facts"]:
            evidence = normalise(fact["evidence"])
            assert len(fact["evidence"].split()) <= 15, (q["id"], fact["evidence"])
            assert any(evidence in _page_text(item["doc"], p) for p in fact["pages"]), (
                q["id"],
                item["doc"],
                fact["pages"],
                fact["evidence"],
            )


def test_traps_have_forbidden_and_no_evidence():
    traps = {q["id"]: q["items"][0] for q in QUESTIONS["questions"] if q["type"] == "trap"}
    for tid in ["T1", "T2", "T3", "T4", "T5"]:
        item = traps[tid]
        assert item["facts"] == [] and item["forbidden"], tid
        assert item["doc"] is None and item["expect_refusal"] is True, tid
    assert traps["T6"]["facts"] and traps["T6"]["doc"] == "HS"
    assert traps["T6"]["expect_refusal"] is False
