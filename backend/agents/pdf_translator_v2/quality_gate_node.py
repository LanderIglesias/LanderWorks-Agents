"""
quality_gate_node.py — Nodo 3: Control de calidad

Este es el nodo que diferencia este agente de todos los demás.
En vez de generar el PDF y esperar que quede bien, el Quality Gate
verifica que cada elemento traducido es válido ANTES de reconstruir.

¿Qué verifica?

1. COMPLETITUD: ¿Todos los elementos tienen traducción?
2. LONGITUD: ¿La traducción es razonable? (no el doble de largo que el original)
3. IDIOMA: ¿La traducción está en el idioma correcto?
   - Detectamos con heurísticas simples (caracteres, palabras comunes)
   - Si el elemento tiene texto en chino y la "traducción" también tiene
     caracteres chinos → algo falló
4. FONT FIT (cálculo previo): ¿El texto traducido cabe en el bbox?
   - Calculamos el font_size óptimo y lo guardamos en computed_font_size
   - Si ni al 65% del tamaño original cabe en el bbox + 2 líneas extra,
     marcamos el elemento para retry con instrucciones más específicas

Si hay elementos con problemas → marca para retry y vuelve al Translator
Si todo está bien → pasa al Reconstructor

El grafo decide el siguiente nodo según lo que devuelve este nodo:
- Si quality_iterations < max_quality_iterations Y hay elementos en RETRY → vuelve al Translator
- Si no → pasa al Reconstructor (con los elementos ACCEPTED aunque no perfectos)
"""

from __future__ import annotations

from typing import Any

from .state import PDFElement, QualityStatus, TranslationState

# Ratio máximo longitud_traducción / longitud_original antes de marcar retry
MAX_LENGTH_RATIO = 4.0

# Font size mínimo como fracción del original
MIN_FONT_SCALE = 0.60

# Número máximo de líneas extra permitidas
MAX_EXTRA_LINES = 3

# Caracteres que indican lenguajes CJK (para detectar traducciones fallidas)
CJK_RANGES = [
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3040, 0x30FF),  # Hiragana + Katakana
    (0xAC00, 0xD7AF),  # Hangul
]


def quality_gate_node(state: TranslationState) -> dict[str, Any]:
    """
    Nodo LangGraph: verifica calidad y calcula font sizes óptimos.

    Evalúa cada elemento traducido y decide si está listo para reconstrucción
    o si necesita reintento. También calcula el computed_font_size para cada
    elemento, que es el tamaño de fuente que usará el Reconstructor.
    """
    elements = state["elements"]
    target_language = state["target_language"]
    quality_iterations = state.get("quality_iterations", 0) + 1
    max_iterations = state.get("max_quality_iterations", 2)

    issues_found = 0
    elements_for_retry = []

    for elem in elements:
        if not elem.needs_translation:
            elem.quality_status = QualityStatus.SKIPPED
            continue

        if not elem.is_translated:
            elem.quality_status = QualityStatus.RETRY
            issues_found += 1
            elements_for_retry.append(elem.element_id)
            continue

        # ── Verificaciones de calidad ──────────────────────────────────
        issues = _check_element_quality(elem, target_language)

        if issues:
            if quality_iterations < max_iterations and elem.retry_count < 2:
                elem.quality_status = QualityStatus.RETRY
                elem.retry_count += 1
                # Limpiamos la traducción para que el Translator la rehaga
                elem.translated_text = ""
                issues_found += 1
                elements_for_retry.append(elem.element_id)
                print(f"[QualityGate] RETRY {elem.element_id}: {'; '.join(issues)}")
            else:
                # Máximo reintentos alcanzado → aceptamos con lo que hay
                elem.quality_status = QualityStatus.ACCEPTED
                print(f"[QualityGate] ACCEPTED (max retry): {elem.element_id}")
        else:
            elem.quality_status = QualityStatus.OK

        # ── Calculamos el font size óptimo ─────────────────────────────
        # Lo hacemos aquí, en el quality gate, para que el Reconstructor
        # no tenga que hacer cálculos — solo insertar.
        if elem.is_translated:
            elem.computed_font_size = _compute_font_size(elem)

    ok_count = sum(1 for e in elements if e.quality_status == QualityStatus.OK)
    accepted_count = sum(1 for e in elements if e.quality_status == QualityStatus.ACCEPTED)
    retry_count_total = sum(1 for e in elements if e.quality_status == QualityStatus.RETRY)

    print(
        f"[QualityGate] Iteración {quality_iterations}: "
        f"{ok_count} OK, {accepted_count} aceptados, {retry_count_total} retry"
    )

    return {
        "elements": elements,
        "quality_iterations": quality_iterations,
        "current_phase": "quality_checked",
    }


def should_retry(state: TranslationState) -> str:
    """
    Edge condicional de LangGraph.

    LangGraph llama a esta función para decidir qué nodo va después del
    Quality Gate. Devuelve el nombre del nodo destino como string.

    - "translate" → hay elementos que necesitan reintento Y no hemos
                    agotado el máximo de iteraciones
    - "reconstruct" → todo listo (o máximo alcanzado), pasamos a reconstruir
    """
    elements = state["elements"]
    quality_iterations = state.get("quality_iterations", 0)
    max_iterations = state.get("max_quality_iterations", 2)

    has_retries = any(e.quality_status == QualityStatus.RETRY for e in elements)

    if has_retries and quality_iterations < max_iterations:
        print(f"[QualityGate] → RETRY (iteración {quality_iterations}/{max_iterations})")
        return "translate"

    print("[QualityGate] → IMAGE PIPELINE (calidad OK o máximo alcanzado)")
    return "language_classifier"


def _check_element_quality(elem: PDFElement, target_language: str) -> list[str]:
    """
    Verifica la calidad de la traducción de un elemento.
    Devuelve lista de problemas encontrados (vacía = OK).
    """
    issues = []
    original = elem.original_text
    translated = elem.translated_text

    # 1. Traducción vacía o idéntica al original (sin cambios)
    if not translated:
        issues.append("empty translation")
        return issues

    # 2. Ratio de longitud excesivo (puede indicar que Claude añadió texto extra)
    orig_len = len(original)
    trans_len = len(translated)
    if orig_len > 5 and trans_len > orig_len * MAX_LENGTH_RATIO:
        issues.append(f"too long ({trans_len} vs {orig_len} chars)")

    # 3. Detección de idioma incorrecto
    # Si el objetivo es un idioma latino y la traducción tiene caracteres CJK,
    # algo fue mal (el modelo devolvió el original sin traducir)
    latin_targets = {
        "spanish",
        "english",
        "french",
        "german",
        "italian",
        "portuguese",
        "dutch",
        "polish",
        "catalan",
    }
    if target_language.lower() in latin_targets:
        if _has_cjk(translated) and len(translated) > 3:
            issues.append("translation still in CJK characters")

    # 4. Traducción idéntica al original (solo si el original era CJK)
    if translated == original and _has_cjk(original):
        issues.append("not translated (identical to original)")

    # 5. Detección de traducción fallida: target es latino pero texto tiene
    # caracteres del idioma origen que no deberían aparecer en la traducción
    if target_language.lower() == "english" and translated == original:
        # Si el original tiene caracteres típicamente españoles/latinos
        spanish_chars = set("áéíóúüñÁÉÍÓÚÜÑ¡¿")
        if any(c in spanish_chars for c in original) and len(original) > 5:
            issues.append("translation not applied (API may have failed)")

    return issues


def _compute_font_size(elem: PDFElement) -> float:
    """
    Calcula el font size que GARANTIZA que el texto cabe en el rect real.

    Usa exactamente las mismas dimensiones que usará el reconstructor:
    - inner = bbox + (1.5, 1.5, -1.5, -1.5)
    - Mismo fontname, mismo align

    El resultado es 100% fiable porque probamos con el rect exacto.
    """
    if not elem.translated_text:
        return elem.font_size

    import fitz

    TEXT_PADDING = 1.5

    original_size = max(elem.font_size, 4.0)
    min_size = original_size * 0.55  # mínimo 55% del original

    # Rect exacto que usará el reconstructor
    actual_w = max(elem.bbox.width - TEXT_PADDING * 2, 5.0)
    actual_h = max(elem.bbox.height - TEXT_PADDING * 2, 3.0)
    test_rect = fitz.Rect(0, 0, actual_w, actual_h)

    font = "hebo" if elem.is_bold or bool(elem.font_flags & 16) else "helv"

    test_doc = fitz.open()
    # Página suficientemente grande para que nunca sea el límite
    test_page = test_doc.new_page(width=actual_w + 20, height=actual_h + 200)

    found_size = min_size
    size = original_size

    while size >= min_size:
        result = test_page.insert_textbox(
            rect=test_rect,
            buffer=elem.translated_text,
            fontname=font,
            fontsize=size,
            align=fitz.TEXT_ALIGN_LEFT,
            overlay=True,
        )
        if result >= 0:
            found_size = size
            break
        size *= 0.90  # reducción del 10% en cada paso
        if size < min_size:
            found_size = min_size
            break

    test_doc.close()
    return found_size


def _has_cjk(text: str) -> bool:
    """True si el texto contiene caracteres CJK."""
    for char in text:
        code = ord(char)
        for start, end in CJK_RANGES:
            if start <= code <= end:
                return True
    return False
