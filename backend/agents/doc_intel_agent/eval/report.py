"""
Métricas de una ejecución de la evaluación de Document Intelligence.

Uso (desde la raíz del repo):
    python -m backend.agents.doc_intel_agent.eval.report eval/results/results_<fecha>.json

Imprime el resumen en JSON y escribe results/review_<fecha>.csv para la revisión manual.
Si existe results/grades_<fecha>.json ([{id, run, doc, grade}]), esas notas sustituyen
a la corrección automática.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .grading import auto_grade, citation_status, cited_pages, facts_hit_by_chunks, normalise

EVAL_DIR = Path(__file__).resolve().parent
GRADES = ("correcta", "parcial", "incorrecta")
STATUSES = ("exact", "adjacent", "wrong", "n/a")


def _labelled_right(item: dict, chunks: list[dict]) -> list[bool]:
    """Por hecho: algún chunk con su evidencia lleva una de sus páginas (si no, falla el etiquetado)."""
    return [
        any(
            c["page"] in f["pages"]
            for c in chunks
            if normalise(f["evidence"]) in normalise(c["content"])
        )
        for f in item["facts"]
    ]


def rows(questions: dict, results: dict, human: list[dict] | None = None) -> list[dict]:
    """Una fila por elemento corregido (pregunta × pasada × documento)."""
    file_to_key = {d["file"]: d["key"] for d in questions["documents"]}
    by_id = {q["id"]: q for q in questions["questions"]}
    overrides = {(h["id"], h["run"], h["doc"]): h["grade"] for h in human or []}

    out = []
    for rec in results["records"]:
        q = by_id[rec["id"]]
        for item in q["items"]:
            if q["route"] == "compare":
                found = [a for a in rec["answers"] if a["doc"] == item["doc"]]
                answer = found[0] if found else {"answer": "", "chunks_text": []}
                default_doc = item["doc"]
            else:
                answer, default_doc = rec["answers"][0], None
            cited = cited_pages(answer["answer"], default_doc, file_to_key)
            auto = auto_grade(item, answer["answer"])
            out.append(
                {
                    "id": q["id"],
                    "type": q["type"],
                    "run": rec["run"],
                    "doc": item["doc"],
                    "expected": item["expected"],
                    "answer": answer["answer"],
                    "auto_grade": auto,
                    "grade": overrides.get((q["id"], rec["run"], item["doc"]), auto),
                    "citation_status": citation_status(item, cited),
                    "cited_pages": {k: sorted(v) for k, v in cited.items()},
                    "facts_retrieved": facts_hit_by_chunks(item, answer["chunks_text"]),
                    "facts_labelled_right": _labelled_right(item, answer["chunks_text"]),
                }
            )
    return out


def summarise(questions: dict, results: dict, human: list[dict] | None = None) -> dict:
    table = rows(questions, results, human)

    def grades(subset):
        c = Counter(r["grade"] for r in subset)
        return {g: c[g] for g in GRADES}

    status = Counter(r["citation_status"] for r in table)
    split = Counter()
    for r in table:
        if r["citation_status"] in ("exact", "n/a"):
            continue
        if not all(r["facts_retrieved"]):
            split["not_retrieved"] += 1
        elif not all(r["facts_labelled_right"]):
            split["retrieved_mislabelled"] += 1
        else:
            split["retrieved_cited_wrong"] += 1

    per_question = defaultdict(list)
    for r in table:
        if r["type"] == "comparison":
            per_question[(r["run"], r["id"])].append(r["grade"])
    all_three = Counter()
    for (run, _), gs in per_question.items():
        all_three[str(run)] += 0
        if len(gs) == 3 and all(g == "correcta" for g in gs):
            all_three[str(run)] += 1

    seen = defaultdict(set)
    for r in table:
        seen[(r["id"], r["doc"])].add((r["grade"], r["citation_status"]))

    return {
        "items_total": len(table),
        "grades": grades(table),
        "by_type": {
            t: grades([r for r in table if r["type"] == t])
            for t in ("extraction", "comparison", "trap")
        },
        "citation": {s: status[s] for s in STATUSES},
        "failure_split": {
            k: split[k] for k in ("not_retrieved", "retrieved_mislabelled", "retrieved_cited_wrong")
        },
        "compare_all_three_right": dict(sorted(all_three.items())),
        "unstable_items": [[i, d] for (i, d), v in seen.items() if len(v) > 1],
    }


def main(path: str) -> None:
    results_path = Path(path)
    stamp = results_path.stem.removeprefix("results_")
    questions = json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))
    results = json.loads(results_path.read_text(encoding="utf-8"))
    grades_path = results_path.with_name(f"grades_{stamp}.json")
    human = json.loads(grades_path.read_text(encoding="utf-8")) if grades_path.exists() else None

    review = results_path.with_name(f"review_{stamp}.csv")
    fields = [
        "id",
        "run",
        "doc",
        "expected",
        "answer",
        "auto_grade",
        "citation_status",
        "cited_pages",
        "facts_retrieved",
        "human_grade",
    ]
    with review.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows(questions, results, human):
            writer.writerow(
                {
                    **r,
                    "cited_pages": json.dumps(r["cited_pages"]),
                    "facts_retrieved": json.dumps(r["facts_retrieved"]),
                    "human_grade": r["grade"] if human else "",
                }
            )

    print(json.dumps(summarise(questions, results, human), ensure_ascii=False, indent=2))
    print(review, file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
