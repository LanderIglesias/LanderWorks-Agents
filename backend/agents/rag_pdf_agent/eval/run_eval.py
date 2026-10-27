"""
Evaluación del RAG PDF Agent: mismo PDF y mismas preguntas contra Haiku (API) y modelos locales (Ollama).

Uso (desde la raíz del repo, con Ollama arrancado):
    python -m backend.agents.rag_pdf_agent.eval.run_eval
    python -m backend.agents.rag_pdf_agent.eval.run_eval --repeats 3

Registra por pregunta: respuesta, tiempo, VRAM en uso, tokens y motivo de parada del LLM,
y corrección automática provisional. Por pregunta (una vez, no depende del LLM): calidad de la búsqueda.
Los resultados se guardan en eval/results/ (JSON completo + CSV para la revisión manual).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import time
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
PDF_PATH = EVAL_DIR / "data" / "memoria_fq_2025.pdf"
RESULTS_DIR = EVAL_DIR / "results"
OLLAMA_URL = "http://localhost:11434"

# Temperatura 0 en todas para que sean comparables, salvo thinking: Qwen3 pide 0.6 en ese modo
# ("DO NOT use greedy decoding", model card de Qwen3-14B en Hugging Face).
GREEDY = {"RAG_LLM_TEMPERATURE": "0"}

# (nombre, variables de entorno que leen rag_engine._get_llm, máximo de pasadas o None)
CONFIGS = [
    ("claude-haiku-4.5 (API)", {"RAG_LLM_PROVIDER": "anthropic", **GREEDY}, None),
    (
        "qwen3:14b (local)",
        {"RAG_LLM_PROVIDER": "ollama", "RAG_OLLAMA_MODEL": "qwen3:14b", **GREEDY},
        None,
    ),
    (
        "qwen3:14b + thinking (local)",
        {
            "RAG_LLM_PROVIDER": "ollama",
            "RAG_OLLAMA_MODEL": "qwen3:14b",
            "RAG_OLLAMA_REASONING": "1",
            "RAG_LLM_TEMPERATURE": "0.6",
        },
        None,
    ),
    # Referencia de baja capacidad: 1 pasada y se presenta aparte de la comparación principal.
    (
        "llama3.2:3b (local)",
        {"RAG_LLM_PROVIDER": "ollama", "RAG_OLLAMA_MODEL": "llama3.2:3b", **GREEDY},
        1,
    ),
]
# Se borran antes de cada configuración: os.environ.update no quita las de la anterior.
CONFIG_KEYS = {k for _, env, _ in CONFIGS for k in env}

# Frases con las que el modelo admite que el documento no tiene la respuesta.
REFUSAL_MARKERS = [
    "no encontre",
    "no se menciona",
    "no aparece",
    "no contiene",
    "no se indica",
    "no se especifica",
    "no incluye",
    "no proporciona",
]

# ── Corrección automática (provisional) ───────────────────────────────────────


def _normalize(text: str) -> str:
    """Minúsculas y sin tildes: 'Málaga' -> 'malaga'."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _numbers_in(text: str) -> set[str]:
    """Cifras sin separadores: '237.294,59 €' -> {'23729459'}."""
    joined = re.sub(r"(?<=\d)[.,  ](?=\d)", "", text)
    return set(re.findall(r"\d+", joined))


def grade(question: dict, answer: str) -> str:
    """Devuelve 'correcta', 'parcial' o 'incorrecta' según questions.json."""
    norm = _normalize(answer)
    refused = any(m in norm for m in REFUSAL_MARKERS)
    if question.get("expect_refusal"):
        return "correcta" if refused else "incorrecta"

    numbers = _numbers_in(answer)
    checks = [n in numbers for n in question["numbers"]]
    checks += [any(alt in norm for alt in group) for group in question["terms"]]
    if all(checks):
        return "correcta"
    return "parcial" if any(checks) else "incorrecta"


def retrieval_metrics(question: dict, chunks: list[dict]) -> dict | None:
    """Calidad de la búsqueda para una pregunta. None si la respuesta no está en el documento."""
    if question["page"] is None:
        return None
    expected = question["page"] if isinstance(question["page"], list) else [question["page"]]
    retrieved = {c["page"] for c in chunks}
    metrics = {
        "pages_found": sum(p in retrieved for p in expected),
        "pages_expected": len(expected),
    }
    # Más fino que la página: una página partida en varios chunks puede recuperarse sin el
    # fragmento con la cifra. En 'calculo' el resultado no está en el texto, solo los sumandos.
    # ponytail: una cifra corta (6, 23) puede aparecer por azar; techo: buscarla con su contexto.
    if question["numbers"] and question["type"] != "calculo":
        # "\n" y no " ": _numbers_in une dígitos separados por espacio entre dos chunks.
        in_context = _numbers_in("\n".join(c["text"] for c in chunks))
        metrics["numbers_found"] = sum(n in in_context for n in question["numbers"])
        metrics["numbers_expected"] = len(question["numbers"])
    return metrics


# ── Medición ──────────────────────────────────────────────────────────────────


def llm_stats(runs_cb) -> dict:
    """Tokens y motivo de parada de la llamada al LLM, para detectar respuestas cortadas."""
    stack = list(runs_cb.traced_runs)
    while stack:
        run = stack.pop()
        if run.run_type in ("llm", "chat_model"):
            msg = run.outputs["generations"][0][0]["message"]["kwargs"]
            meta = msg.get("response_metadata", {})
            usage = msg.get("usage_metadata") or {}
            return {
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                # Ollama: done_reason ('length' = cortada). Anthropic: stop_reason ('max_tokens').
                "stop_reason": meta.get("done_reason") or meta.get("stop_reason"),
            }
        stack.extend(run.child_runs)
    return {}


def vram_used_mib() -> int:
    """VRAM total en uso en la GPU. En Windows (WDDM) nvidia-smi no da el dato por proceso."""
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.strip().splitlines()[0])


def ollama_unload(model: str) -> None:
    """Saca el modelo de la VRAM (keep_alive=0) para medir un arranque en frío real."""
    body = json.dumps({"model": model, "keep_alive": 0}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=60).read()
    time.sleep(2)  # dar tiempo a que el driver libere la memoria antes de medir la base


def ensure_pdf(meta: dict) -> Path:
    """Descarga el PDF si falta y comprueba que es exactamente el validado (sha256)."""
    if not PDF_PATH.exists():
        PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(meta["url"], PDF_PATH)
    digest = hashlib.sha256(PDF_PATH.read_bytes()).hexdigest()
    if digest != meta["sha256"]:
        raise RuntimeError(
            f"El PDF no coincide con el validado (sha256 {digest}). Bórralo y repite."
        )
    return PDF_PATH


# ── Ejecución ─────────────────────────────────────────────────────────────────


def run(repeats: int) -> Path:
    # Import tardío: rag_engine carga .env y LangChain, y así --help responde al instante.
    from langchain_core.tracers.context import collect_runs

    from backend.agents.rag_pdf_agent import rag_engine

    spec = json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))
    pdf = ensure_pdf(spec["pdf"])

    # Un único índice (embeddings locales, bge-m3) compartido: el retrieval es idéntico
    # para ambos modelos, así que las diferencias vienen solo del LLM.
    os.environ["RAG_EMBEDDINGS_PROVIDER"] = "ollama"
    session_id = rag_engine.create_session_id()

    records, runs = [], []
    try:
        rag_engine.process_pdf(str(pdf), session_id)

        # Texto completo de los fragmentos recuperados por pregunta. El retrieval no depende
        # del LLM, así que basta una vez; sirve para distinguir fallo de búsqueda vs. de modelo.
        retriever = rag_engine._load_vectorstore(session_id).as_retriever(
            search_kwargs={"k": rag_engine.TOP_K_CHUNKS}
        )
        chunks = {
            q["id"]: [
                {"page": d.metadata.get("page", 0) + 1, "text": d.page_content}
                for d in retriever.invoke(q["question"])
            ]
            for q in spec["questions"]
        }
        retrieval = {q["id"]: retrieval_metrics(q, chunks[q["id"]]) for q in spec["questions"]}

        local_models = sorted(
            {e["RAG_OLLAMA_MODEL"] for _, e, _ in CONFIGS if "RAG_OLLAMA_MODEL" in e}
        )
        for name, env, max_repeats in CONFIGS:
            for k in CONFIG_KEYS:
                os.environ.pop(k, None)
            os.environ.update(env)
            n_repeats = repeats if max_repeats is None else min(repeats, max_repeats)
            # Ningún LLM local cargado al medir la base (también antes de la config por API).
            for m in local_models:
                ollama_unload(m)
            # La base incluye el modelo de embeddings cargado: así el delta es solo el LLM.
            rag_engine._get_embeddings().embed_query("calentamiento")
            baseline = vram_used_mib()

            # Llamada de calentamiento: en local mide la carga del modelo en VRAM (arranque en frío).
            t0 = time.perf_counter()
            rag_engine.get_answer("¿De qué trata el documento?", session_id)
            cold_s = time.perf_counter() - t0
            runs.append(
                {
                    "config": name,
                    "env": env,
                    "repeats": n_repeats,
                    "vram_baseline_mib": baseline,
                    "cold_start_s": round(cold_s, 2),
                }
            )
            print(f"\n== {name} | VRAM base {baseline} MiB | arranque en frío {cold_s:.1f}s")

            for rep in range(1, n_repeats + 1):
                for q in spec["questions"]:
                    t0 = time.perf_counter()
                    with collect_runs() as runs_cb:
                        result = rag_engine.get_answer(q["question"], session_id)
                    elapsed = time.perf_counter() - t0
                    stats = llm_stats(runs_cb)
                    vram = vram_used_mib()
                    status = grade(q, result["answer"])
                    records.append(
                        {
                            "config": name,
                            "repeat": rep,
                            "id": q["id"],
                            "type": q["type"],
                            "question": q["question"],
                            "expected": q["expected"],
                            "answer": result["answer"],
                            "pages_retrieved": [s["page"] for s in result["sources"]],
                            "expected_page": q["page"],
                            "seconds": round(elapsed, 2),
                            "vram_used_mib": vram,
                            "vram_delta_mib": vram - baseline,
                            **stats,
                            "auto_grade": status,
                        }
                    )
                    print(
                        f"  r{rep} Q{q['id']:>2} {elapsed:6.1f}s  {status:<10} {vram - baseline:>6} MiB"
                        f"  tok {stats.get('input_tokens')}+{stats.get('output_tokens')}"
                        f" {stats.get('stop_reason')}"
                    )
        return save(records, runs, repeats, chunks, retrieval)
    finally:
        try:
            rag_engine.cleanup_session(session_id)
        except PermissionError:
            # Windows: Chroma mantiene abiertos sus archivos mientras vive el proceso.
            print(f"\nAVISO: borra a mano el índice temporal data/chroma/{session_id}")


def save(
    records: list[dict], runs: list[dict], repeats: int, chunks: dict, retrieval: dict
) -> Path:
    import importlib.metadata as md

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    gpu = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    meta = {
        "timestamp": stamp,
        "repeats": repeats,
        "gpu": gpu,
        "packages": {
            p: md.version(p) for p in ["langchain-core", "langchain-anthropic", "langchain-ollama"]
        },
        "runs": runs,
    }
    json_path = RESULTS_DIR / f"results_{stamp}.json"
    json_path.write_text(
        json.dumps(
            {"meta": meta, "records": records, "retrieval": retrieval, "retrieved_chunks": chunks},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # CSV para revisar a mano: la columna manual_grade se rellena tras leer cada respuesta.
    csv_path = RESULTS_DIR / f"review_{stamp}.csv"
    fields = [
        "config",
        "repeat",
        "id",
        "question",
        "expected",
        "answer",
        "auto_grade",
        "manual_grade",
    ]
    with csv_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as f:  # utf-8-sig: Excel lee las tildes
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        writer.writerows({**r, "manual_grade": ""} for r in records)

    print(f"\nResultados: {json_path}\nRevisión manual: {csv_path}")
    return json_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--repeats", type=int, default=1, help="veces que se lanza cada pregunta")
    run(parser.parse_args().repeats)
