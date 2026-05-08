"""
Extractor de texto para CVs y ofertas de empleo.

Que hace este archivo:
- Lee CVs en PDF (PyMuPDF) y DOCX (python-docx)
- Scrapeea el texto de URLs de ofertas publicas
- Limpia y normaliza el texto extraido

Por que PyMuPDF y no pypdf?
PyMuPDF extrae texto con mejor fidelidad en PDFs complejos
con columnas, tablas y formatos de CV modernos.
Ya lo usas en el PDF Translator — reutilizamos lo conocido.
"""

from __future__ import annotations

import re

import fitz  # PyMuPDF
import httpx
from bs4 import BeautifulSoup
from docx import Document


def extraer_texto_pdf(contenido: bytes) -> str:
    """Extrae texto de un PDF recibido como bytes."""
    doc = fitz.open(stream=contenido, filetype="pdf")
    texto = ""
    for pagina in doc:
        texto += pagina.get_text()
    doc.close()
    return limpiar_texto(texto)


def extraer_texto_docx(contenido: bytes) -> str:
    """Extrae texto de un DOCX recibido como bytes."""
    import io

    doc = Document(io.BytesIO(contenido))
    texto = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return limpiar_texto(texto)


def scrapeear_url(url: str) -> str:
    """
    Extrae el texto principal de una URL de oferta de empleo.

    Funciona con: Infojobs, Indeed, webs de empresa, cualquier URL publica.
    No funciona con: LinkedIn (requiere login), portales con JS pesado.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        response = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise ValueError(f"No se pudo acceder a la URL: {e}")  # noqa: B904

    soup = BeautifulSoup(response.text, "html.parser")

    # Eliminamos elementos que no son contenido
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Intentamos extraer el contenido principal
    # Orden de preferencia: article > main > body
    contenido = (
        soup.find("article")
        or soup.find("main")
        or soup.find(class_=re.compile(r"job|offer|description|content", re.I))
        or soup.find("body")
    )

    if not contenido:
        raise ValueError("No se pudo extraer contenido de la URL")

    texto = contenido.get_text(separator="\n")
    return limpiar_texto(texto)


def limpiar_texto(texto: str) -> str:
    """Limpia y normaliza texto extraido."""
    # Elimina lineas vacias multiples
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    # Elimina espacios multiples
    texto = re.sub(r" {2,}", " ", texto)
    # Elimina caracteres de control
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", texto)
    return texto.strip()
