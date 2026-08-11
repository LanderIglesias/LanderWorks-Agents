"""
analyzer_node.py — Nodo 1: Analizador del PDF

Este es el primer nodo del grafo. Su trabajo es leer el PDF completo
y crear un PDFElement por cada bloque de contenido relevante.

Para cada elemento decide:
- ¿Es texto nativo? → ElementType.NATIVE_TEXT
- ¿Es una imagen con texto traducible (fondo sólido)? → ElementType.IMAGE_TEXT
- ¿Es una imagen que mejor dejar intacta? → ElementType.IMAGE_ONLY

¿Qué diferencia este Analyzer del parser anterior?
→ El anterior solo extraía texto nativo.
→ Este también analiza las imágenes con Claude Sonnet Vision para decidir
  si merecen traducción, y si es así, detecta los bloques de texto dentro.
→ El resultado es una lista completa de TODOS los elementos del PDF,
  no solo los nativos, con la información necesaria para cada nodo posterior.

Separar el análisis del procesamiento es el patrón correcto en LangGraph:
el Analyzer crea el "mapa" del PDF, y los nodos siguientes ejecutan
acciones específicas sobre cada elemento sin necesidad de re-analizar.
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import anthropic
import fitz
from dotenv import load_dotenv

from .state import BBox, ElementType, PDFElement, TranslationState

load_dotenv()

# Tamaño mínimo de texto para ser traducible
MIN_TEXT_LENGTH = 3
MIN_FONT_SIZE = 5.0

# Escala para renderizar páginas que enviamos a Vision
VISION_RENDER_SCALE = 2.0

# Luminancia mínima de contraste para considerar texto sobre fondo sólido
# (diferencia entre color de texto y color de fondo)
MIN_CONTRAST_LUMINANCE = 50


def analyzer_node(state: TranslationState) -> dict[str, Any]:
    print(f"\n[Analyzer] Analizando PDF: {state['input_pdf_path']}")

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    doc = fitz.open(state["input_pdf_path"])

    all_elements: list[PDFElement] = []
    pages_info: list[dict[str, Any]] = []
    page_images: dict[int, bytes] = {}

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_w = page.rect.width
        page_h = page.rect.height

        pages_info.append({"page_num": page_num, "width": page_w, "height": page_h})

        native_elements = _extract_native_text(page, page_num, page_w, page_h)
        all_elements.extend(native_elements)

        # Renderizamos la página y guardamos los bytes para el image patcher
        page_bytes, img_w, img_h = _render_page(page)
        if page_bytes:
            page_images[page_num] = page_bytes
            image_elements = _analyze_images(
                client, page, page_bytes, img_w, img_h, page_num, page_w, page_h
            )
            # Deduplicación: descartamos IMAGE_TEXT que solapan con texto nativo
            # Esto evita que el image patcher pinte encima de texto nativo ya traducido
            image_elements = _deduplicate_with_native(image_elements, native_elements)
            all_elements.extend(image_elements)
        else:
            image_elements = []

        native_count = len(native_elements)
        img_text = len([e for e in image_elements if e.element_type == ElementType.IMAGE_TEXT])
        print(
            f"[Analyzer] Página {page_num + 1}: {native_count} texto nativo, {img_text} imagen+texto"
        )

    doc.close()
    total = len(all_elements)
    translatable = len([e for e in all_elements if e.needs_translation])
    print(f"[Analyzer] Total: {total} elementos, {translatable} a traducir")

    return {
        "elements": all_elements,
        "pages_info": pages_info,
        "page_images": page_images,
        "current_phase": "analyzed",
        "stats": {"total_elements": total, "translatable": translatable, "pages": len(pages_info)},
    }


def _render_page(page: fitz.Page) -> tuple:
    """Renderiza la página como JPEG. Returns (bytes, width, height)."""
    try:
        matrix = fitz.Matrix(VISION_RENDER_SCALE, VISION_RENDER_SCALE)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("jpeg"), pix.width, pix.height
    except Exception as e:
        print(f"[Analyzer] Warning renderizando: {e}")
        return None, 0, 0


def _extract_native_text(
    page: fitz.Page,
    page_num: int,
    page_w: float,
    page_h: float,
) -> list[PDFElement]:
    """
    Extrae texto nativo del PDF span a span.

    Extraemos cada span individualmente en vez de unir todo el bloque.
    Esto da control preciso sobre la posición y el estilo de cada trozo
    de texto — es la forma más fiel al original.

    Un "span" en PyMuPDF = una secuencia de caracteres con el mismo
    estilo (fuente, tamaño, color). Cada span tiene su propio bbox exacto.
    """
    elements = []
    page_dict = page.get_text("dict")
    elem_idx = 0

    for block in page_dict["blocks"]:
        if block["type"] != 0:
            continue

        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if not text or len(text) < MIN_TEXT_LENGTH:
                    continue
                if span["size"] < MIN_FONT_SIZE:
                    continue
                if _is_numeric_or_untranslatable(text):
                    continue

                x0, y0, x1, y1 = span["bbox"]

                element = PDFElement(
                    element_id=f"p{page_num}_s{elem_idx}",
                    page_num=page_num,
                    element_type=ElementType.NATIVE_TEXT,
                    bbox=BBox(x0, y0, x1, y1),
                    page_width=page_w,
                    page_height=page_h,
                    original_text=text,
                    font_size=span["size"],
                    font_flags=span["flags"],
                    text_color=span["color"],
                    bg_color="#ffffff",
                    is_bold=bool(span["flags"] & 16),
                )
                elements.append(element)
                elem_idx += 1

    return elements


def _analyze_images(
    client: anthropic.Anthropic,
    page: fitz.Page,
    page_bytes: bytes,
    img_w: int,
    img_h: int,
    page_num: int,
    page_w: float,
    page_h: float,
) -> list[PDFElement]:
    image_list = page.get_images(full=True)
    if not image_list:
        return []

    detected_regions = _vision_detect_image_text(client, page_bytes, img_w, img_h)
    if not detected_regions:
        return []

    elements = []
    for idx, region in enumerate(detected_regions):
        rx0 = region["bbox_pct"][0] * page_w
        ry0 = region["bbox_pct"][1] * page_h
        rx1 = region["bbox_pct"][2] * page_w
        ry1 = region["bbox_pct"][3] * page_h

        if (rx1 - rx0) < 5 or (ry1 - ry0) < 3:
            continue

        element = PDFElement(
            element_id=f"p{page_num}_img{idx}",
            page_num=page_num,
            element_type=ElementType.IMAGE_TEXT,
            bbox=BBox(rx0, ry0, rx1, ry1),
            page_width=page_w,
            page_height=page_h,
            original_text=region["text"],
            font_size=region["font_size_pct"] * page_h,
            bg_color=region["bg_color"],
            text_color_hex=region["text_color"],
            bg_is_solid=region.get("bg_is_solid", True),
            is_bold=region["is_bold"],
            text_color=0xFFFFFF if _is_light_color(region["text_color"]) else 0x000000,
        )
        elements.append(element)

    return elements


def _vision_detect_image_text(
    client: anthropic.Anthropic,
    page_bytes: bytes,
    img_w: int,
    img_h: int,
) -> list[dict]:
    """
    Envía la página renderizada a Claude Sonnet Vision.
    Detecta SOLO texto en fondos de color sólido no-blanco.

    Retorna lista de dicts con: text, bbox_pct, bg_color, text_color,
    is_bold, font_size_pct.
    """
    b64 = base64.standard_b64encode(page_bytes).decode("utf-8")

    system_prompt = f"""You analyze a PDF page ({img_w}×{img_h} pixels) to find ALL readable text inside graphical/image elements.

Detect EVERY text element that is part of an image or graphic — including:
- Text on solid color backgrounds (banners, headers, labels)
- Text on photo backgrounds
- Text on gradient or patterned backgrounds
- Large display text (titles, prices, slogans)
- Small descriptive text within graphics

DO NOT detect:
- Product reference codes (OBYP4-L0.5-101, JG-LOCK-X9, etc.)
- Pure numbers standing alone
- Brand logos or decorative text that cannot be translated
- Page numbers

For each element:
- bbox_pct: [x0, y0, x1, y1] as page fractions 0.0-1.0
- bg_color: dominant background color hex (best estimate)
- bg_is_solid: true if background is a flat solid color, false if photo/gradient/texture
- text_color: hex color of the text
- font_size_pct: cap-height as fraction of page height
- is_bold: true/false

Return ONLY valid JSON:
{{
  "regions": [
    {{
      "text": "ANNIVERSARY SALE",
      "bbox_pct": [0.02, 0.45, 0.55, 0.58],
      "bg_color": "#cc1122",
      "bg_is_solid": false,
      "text_color": "#ffffff",
      "is_bold": true,
      "font_size_pct": 0.06
    }}
  ]
}}

If no translatable text: {{"regions": []}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=3000,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                        },
                        {"type": "text", "text": "Find text on solid-color backgrounds only."},
                    ],
                },
                {"role": "assistant", "content": "{"},
            ],
        )

        raw = "{" + response.content[0].text.strip()
        return _parse_vision_response(raw)

    except Exception as e:
        print(f"[Analyzer] Warning Vision API: {e}")
        return []


def _parse_vision_response(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return []

    regions = []
    for item in data.get("regions", []):
        text = item.get("text", "").strip()
        bbox = item.get("bbox_pct", [])
        if not text or len(text) < 2 or len(bbox) != 4:
            continue
        try:
            bbox = [max(0.0, min(1.0, float(v))) for v in bbox]
        except (ValueError, TypeError):
            continue
        if bbox[2] - bbox[0] < 0.01 or bbox[3] - bbox[1] < 0.005:
            continue
        try:
            font_size_pct = max(0.008, min(0.12, float(item.get("font_size_pct", 0.02))))
        except (ValueError, TypeError):
            font_size_pct = 0.02

        regions.append(
            {
                "text": text,
                "bbox_pct": tuple(bbox),
                "bg_color": item.get("bg_color", "#ffffff"),
                "bg_is_solid": bool(item.get("bg_is_solid", True)),
                "text_color": item.get("text_color", "#000000"),
                "is_bold": bool(item.get("is_bold", False)),
                "font_size_pct": font_size_pct,
            }
        )

    return regions


def _is_near_white(hex_color: str) -> bool:
    """True si el color es blanco o muy claro (no es fondo sólido de color)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return True
    try:
        r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) > 210
    except ValueError:
        return True


def _is_light_color(hex_color: str) -> bool:
    """True si el color es claro (texto claro sobre fondo oscuro)."""
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


def _is_numeric_or_untranslatable(text: str) -> bool:
    """
    True si el texto NO necesita traducción.
    Usa ratio de caracteres alfabéticos como filtro principal:
    si menos del 30% son letras reales → es numérico/técnico → skip.
    """
    import re

    s = text.strip()
    if not s:
        return True

    # ── Filtro principal: ratio de caracteres alfabéticos ─────────────
    # "999.-" → 0% alfa → skip
    # "1400 r.p.m." → 27% alfa → skip
    # "OFFER" → 100% alfa → traducir
    # "Función Vapor Refresh" → 95% alfa → traducir
    alpha_count = sum(1 for c in s if c.isalpha())
    total = len(s)
    if total > 0 and alpha_count / total < 0.30:
        return True

    # ── Filtros secundarios para casos mixtos ──────────────────────────

    # Referencia de producto: "Ref.: 1579408"
    if re.match(r"^Ref\.?:?\s*[\d\w/-]+$", s, re.IGNORECASE):
        return True

    # Código de modelo alfanumérico: "WW90T4042CE", "GBV5240APY"
    # (letras Y dígitos mezclados, sin espacios, sin palabras reales)
    if re.match(r"^[A-Za-z]{1,5}\d+[A-Za-z\d]*$", s) and any(c.isdigit() for c in s):
        return True

    return False


def _deduplicate_with_native(
    image_elements: list[PDFElement],
    native_elements: list[PDFElement],
) -> list[PDFElement]:
    """
    Descarta elementos IMAGE_TEXT que se solapan con texto nativo.

    Vision detecta el texto renderizado de la página — incluyendo texto nativo.
    Si el reconstructor ya va a traducir ese texto, no queremos que el image
    patcher también lo pinte encima creando artefactos visuales.

    Un IMAGE_TEXT se descarta si su centro cae dentro de algún bbox nativo
    expandido un 20% (para cubrir pequeñas imprecisiones de Vision).
    """
    if not native_elements:
        return image_elements

    kept = []
    for img_elem in image_elements:
        # Centro del elemento de imagen
        cx = (img_elem.bbox.x0 + img_elem.bbox.x1) / 2
        cy = (img_elem.bbox.y0 + img_elem.bbox.y1) / 2

        overlaps = False
        for nat in native_elements:
            # Expandimos el bbox nativo un 20% para mayor tolerancia
            margin_x = nat.bbox.width * 0.20
            margin_y = nat.bbox.height * 0.30
            if (
                nat.bbox.x0 - margin_x <= cx <= nat.bbox.x1 + margin_x
                and nat.bbox.y0 - margin_y <= cy <= nat.bbox.y1 + margin_y
            ):
                overlaps = True
                break

        if not overlaps:
            kept.append(img_elem)

    discarded = len(image_elements) - len(kept)
    if discarded > 0:
        print(
            f"[Analyzer] Deduplicación: {discarded} IMAGE_TEXT descartados (solapan con texto nativo)"
        )

    return kept
