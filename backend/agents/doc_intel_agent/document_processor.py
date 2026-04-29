"""
document_processor.py — Extrae texto de PDFs y genera embeddings.

Flujo:
1. Recibe los bytes del PDF
2. Extrae el texto página por página con pypdf
3. Divide el texto en chunks de ~500 palabras con overlap
4. Genera un embedding por chunk con OpenAI
5. Devuelve los chunks listos para guardar en PostgreSQL

¿Qué es el overlap?
Cuando divides un texto en chunks, la información importante
puede estar justo en el corte entre dos chunks. El overlap
repite las últimas N palabras del chunk anterior al inicio
del siguiente — así el contexto no se pierde en los bordes.

Ejemplo sin overlap:
  Chunk 1: "El contrato fue firmado el 15 de enero..."
  Chunk 2: "...por ambas partes. El precio acordado es..."

Ejemplo con overlap de 50 palabras:
  Chunk 1: "El contrato fue firmado el 15 de enero..."
  Chunk 2: "...firmado el 15 de enero por ambas partes. El precio..."
"""

from __future__ import annotations

import io
import os

from dotenv import load_dotenv
from openai import OpenAI
from pypdf import PdfReader

load_dotenv()

# ── Configuración ────────────────────────────────────────────────────────────

# Tamaño de cada chunk en palabras
# 500 palabras ≈ 700 tokens ≈ cabe bien en contexto sin desperdiciar
CHUNK_SIZE_WORDS = 500

# Overlap en palabras entre chunks consecutivos
# 50 palabras ≈ 10% del chunk — suficiente para no perder contexto
OVERLAP_WORDS = 50

# Modelo de embeddings de OpenAI
# text-embedding-3-small: 1536 dimensiones, muy buena calidad, barato
# Coste: ~$0.02 por millón de tokens — prácticamente gratis
EMBEDDING_MODEL = "text-embedding-3-small"


# ── Extracción de texto ──────────────────────────────────────────────────────


def extract_text_from_pdf(pdf_bytes: bytes) -> list[dict]:
    """
    Extrae el texto de un PDF página por página.

    Args:
        pdf_bytes: contenido binario del PDF

    Returns:
        Lista de dicts con 'page_number' y 'text' para cada página.
        Las páginas sin texto (imágenes escaneadas) se omiten.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []

    for i, page in enumerate(reader.pages):
        text = page.extract_text()

        # Omitir páginas sin texto (PDFs escaneados, páginas de imagen)
        if not text or len(text.strip()) < 50:
            continue

        pages.append(
            {
                "page_number": i + 1,  # empezamos en 1, no en 0
                "text": text.strip(),
            }
        )

    return pages


# ── División en chunks ───────────────────────────────────────────────────────


def split_into_chunks(pages: list[dict]) -> list[dict]:
    """
    Divide el texto de todas las páginas en chunks con overlap.

    Estrategia:
    1. Juntamos todo el texto con separadores de página
    2. Dividimos en palabras
    3. Creamos ventanas deslizantes de CHUNK_SIZE_WORDS con OVERLAP_WORDS

    Guardamos el page_number del inicio de cada chunk para que el usuario
    sepa en qué página encontrar la información.

    Returns:
        Lista de dicts con 'content', 'page_number', 'chunk_index'.
    """
    # Construimos una lista de (palabra, page_number) para rastrear páginas
    word_page_pairs = []
    for page in pages:
        words = page["text"].split()
        for word in words:
            word_page_pairs.append((word, page["page_number"]))

    if not word_page_pairs:
        return []

    chunks = []
    chunk_index = 0
    start = 0

    while start < len(word_page_pairs):
        end = min(start + CHUNK_SIZE_WORDS, len(word_page_pairs))

        # Extraemos las palabras y la página del primer word del chunk
        chunk_words = [pair[0] for pair in word_page_pairs[start:end]]
        chunk_page = word_page_pairs[start][1]

        chunk_text = " ".join(chunk_words)

        chunks.append(
            {
                "content": chunk_text,
                "page_number": chunk_page,
                "chunk_index": chunk_index,
            }
        )

        chunk_index += 1

        # El siguiente chunk empieza CHUNK_SIZE - OVERLAP palabras después
        # Esto crea el solapamiento
        start += CHUNK_SIZE_WORDS - OVERLAP_WORDS

    return chunks


# ── Generación de embeddings ─────────────────────────────────────────────────


def generate_embeddings(chunks: list[dict]) -> list[dict]:
    """
    Genera un embedding por chunk usando la API de OpenAI.

    Mandamos todos los chunks en una sola llamada (batch) para eficiencia.
    La API acepta hasta 2048 textos por llamada.

    El embedding es una lista de 1536 números que representa el
    'significado' del texto. Textos similares tienen vectores similares.

    Args:
        chunks: lista de dicts con 'content' (el texto del chunk)

    Returns:
        Los mismos chunks con el campo 'embedding' añadido.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Extraemos solo los textos para mandarlos en batch
    texts = [chunk["content"] for chunk in chunks]

    # Una sola llamada para todos los chunks — más eficiente que llamar
    # una vez por chunk
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )

    # Añadimos el embedding a cada chunk
    # response.data tiene los embeddings en el mismo orden que los textos
    for i, embedding_data in enumerate(response.data):
        chunks[i]["embedding"] = embedding_data.embedding

    return chunks


# ── Pipeline completo ────────────────────────────────────────────────────────


def process_pdf(pdf_bytes: bytes) -> list[dict]:
    """
    Pipeline completo: bytes del PDF → chunks con embeddings listos para indexar.

    Args:
        pdf_bytes: contenido binario del PDF

    Returns:
        Lista de chunks con 'content', 'page_number', 'chunk_index', 'embedding'.
        Listos para pasar a database.save_chunks().
    """
    # Paso 1: extraer texto por página
    pages = extract_text_from_pdf(pdf_bytes)

    if not pages:
        raise ValueError(
            "No text could be extracted from this PDF. " "It may be a scanned document without OCR."
        )

    # Paso 2: dividir en chunks con overlap
    chunks = split_into_chunks(pages)

    if not chunks:
        raise ValueError("PDF has text but could not be split into chunks.")

    # Paso 3: generar embeddings en batch
    chunks_with_embeddings = generate_embeddings(chunks)

    return chunks_with_embeddings
