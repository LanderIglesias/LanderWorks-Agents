"""
image_patcher_node.py — Parchea texto en imágenes usando redacciones PDF

Técnica correcta para texto embebido en imágenes JPEG:
1. add_redact_annot con fill=color_fondo  → marca la zona
2. apply_redactions(PDF_REDACT_IMAGE_PIXELS) → pinta esos píxeles en el JPEG
3. insert_text → escribe el texto traducido encima

PDF_REDACT_IMAGE_PIXELS es el único método que realmente modifica los píxeles
de las imágenes JPEG embebidas. shape.draw_rect solo añade vectores encima
que quedan detrás de la imagen raster.
"""

from __future__ import annotations

import io
from typing import Any

import fitz

from .image_strategy_node import compute_font_size_for_strategy
from .state import ElementType, ImageStrategy, PDFElement, TranslationState

TEXT_PADDING = 1.5


def image_patcher_node(state: TranslationState) -> dict[str, Any]:
    input_path = state["input_pdf_path"]
    output_path = state["output_pdf_path"]
    elements = state["elements"]
    page_images = state.get("page_images", {})

    import os

    source_path = output_path if os.path.exists(output_path) else input_path
    doc = fitz.open(source_path)

    by_page: dict[int, list[PDFElement]] = {}
    for elem in elements:
        if elem.element_type == ElementType.IMAGE_TEXT:
            if elem.image_strategy != ImageStrategy.SKIP and elem.is_translated:
                by_page.setdefault(elem.page_num, []).append(elem)

    patched_total = 0

    for page_num, page_elements in by_page.items():
        page = doc[page_num]
        page_image_bytes = page_images.get(page_num)

        # Paso 1: añadir todas las redacciones de la página
        elem_rects = []
        for elem in page_elements:
            rect = elem.bbox.to_rect()
            if rect.is_empty or rect.width < 5 or rect.height < 3:
                continue

            bg_rgb = _get_bg_color(elem, page_image_bytes)

            # Expandimos ligeramente el rect para cubrir bordes del texto original
            expanded = fitz.Rect(
                rect.x0 - 1,
                rect.y0 - 1,
                rect.x1 + 1,
                rect.y1 + 1,
            )
            page.add_redact_annot(expanded, fill=bg_rgb)
            elem_rects.append((expanded, elem, bg_rgb))

        if not elem_rects:
            continue

        # Paso 2: aplicar todas las redacciones → pinta píxeles JPEG
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)

        # Paso 3: insertar texto traducido en cada zona
        for rect, elem, bg_rgb in elem_rects:
            success = _insert_translated_text(page, rect, elem, bg_rgb)
            if success:
                patched_total += 1

    print(f"[ImagePatcher] {patched_total} elementos de imagen parcheados")

    tmp_path = None
    import shutil
    import tempfile

    same_file = os.path.abspath(source_path) == os.path.abspath(output_path)
    if same_file:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(tmp_fd)
        save_path = tmp_path
    else:
        save_path = output_path

    doc.save(save_path, garbage=4, deflate=True)
    doc.close()

    if tmp_path:
        shutil.move(tmp_path, output_path)

    return {
        "current_phase": "image_patched",
        "stats": {**state.get("stats", {}), "image_patched": patched_total},
    }


def _insert_translated_text(
    page: fitz.Page,
    rect: fitz.Rect,
    elem: PDFElement,
    bg_rgb: tuple,
) -> bool:
    try:
        translated = _clean_text(elem.translated_text.strip())
        if not translated:
            return False

        font_size = compute_font_size_for_strategy(elem)
        font_size = max(4.0, font_size)

        # Color del texto — preservamos el original, ajustamos si hay poco contraste
        txt_rgb = _hex_to_rgb(elem.text_color_hex)
        bg_lum = bg_rgb[0] * 0.299 + bg_rgb[1] * 0.587 + bg_rgb[2] * 0.114
        txt_lum = txt_rgb[0] * 0.299 + txt_rgb[1] * 0.587 + txt_rgb[2] * 0.114

        if abs(bg_lum - txt_lum) < 0.3:
            txt_rgb = (0.05, 0.05, 0.05) if bg_lum > 0.5 else (0.95, 0.95, 0.95)

        font = "hebo" if elem.is_bold else "helv"

        # Centramos el texto verticalmente en el rect
        # baseline = centro del rect + font_size/2
        x = rect.x0 + TEXT_PADDING
        center_y = (rect.y0 + rect.y1) / 2
        baseline_y = center_y + font_size * 0.35  # ajuste empírico para centrado visual

        page.insert_text(
            point=fitz.Point(x, baseline_y),
            text=translated,
            fontname=font,
            fontsize=font_size,
            color=txt_rgb,
            overlay=True,
        )
        return True

    except Exception as e:
        print(f"[ImagePatcher] Warning {elem.element_id}: {e}")
        return False


def _clean_text(text: str) -> str:
    """
    Limpia el texto antes de insertar:
    - Reemplaza € por EUR (Helvetica no tiene el glifo €)
    - Elimina caracteres no soportados por las fuentes base de PyMuPDF
    """
    text = text.replace("€", " EUR").replace("£", "GBP").replace("©", "(c)")
    # Eliminamos caracteres fuera del rango Latin-1 que Helvetica no soporta
    cleaned = ""
    for c in text:
        if ord(c) < 256 or c in "–—…":
            cleaned += c if ord(c) < 256 else "-"
        else:
            cleaned += "?"
    return cleaned.strip()


def _get_bg_color(elem: PDFElement, page_image_bytes: bytes | None) -> tuple:
    """Obtiene el color de fondo para la redacción."""
    if elem.bg_is_solid:
        return _hex_to_rgb(elem.bg_color)

    # Fondo complejo → muestreamos del render
    if page_image_bytes:
        return _sample_corners(
            page_image_bytes,
            elem.bbox.x0 / elem.page_width,
            elem.bbox.y0 / elem.page_height,
            elem.bbox.x1 / elem.page_width,
            elem.bbox.y1 / elem.page_height,
        )
    return _hex_to_rgb(elem.bg_color)


def _sample_corners(
    page_bytes: bytes,
    x0_pct: float,
    y0_pct: float,
    x1_pct: float,
    y1_pct: float,
) -> tuple[float, float, float]:
    """Muestrea el color de fondo de las esquinas del bbox."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(page_bytes)).convert("RGB")
        w, h = img.size
        x0, y0 = int(x0_pct * w), int(y0_pct * h)
        x1, y1 = int(x1_pct * w), int(y1_pct * h)
        corners = [
            (max(0, x0), max(0, y0)),
            (min(w - 1, x1 - 1), max(0, y0)),
            (max(0, x0), min(h - 1, y1 - 1)),
            (min(w - 1, x1 - 1), min(h - 1, y1 - 1)),
        ]
        tr, tg, tb, n = 0.0, 0.0, 0.0, 0
        for cx, cy in corners:
            r, g, b = img.getpixel((cx, cy))
            tr += r / 255.0
            tg += g / 255.0
            tb += b / 255.0
            n += 1
        return (tr / n, tg / n, tb / n) if n else (1.0, 1.0, 1.0)
    except Exception:
        return (1.0, 1.0, 1.0)


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (1.0, 1.0, 1.0)
    try:
        return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)
    except ValueError:
        return (1.0, 1.0, 1.0)
