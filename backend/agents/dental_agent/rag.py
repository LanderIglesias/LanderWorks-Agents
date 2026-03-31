from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import chromadb
from chromadb.api.types import IncludeEnum

CHROMA_DIR = Path(__file__).resolve().parent / "data" / "chroma"
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
_col = _client.get_or_create_collection(name="dental")


def _split_md(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    """
    Chunking orientado a RAG:
    - conserva encabezados (#, ##, ###) dentro del chunk
    - agrupa por secciones
    - corta con solape para evitar partir respuestas a mitad
    """
    # Captura encabezados y contenido: [(header, body), ...]
    pattern = re.compile(r"(?ms)^(#{1,3}\s+[^\n]+)\n(.*?)(?=^#{1,3}\s+|\Z)")
    sections = pattern.findall(text)

    # Si no hay encabezados, fallback simple
    if not sections:
        sections = [("DOCUMENTO", text)]

    chunks: list[str] = []

    for header, body in sections:
        header = header.strip()
        body = body.strip()
        if not body:
            continue

        full = f"{header}\n{body}".strip()

        # Si cabe, entra tal cual
        if len(full) <= chunk_size:
            chunks.append(full)
            continue

        # Si no cabe, trocea con solape (manteniendo el header al inicio)
        start = 0
        while start < len(body):
            end = min(len(body), start + (chunk_size - len(header) - 1))
            piece = body[start:end].strip()
            if piece:
                chunks.append(f"{header}\n{piece}".strip())
            if end >= len(body):
                break
            start = max(0, end - overlap)

    # Limpieza final
    chunks = [c for c in chunks if len(c) > 30]
    return chunks


def ingest_markdown(md_path: str = "backend/data/dental_faq.md") -> int:
    md = Path(md_path).read_text(encoding="utf-8")
    chunks = _split_md(md)

    global _col, _client
    _client.delete_collection("dental")
    _col = _client.get_or_create_collection(name="dental")

    ids = [f"doc-{i}" for i in range(len(chunks))]
    metas: list[dict[str, str | int | float | bool]] = [
        {"source": md_path, "idx": i} for i in range(len(chunks))
    ]
    _col.add(
        ids=ids,
        documents=chunks,
        metadatas=cast(list[Mapping[str, str | int | float | bool]], metas),
    )
    return len(chunks)


def search(q: str, k: int = 4):
    res = _col.query(
        query_texts=[q],
        n_results=k,
        include=[IncludeEnum.documents, IncludeEnum.metadatas, IncludeEnum.distances],
    )
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    items = []
    best = None
    for d, m, dist in zip(docs, metas, dists, strict=False):
        items.append({"source": m.get("source", "unknown"), "snippet": d, "distance": float(dist)})
        best = float(dist) if best is None else min(best, float(dist))
    return items, best
