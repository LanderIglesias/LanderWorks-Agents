"""
Evaluación del Document Intelligence Agent: 24 preguntas sobre tres contratos SaaS congelados.

Uso (desde la raíz del repo, con la base de datos de evaluación arrancada):
    docker run -d --name doc-intel-eval-db -e POSTGRES_USER=eval -e POSTGRES_PASSWORD=eval \
        -e POSTGRES_DB=doc_intel_eval -p 5433:5432 pgvector/pgvector:pg16
    set EVAL_DATABASE_URL=postgresql://eval:eval@localhost:5433/doc_intel_eval
    python -m backend.agents.doc_intel_agent.eval.run_eval
    python -m backend.agents.doc_intel_agent.eval.run_eval --repeats 1 --only E1,C1,T1
    python -m backend.agents.doc_intel_agent.eval.run_eval --skip-index

Indexa los PDF con process_pdf + save_chunks (sin R2) en una base pgvector local que se
vacía antes de indexar, y responde con las funciones reales del motor
(answer_question / compare_documents). Solo acepta EVAL_DATABASE_URL en localhost:
DATABASE_URL del .env apunta a producción y nunca se usa.
Resultados en eval/results/results_<fecha>.json; métricas con report.py.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parents[3]
RESULTS_DIR = EVAL_DIR / "results"
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
PACKAGES = ["openai", "anthropic", "pypdf", "sqlalchemy", "pgvector"]


def check_eval_db_url(url: str) -> str:
    """Devuelve la URL si apunta a localhost; si no, aborta (protege la base de producción)."""
    if not url:
        raise SystemExit("EVAL_DATABASE_URL no está definida (debe apuntar a la base local).")
    host = urlsplit(url).hostname
    if host not in LOCAL_HOSTS:
        raise SystemExit(f"EVAL_DATABASE_URL debe apuntar a localhost, no a '{host}'.")
    parts = urlsplit(url)
    # libpq acepta ?host=... en la query: se saltaría la comprobación del host.
    if parts.query:
        raise SystemExit("EVAL_DATABASE_URL no puede llevar parámetros (?...).")
    # Una copia local de la base de la app o un túnel a producción en localhost no vale:
    # la tabla se vacía antes de indexar.
    if "eval" not in parts.path.lstrip("/"):
        raise SystemExit(
            "La base de EVAL_DATABASE_URL debe llamarse con 'eval' (p. ej. doc_intel_eval)."
        )
    return url


def results_name(n_records: int, n_expected: int, stamp: str) -> str:
    """Una ejecución incompleta (p. ej. error de la API a medias) lleva 'partial' en el nombre."""
    prefix = "results" if n_records == n_expected else "results_partial"
    return f"{prefix}_{stamp}.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--repeats", type=int, default=3, help="pasadas por pregunta")
    parser.add_argument("--only", default="", help="ids separados por comas (p. ej. E1,C1)")
    parser.add_argument("--skip-index", action="store_true", help="no reindexar los PDF")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    # Antes de importar database: crea su engine al importarse con DATABASE_URL.
    os.environ["DATABASE_URL"] = check_eval_db_url(os.environ.get("EVAL_DATABASE_URL", ""))

    from sqlalchemy import text

    from backend.agents.doc_intel_agent import database, engine
    from backend.agents.doc_intel_agent.document_processor import (
        CHUNK_SIZE_WORDS,
        EMBEDDING_MODEL,
        OVERLAP_WORDS,
        process_pdf,
    )

    spec = json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))
    file_to_key = {d["file"]: d["key"] for d in spec["documents"]}
    for doc in spec["documents"]:
        if _sha256(EVAL_DIR / "data" / doc["file"]) != doc["sha256"]:
            raise SystemExit(f"{doc['file']}: el sha256 no coincide con questions.json")

    only = {i.strip() for i in args.only.split(",") if i.strip()}
    questions = [q for q in spec["questions"] if not only or q["id"] in only]

    db = database.SessionLocal()
    try:
        if not args.skip_index:
            database.init_db()
            db.execute(text("TRUNCATE document_chunks RESTART IDENTITY"))
            db.commit()
            for doc in spec["documents"]:
                chunks = process_pdf((EVAL_DIR / "data" / doc["file"]).read_bytes())
                database.save_chunks(db, doc["file"], chunks, r2_key=None)
        counts = {d["filename"]: d["chunk_count"] for d in database.get_all_documents(db)}
        for doc in spec["documents"]:
            print(f"{doc['file']}: {counts.get(doc['file'], 0)} chunks")

        meta = {
            "date": datetime.now().isoformat(timespec="seconds"),
            "repeats": args.repeats,
            "llm_model": engine.MODEL,
            "embedding_model": EMBEDDING_MODEL,
            "top_k_ask": 5,
            "top_k_compare": 3,
            "chunk_size_words": CHUNK_SIZE_WORDS,
            "overlap_words": OVERLAP_WORDS,
            "packages": {p: importlib.metadata.version(p) for p in PACKAGES},
            "documents": [
                {
                    "key": d["key"],
                    "file": d["file"],
                    "sha256": d["sha256"],
                    "chunks": counts.get(d["file"], 0),
                }
                for d in spec["documents"]
            ],
        }

        records = []
        try:
            for run in range(1, args.repeats + 1):
                for q in questions:
                    t0 = time.perf_counter()
                    if q["route"] == "compare":
                        results = engine.compare_documents(db, q["question"])
                        answers = [
                            {"doc": file_to_key.get(r["filename"]), **_keep(r)} for r in results
                        ]
                    else:
                        answers = [
                            {"doc": None, **_keep(engine.answer_question(db, q["question"]))}
                        ]
                    seconds = round(time.perf_counter() - t0, 2)
                    records.append(
                        {
                            "id": q["id"],
                            "run": run,
                            "route": q["route"],
                            "seconds": seconds,
                            "answers": answers,
                        }
                    )
                    print(f"[{run}] {q['id']} {seconds}s")
        finally:
            # Guardamos aunque falle a medias: no perder respuestas ya pagadas.
            RESULTS_DIR.mkdir(exist_ok=True)
            expected = args.repeats * len(questions)
            meta["complete"] = len(records) == expected
            meta["records_expected"] = expected
            stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
            out = RESULTS_DIR / results_name(len(records), expected, stamp)
            out.write_text(
                json.dumps({"meta": meta, "records": records}, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            print(out)
    finally:
        db.close()


def _keep(result: dict) -> dict:
    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "chunks_text": result["chunks_text"],
    }


if __name__ == "__main__":
    main()
