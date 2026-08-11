"""
reconstructor_node.py — Nodo 4: Reconstructor del PDF

Último nodo del pipeline. Recibe todos los PDFElement con:
- translated_text: la traducción validada por el Quality Gate
- computed_font_size: el font size calculado para que quepa bien
- quality_status: OK, ACCEPTED o SKIPPED

Estrategia por tipo de elemento:

NATIVE_TEXT:
  1. add_redact_annot con fill=None → borra el texto sin tocar el fondo
  2. apply_redactions(PDF_REDACT_IMAGE_NONE) → no toca imágenes
  3. insert_textbox con computed_font_size → inserta la traducción
     Si no cabe → expande hasta MAX_EXTRA_LINES líneas

IMAGE_TEXT:
  1. add_redact_annot con fill=bg_color → pinta el fondo del color original
  2. apply_redactions(PDF_REDACT_IMAGE_PIXELS) → pinta esos píxeles en la imagen
  3. insert_textbox → escribe el texto encima

IMAGE_ONLY / SKIPPED:
  → No se toca nada. La imagen queda intacta.

¿Por qué procesamos redacciones por tipo separado?
PyMuPDF tiene dos modos de redacción:
- PDF_REDACT_IMAGE_NONE: borra texto nativo sin tocar imágenes
- PDF_REDACT_IMAGE_PIXELS: pinta píxeles en imágenes JPEG embebidas

Si mezclamos las dos en la misma llamada a apply_redactions(), PyMuPDF
aplica el mismo modo a todo. Por eso hacemos dos pasadas por página:
primero las nativas, luego las de imagen.
"""

from __future__ import annotations

from typing import Any

import fitz

from .state import ElementType, PDFElement, QualityStatus, TranslationState

MAX_EXTRA_LINES = 3
TEXT_PADDING = 1.5


def reconstructor_node(state: TranslationState) -> dict[str, Any]:
    """
    Nodo LangGraph: reconstruye el PDF con todas las traducciones.

    Lee el PDF original, aplica las traducciones elemento por elemento,
    y guarda el resultado en output_pdf_path.
    """
    input_path = state["input_pdf_path"]
    output_path = state["output_pdf_path"]
    elements = state["elements"]

    # Si image_patcher ya guardó en output_path, abrimos ese (tiene los patches de imagen)
    # Si no existe todavía, abrimos el original
    import os
    import shutil

    source_path = output_path if os.path.exists(output_path) else input_path
    doc = fitz.open(source_path)

    # Si source y output son el mismo fichero, guardamos a un temp y renombramos
    tmp_path = None
    same_file = os.path.abspath(source_path) == os.path.abspath(output_path)
    if same_file:
        import tempfile

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(tmp_fd)
        save_path = tmp_path
    else:
        save_path = output_path
        tmp_path = None

    # Agrupamos elementos por página
    by_page: dict[int, list[PDFElement]] = {}
    for elem in elements:
        by_page.setdefault(elem.page_num, []).append(elem)

    native_replaced = 0
    image_replaced = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_elements = by_page.get(page_num, [])

        if not page_elements:
            continue

        # ── PASADA 1: Texto nativo ─────────────────────────────────────
        native_elements = [
            e
            for e in page_elements
            if e.element_type == ElementType.NATIVE_TEXT
            and e.quality_status in (QualityStatus.OK, QualityStatus.ACCEPTED)
            and e.is_translated
        ]

        if native_elements:
            for elem in native_elements:
                rect = elem.bbox.to_rect()
                # Encogemos el rect de redacción para evitar rozar con texto
                # adyacente — especialmente fuentes grandes cuyos descenders
                # se solapan con el ascender del siguiente elemento
                shrink = max(3.0, elem.font_size * 0.08)
                safe_rect = fitz.Rect(
                    rect.x0,
                    rect.y0 + shrink,
                    rect.x1,
                    rect.y1 - shrink,
                )
                if safe_rect.is_empty:
                    safe_rect = rect
                page.add_redact_annot(safe_rect, fill=None)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            for elem in native_elements:
                _insert_text(page, elem)
                native_replaced += 1

        # ── PASADA 2: Texto en imágenes ────────────────────────────────
        image_text_elements = [
            e
            for e in page_elements
            if e.element_type == ElementType.IMAGE_TEXT
            and e.quality_status in (QualityStatus.OK, QualityStatus.ACCEPTED)
            and e.is_translated
        ]

        if image_text_elements:
            for elem in image_text_elements:
                bg = _hex_to_rgb_float(elem.bg_color)
                page.add_redact_annot(elem.bbox.to_rect(), fill=bg)

            # PDF_REDACT_IMAGE_PIXELS: pinta exactamente los píxeles marcados
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)

            for elem in image_text_elements:
                _insert_image_text(page, elem)
                image_replaced += 1

    print(f"[Reconstructor] {native_replaced} texto nativo + {image_replaced} imagen")

    doc.save(save_path, garbage=4, deflate=True)
    doc.close()

    # Si guardamos a temp, reemplazamos el output
    if tmp_path:
        shutil.move(tmp_path, output_path)

    print(f"[Reconstructor] PDF guardado: {output_path}")

    return {
        "current_phase": "done",
        "stats": {
            **state.get("stats", {}),
            "native_replaced": native_replaced,
            "image_replaced": image_replaced,
        },
    }


def _cover_and_replace(page: fitz.Page, elem: PDFElement) -> None:
    """
    Reemplaza el texto original con la traducción sin usar redacciones.

    En vez de add_redact_annot (que puede eliminar contenido adyacente),
    usamos una secuencia de dos pasos:
    1. Muestreamos el color de fondo en las esquinas del span (sin texto)
    2. Dibujamos un rect del color de fondo exacto sobre el texto original
    3. Insertamos la traducción encima con overlay=True

    Esto garantiza que solo cubrimos el área exacta del span sin afectar
    elementos cercanos como precios grandes en otro color.
    """
    rect = elem.bbox.to_rect()

    # Muestreamos el color de fondo ANTES de cubrir
    bg_color = _sample_span_background(page, rect)

    # Cubrimos el texto original con un rect del color exacto del fondo
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(fill=bg_color, color=bg_color, width=0)
    shape.commit()

    # Insertamos la traducción encima
    _insert_text(page, elem)


def _sample_span_background(page: fitz.Page, rect: fitz.Rect) -> tuple:
    """
    Muestrea el color de fondo de un span renderizando solo el área del rect.
    Toma las 4 esquinas (donde raramente hay texto) para estimar el fondo.

    Returns: (r, g, b) con valores 0.0 - 1.0
    """
    try:
        clip = fitz.Rect(
            max(0, rect.x0),
            max(0, rect.y0),
            min(page.rect.width, rect.x1),
            min(page.rect.height, rect.y1),
        )
        # Renderizamos a 72 DPI — suficiente para detectar color, muy rápido
        pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), clip=clip, alpha=False)
        if pix.width < 2 or pix.height < 2:
            return (1.0, 1.0, 1.0)

        samples = pix.samples
        w, h = pix.width, pix.height

        # Muestreamos las 4 esquinas — generalmente son fondo puro
        corners = [
            (0, 0),
            (w - 1, 0),
            (0, h - 1),
            (w - 1, h - 1),
        ]
        tr = tg = tb = 0.0
        count = 0
        for cx, cy in corners:
            idx = (cy * w + cx) * 3
            if idx + 2 < len(samples):
                tr += samples[idx] / 255.0
                tg += samples[idx + 1] / 255.0
                tb += samples[idx + 2] / 255.0
                count += 1

        return (tr / count, tg / count, tb / count) if count else (1.0, 1.0, 1.0)

    except Exception:
        return (1.0, 1.0, 1.0)


def _insert_text(page: fitz.Page, elem: PDFElement) -> None:
    """
    Inserta texto traducido en la posición exacta del span original.

    Con la extracción span a span, el bbox es exacto — x0,y0,x1,y1
    corresponden exactamente al glifo en la página.

    Baseline PyMuPDF: y1 del span es el baseline (fondo del texto).
    Usamos y1 directamente para máxima precisión de posición.
    """
    text = elem.translated_text
    font = _select_font(elem)
    # Preservamos el color original del span — con fill=None el fondo
    # original se mantiene, así el contraste siempre es correcto
    color = _int_color_to_rgb(elem.text_color)

    rect = elem.bbox.to_rect()
    original_size = max(elem.font_size, 4.0)
    available_w = max(rect.width, 10.0)

    # Font size: el original si cabe, sino reducimos para que quepa en el ancho
    n_chars = max(1, len(text))
    size_one_line = available_w / (n_chars * 0.55)
    size = max(original_size * 0.55, min(original_size, size_one_line))
    size = max(4.0, size)

    # Baseline: y1 del bbox menos el descender estimado
    # Evita que el texto reinsertado tape elementos adyacentes de abajo
    descender = size * 0.2
    baseline_y = rect.y1 - descender

    page.insert_text(
        point=fitz.Point(rect.x0, baseline_y),
        text=text,
        fontname=font,
        fontsize=size,
        color=color,
        overlay=True,
    )


def _insert_image_text(page: fitz.Page, elem: PDFElement) -> None:
    """
    Inserta texto traducido sobre una zona de imagen con fondo sólido.
    El área ya fue pintada con el color de fondo por la redacción.
    """
    text = elem.translated_text
    size = elem.computed_font_size or elem.font_size
    if size <= 0:
        size = 10.0

    font = "hebo" if elem.is_bold else "helv"
    txt_color = _hex_to_rgb_float(elem.bg_color if _is_light_hex(elem.bg_color) else "#ffffff")

    # Para texto en imágenes, el color del texto es el que Vision detectó
    if hasattr(elem, "text_color_hex"):
        txt_color = _hex_to_rgb_float(elem.text_color_hex)

    rect = elem.bbox.to_rect()
    inner = rect + (TEXT_PADDING, TEXT_PADDING, -TEXT_PADDING, -TEXT_PADDING)
    if inner.is_empty:
        inner = rect

    min_size = max(5.0, size * 0.7)
    current_size = size

    while current_size >= min_size:
        result = page.insert_textbox(
            rect=inner,
            buffer=text,
            fontname=font,
            fontsize=current_size,
            color=txt_color,
            align=fitz.TEXT_ALIGN_LEFT,
            overlay=True,
        )
        if result >= 0:
            return
        current_size *= 0.88
        if current_size < min_size:
            break

    page.insert_textbox(
        rect=inner,
        buffer=text,
        fontname=font,
        fontsize=max(5.0, min_size),
        color=txt_color,
        align=fitz.TEXT_ALIGN_LEFT,
        overlay=True,
    )


def _select_font(elem: PDFElement) -> str:
    """Selecciona la fuente correcta según flags y contenido."""
    text = elem.translated_text
    # CJK
    for char in text:
        code = ord(char)
        if 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF:
            return "cjk"
    # Bold/italic
    if elem.font_flags & 16:
        return "hebo"
    if elem.font_flags & 2:
        return "heit"
    return "helv"


def _int_color_to_rgb(color_int: int) -> tuple:
    """Convierte color int de PyMuPDF a RGB flotante (0.0-1.0)."""
    r = (color_int >> 16) & 0xFF
    g = (color_int >> 8) & 0xFF
    b = color_int & 0xFF
    return (r / 255.0, g / 255.0, b / 255.0)


def _hex_to_rgb_float(hex_color: str) -> tuple:
    """Convierte hex a RGB flotante (0.0-1.0)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (1.0, 1.0, 1.0)
    try:
        return (
            int(h[0:2], 16) / 255.0,
            int(h[2:4], 16) / 255.0,
            int(h[4:6], 16) / 255.0,
        )
    except ValueError:
        return (1.0, 1.0, 1.0)


def _is_light_hex(hex_color: str) -> bool:
    """True si el color es claro."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return True
    try:
        r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) > 128
    except ValueError:
        return True


def _sample_bg_color(page: fitz.Page, rect: fitz.Rect) -> tuple:
    """
    Muestrea el color de fondo de una zona renderizando la página antes de redactar.
    Toma píxeles de las esquinas (donde no hay texto normalmente).
    Returns (r, g, b) con valores 0.0-1.0.
    """
    try:
        clip = fitz.Rect(
            max(0, rect.x0),
            max(0, rect.y0),
            min(page.rect.width, rect.x1),
            min(page.rect.height, rect.y1),
        )
        pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), clip=clip, alpha=False)
        if pix.width == 0 or pix.height == 0:
            return (1.0, 1.0, 1.0)

        samples = pix.samples
        w, h = pix.width, pix.height

        # Muestreamos las 4 esquinas — donde casi nunca hay texto
        corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
        total_r = total_g = total_b = 0.0
        count = 0
        for cx, cy in corners:
            idx = (cy * w + cx) * 3
            if idx + 2 < len(samples):
                total_r += samples[idx] / 255.0
                total_g += samples[idx + 1] / 255.0
                total_b += samples[idx + 2] / 255.0
                count += 1

        if count == 0:
            return (1.0, 1.0, 1.0)

        return (total_r / count, total_g / count, total_b / count)

    except Exception:
        return (1.0, 1.0, 1.0)
