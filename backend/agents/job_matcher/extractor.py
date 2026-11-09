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

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import fitz  # PyMuPDF
import httpx
from bs4 import BeautifulSoup
from docx import Document

MAX_REDIRECTS = 3


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


def _validar_url_publica(url: str) -> None:
    """Rechaza URLs que no sean http(s) o que resuelvan a redes internas/reservadas (anti-SSRF)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL invalida: solo se admiten http/https")
    if not parsed.hostname:
        raise ValueError("URL invalida: falta host")

    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"No se pudo resolver el host: {e}")  # noqa: B904

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("URL invalida: apunta a una red interna/reservada")


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
        # Redirecciones a mano: cada salto se revalida contra redes internas.
        # ponytail: el DNS se resuelve dos veces (en la validacion y en httpx), asi que un
        # DNS rebinding entre ambas sigue siendo posible; cerrarlo exige conectar a la IP
        # ya validada con un transport propio.
        for _ in range(MAX_REDIRECTS + 1):
            _validar_url_publica(url)
            response = httpx.get(url, headers=headers, timeout=15, follow_redirects=False)
            if not response.is_redirect:
                break
            url = urljoin(str(response.url), response.headers["location"])
        else:
            raise ValueError("URL invalida: demasiadas redirecciones")
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
