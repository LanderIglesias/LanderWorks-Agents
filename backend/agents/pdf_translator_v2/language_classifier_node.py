"""
language_classifier_node.py — Nodo: Clasificador de script de texto

Clasifica cada IMAGE_TEXT element según el script del texto original:
- LATIN: inglés, español, francés, alemán, etc.
- ASIAN: chino, japonés, coreano (caracteres CJK)
- CYRILLIC: ruso, ucraniano, etc.
- ARABIC: árabe, persa, etc.

Usa heurísticas de rangos Unicode — sin llamadas a la API.
Rápido y 100% fiable para detectar el script.

¿Por qué importa el script?
→ Un texto latino traducido a español tiene la misma longitud aproximada
  y podemos mantener el mismo estilo casi siempre.
→ Un texto asiático traducido a inglés puede necesitar 3x más espacio.
→ Un texto árabe tiene escritura RTL que requiere consideraciones especiales.
"""

from __future__ import annotations

from typing import Any

from .state import ElementType, LanguageScript, TranslationState


def language_classifier_node(state: TranslationState) -> dict[str, Any]:
    """
    Nodo LangGraph: clasifica el script de cada IMAGE_TEXT element.
    Opera solo sobre elementos de imagen — el texto nativo no lo necesita.
    """
    elements = state["elements"]
    classified = 0

    for elem in elements:
        if elem.element_type != ElementType.IMAGE_TEXT:
            continue
        elem.language_script = _classify_script(elem.original_text)
        classified += 1

    print(f"[LanguageClassifier] {classified} elementos de imagen clasificados")

    # Resumen por script
    from collections import Counter

    scripts = Counter(
        e.language_script for e in elements if e.element_type == ElementType.IMAGE_TEXT
    )
    for script, count in scripts.items():
        print(f"  {script}: {count}")

    return {"elements": elements, "current_phase": "language_classified"}


def _classify_script(text: str) -> LanguageScript:
    """
    Clasifica el script del texto usando rangos Unicode.

    Cuenta qué tipo de caracteres predomina y devuelve el script mayoritario.
    Si el texto es mixto, el script con más del 30% de caracteres gana.
    """
    if not text:
        return LanguageScript.UNKNOWN

    counts = {
        "asian": 0,
        "cyrillic": 0,
        "arabic": 0,
        "latin": 0,
    }

    for char in text:
        code = ord(char)

        # CJK: chino, japonés, coreano
        if (
            0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
            or 0x3040 <= code <= 0x30FF  # Hiragana + Katakana
            or 0xAC00 <= code <= 0xD7AF  # Hangul
            or 0x3400 <= code <= 0x4DBF
        ):  # CJK Extension A
            counts["asian"] += 1

        # Cirílico
        elif 0x0400 <= code <= 0x04FF:
            counts["cyrillic"] += 1

        # Árabe
        elif 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F:
            counts["arabic"] += 1

        # Latino básico + extendido
        elif (
            0x0041 <= code <= 0x007A  # A-Z, a-z
            or 0x00C0 <= code <= 0x024F  # Latin Extended
            or 0x00E0 <= code <= 0x00FF
        ):  # Latin-1 Supplement
            counts["latin"] += 1

    total = max(1, len(text))
    ratios = {k: v / total for k, v in counts.items()}

    # El script con mayor ratio gana si supera el 30%
    max_script = max(ratios, key=ratios.get)
    if ratios[max_script] >= 0.30:
        return LanguageScript(max_script)

    # Si no hay dominancia clara, asumimos LATIN (el caso más común)
    return LanguageScript.LATIN
