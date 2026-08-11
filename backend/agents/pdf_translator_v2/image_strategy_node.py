"""
image_strategy_node.py — Nodo: Decisor de estrategia por elemento

Aquí está la inteligencia del sistema. Para cada IMAGE_TEXT element decide
cuál es la mejor estrategia dado:
- El script del texto original (LATIN, ASIAN, CYRILLIC, ARABIC)
- El tamaño del bbox disponible
- La longitud del texto traducido vs. el original
- El tamaño de fuente detectado

Estrategias posibles:
- FULL_STYLE: mismo tamaño, mismo color, mismo estilo → resultado perfecto
- REDUCED_SIZE: font reducido al 80-85%, mismo color → resultado muy bueno
- BEST_EFFORT: font mínimo, intenta mantener color → resultado aceptable
- SKIP: no tocar → preserva la imagen original

Criterios de decisión:
┌────────────────────────────────────────────────────────────┐
│ Script   │ Condición               │ Estrategia             │
├──────────┼─────────────────────────┼────────────────────────┤
│ LATIN    │ cabe a 100%             │ FULL_STYLE             │
│ LATIN    │ cabe al 80%             │ REDUCED_SIZE           │
│ LATIN    │ cabe al 60%             │ BEST_EFFORT            │
│ LATIN    │ no cabe ni al 60%       │ BEST_EFFORT (mínimo)   │
├──────────┼─────────────────────────┼────────────────────────┤
│ ASIAN    │ bbox ≥ 12pt height      │ BEST_EFFORT            │
│ ASIAN    │ bbox < 12pt height      │ SKIP (demasiado pequeño│
├──────────┼─────────────────────────┼────────────────────────┤
│ CYRILLIC │ cabe al 80%             │ REDUCED_SIZE           │
│ CYRILLIC │ no cabe al 80%          │ BEST_EFFORT            │
├──────────┼─────────────────────────┼────────────────────────┤
│ ARABIC   │ cualquiera              │ BEST_EFFORT (RTL issue)│
└────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from typing import Any

from .state import ElementType, ImageStrategy, LanguageScript, PDFElement, TranslationState

# Ancho medio de carácter en Helvetica como fracción del font size
CHAR_WIDTH_RATIO = 0.55

# Umbral mínimo de font size para que el texto sea legible
MIN_READABLE_FONT = 6.0


def image_strategy_node(state: TranslationState) -> dict[str, Any]:
    """
    Nodo LangGraph: decide la estrategia de patch para cada IMAGE_TEXT element.
    """
    elements = state["elements"]
    counts = {s: 0 for s in ImageStrategy}

    for elem in elements:
        if elem.element_type != ElementType.IMAGE_TEXT:
            continue
        if not elem.is_translated:
            elem.image_strategy = ImageStrategy.SKIP
            continue

        strategy = _decide_strategy(elem)
        elem.image_strategy = strategy
        counts[strategy] += 1
        print(
            f"[Strategy] {elem.element_id}: {elem.language_script} "
            f"→ {strategy} ('{elem.original_text[:20]}')"
        )

    print(
        f"[Strategy] Resumen: "
        f"FULL={counts[ImageStrategy.FULL_STYLE]} "
        f"REDUCED={counts[ImageStrategy.REDUCED_SIZE]} "
        f"BEST={counts[ImageStrategy.BEST_EFFORT]} "
        f"SKIP={counts[ImageStrategy.SKIP]}"
    )

    return {"elements": elements, "current_phase": "strategy_decided"}


def _decide_strategy(elem: PDFElement) -> ImageStrategy:
    """Decide la estrategia óptima para un elemento de imagen."""

    # ── Filtro: elementos que no necesitan traducción ─────────────────
    if _is_numeric_or_code(elem.original_text):
        return ImageStrategy.SKIP

    script = elem.language_script
    translated = elem.translated_text
    font_size = max(elem.font_size, 4.0)
    bbox_w = elem.bbox.width
    bbox_h = elem.bbox.height

    # Estimamos el ancho del texto traducido al font size original
    est_width = len(translated) * font_size * CHAR_WIDTH_RATIO

    if script == LanguageScript.LATIN:
        return _latin_strategy(est_width, bbox_w, font_size, bbox_h)

    elif script == LanguageScript.ASIAN:
        return _asian_strategy(font_size, bbox_h)

    elif script == LanguageScript.CYRILLIC:
        # Cirílico → latino: ratio ~1:1, tratamos como latin pero más conservador
        if font_size < MIN_READABLE_FONT:
            return ImageStrategy.SKIP
        if est_width <= bbox_w * 1.3:
            return ImageStrategy.REDUCED_SIZE
        return ImageStrategy.BEST_EFFORT

    elif script == LanguageScript.ARABIC:
        # Árabe es RTL — por ahora solo BEST_EFFORT (no implementamos RTL rendering)
        if font_size < MIN_READABLE_FONT:
            return ImageStrategy.SKIP
        return ImageStrategy.BEST_EFFORT

    else:
        # UNKNOWN → tratamos como latin
        return _latin_strategy(est_width, bbox_w, font_size, bbox_h)


def _latin_strategy(
    est_width: float, bbox_w: float, font_size: float, bbox_h: float
) -> ImageStrategy:
    """Estrategia para texto latino (incluye inglés, español, francés, etc.)"""
    if font_size < MIN_READABLE_FONT:
        return ImageStrategy.BEST_EFFORT  # font pequeño pero intentamos

    # ¿Cabe al 100% del font size original?
    if est_width <= bbox_w * 1.05:
        return ImageStrategy.FULL_STYLE

    # ¿Cabe al 80%?
    if est_width <= bbox_w * 1.35:
        return ImageStrategy.REDUCED_SIZE

    # ¿Cabe al 60%?
    if est_width <= bbox_w * 1.8:
        return ImageStrategy.BEST_EFFORT

    # No cabe bien pero intentamos de todas formas al mínimo
    return ImageStrategy.BEST_EFFORT


def _asian_strategy(font_size: float, bbox_h: float) -> ImageStrategy:
    """
    Estrategia para texto asiático.
    Los caracteres CJK son cuadrados — el texto traducido a latino
    suele ser 2-3x más largo. El bbox es el de los caracteres CJK.
    """
    # Si el bbox es muy pequeño, el texto traducido quedaría ilegible
    if bbox_h < 10 or font_size < 8:
        return ImageStrategy.SKIP

    # Bbox razonable → intentamos BEST_EFFORT
    return ImageStrategy.BEST_EFFORT


def _is_numeric_or_code(text: str) -> bool:
    """
    True si el texto es principalmente numérico o un código técnico
    que no necesita traducción.

    Casos que detectamos:
    - Precios: "999.-", "1.299,00", "44.90€"
    - Medidas: "1400 r.p.m.", "100 W", "721 m³/h", "8L"
    - Potencias, capacidades, velocidades con unidades
    - Porcentajes, referencias técnicas
    """
    import re

    stripped = text.strip()

    # Vacío o muy corto
    if len(stripped) <= 1:
        return True

    # Contamos caracteres: dígitos, puntuación y símbolos de unidad
    numeric_chars = sum(1 for c in stripped if c.isdigit() or c in ".,.-€$£%/³²°")

    # Si >60% son numéricos/puntuación → skip
    if numeric_chars / max(1, len(stripped)) > 0.60:
        return True

    # Patrones de medidas técnicas con unidades cortas: "1400 r.p.m.", "100 W", "8L"
    if re.match(r"^\d[\d\s.,]*\s*[a-zA-ZµΩ³²°/.-]{1,8}\.?$", stripped):
        return True

    # Solo números y símbolos de precio: "999.-", "1.299€"
    if re.match(r"^[\d\s.,·€$£°%-]+\.?-?$", stripped):
        return True

    return False


def compute_font_size_for_strategy(elem: PDFElement) -> float:
    """
    Calcula el font size real a usar según la estrategia.
    Llamado por el image_patcher_node.
    """
    original = elem.font_size
    strategy = elem.image_strategy
    translated = elem.translated_text
    bbox_w = elem.bbox.width

    if strategy == ImageStrategy.FULL_STYLE:
        return original

    if strategy == ImageStrategy.REDUCED_SIZE:
        return max(MIN_READABLE_FONT, original * 0.80)

    if strategy == ImageStrategy.BEST_EFFORT:
        n_chars = max(1, len(translated))
        size_one_line = bbox_w / (n_chars * CHAR_WIDTH_RATIO)
        max_size = original * 0.75
        return max(MIN_READABLE_FONT, min(max_size, size_one_line))

    return original
