"""
translator_node.py — Nodo 2: Traductor inteligente por lotes

Este nodo recibe todos los PDFElement del Analyzer y los traduce.
Gestiona dos tipos de elementos de forma diferente:

TEXTO NATIVO (NATIVE_TEXT):
- Agrupamos en lotes de 40 y enviamos a Claude Haiku (rápido, barato)
- El contexto del lote ayuda: Claude sabe que "型号" en un catálogo = "Model"
- Preservamos colores, números de referencia, URLs, etc.

TEXTO DE IMAGEN (IMAGE_TEXT):
- Mismo sistema de lotes, mismo modelo
- El prompt indica que son textos de cabeceras/banners
- Generalmente son textos más cortos y formales

¿Por qué Haiku para traducción y Sonnet para Vision?
→ Haiku es 6x más barato y 3x más rápido que Sonnet para texto puro
→ Sonnet se justifica solo para Vision (precisión de coordenadas)
→ Para un PDF de 8 páginas: Haiku traduce 200 bloques en ~15s
   Sonnet haría lo mismo en ~45s y costaría 6x más

Prefill de asistente:
Añadimos {"role": "assistant", "content": "{"} para forzar JSON puro.
Sin este truco, los modelos añaden texto introductorio antes del JSON.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import anthropic
from dotenv import load_dotenv

from .state import ElementType, PDFElement, TranslationState

load_dotenv()

BATCH_SIZE = 40  # bloques por llamada a la API


def translator_node(state: TranslationState) -> dict[str, Any]:
    """
    Nodo LangGraph: traduce todos los elementos que necesitan traducción.

    Filtra los elementos que ya tienen translated_text (para no re-traducir
    en reintentos del quality gate) y traduce el resto en lotes.
    """
    elements = state["elements"]
    target_language = state["target_language"]
    source_language = state.get("source_language", "auto")

    # Separamos por tipo para usar el prompt más adecuado
    to_translate = [e for e in elements if e.needs_translation and not e.is_translated]

    if not to_translate:
        print("[Translator] Nada que traducir (ya traducido o sin texto)")
        return {"elements": elements, "current_phase": "translated"}

    print(f"[Translator] Traduciendo {len(to_translate)} elementos al {target_language}...")

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Creamos un índice para actualizar los elementos por element_id
    elements_by_id = {e.element_id: e for e in elements}

    # Traducimos en lotes
    for batch_start in range(0, len(to_translate), BATCH_SIZE):
        batch = to_translate[batch_start : batch_start + BATCH_SIZE]

        print(f"[Translator] Lote {batch_start // BATCH_SIZE + 1}: " f"{len(batch)} elementos")

        batch_dict = {str(i): elem.original_text for i, elem in enumerate(batch)}
        context_hint = _get_context_hint(batch)

        translated_dict = _call_claude_translate(
            client=client,
            batch_dict=batch_dict,
            target_language=target_language,
            source_hint=source_language,
            context_hint=context_hint,
        )

        # Aplicamos las traducciones
        for i, elem in enumerate(batch):
            translation = translated_dict.get(str(i), "").strip()
            if translation:
                elements_by_id[elem.element_id].translated_text = translation
            else:
                # Fallback: usamos el texto original
                elements_by_id[elem.element_id].translated_text = elem.original_text

    translated_count = sum(1 for e in elements if e.is_translated)
    print(f"[Translator] {translated_count} elementos traducidos")

    return {
        "elements": list(elements_by_id.values()),
        "current_phase": "translated",
    }


def _get_context_hint(batch: list[PDFElement]) -> str:
    """
    Genera una pista de contexto basada en los tipos de elementos del lote.
    Ayuda al modelo a traducir con el registro correcto.
    """
    has_image_text = any(e.element_type == ElementType.IMAGE_TEXT for e in batch)
    has_native = any(e.element_type == ElementType.NATIVE_TEXT for e in batch)

    if has_image_text and not has_native:
        return "These are section headers and banner texts from a product catalog."
    elif has_native:
        return "These are product descriptions, specifications, and catalog content."
    return "Product catalog content."


def _call_claude_translate(
    client: anthropic.Anthropic,
    batch_dict: dict[str, str],
    target_language: str,
    source_hint: str,
    context_hint: str,
) -> dict[str, str]:
    """
    Llama a Claude Haiku para traducir un lote de textos.

    Envía {índice: texto} y recibe {índice: traducción}.
    Usa prefill de asistente para garantizar JSON puro.
    """
    source_info = (
        f"Source language: {source_hint}."
        if source_hint != "auto"
        else "Auto-detect the source language."
    )

    system_prompt = f"""You are a professional translator specializing in product catalogs and technical documents.
Translate texts to: {target_language.upper()}

RULES:
1. Return ONLY a valid JSON object. No text before or after.
2. Keep the exact same numeric keys from the input.
3. {source_info}
4. Context: {context_hint}
5. Do NOT translate: brand names, product reference codes (like JG-LOCK-X9, OBYP4-L0.5-101), URLs, emails, phone numbers.
6. If text is already in {target_language}, return it unchanged.
7. Preserve the tone and register (formal for technical content, descriptive for marketing).
8. Keep punctuation style consistent with the original.

Input: {{"0": "text0", "1": "text1"}}
Output: {{"0": "translated0", "1": "translated1"}}"""

    user_msg = f"Translate to {target_language}:\n\n{json.dumps(batch_dict, ensure_ascii=False)}"

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": "{"},  # prefill → JSON garantizado
            ],
        )

        raw = "{" + response.content[0].text.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Extracción de emergencia
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    pass
            print("[Translator] Warning: no se pudo parsear JSON. Usando originales.")
            return {k: v for k, v in batch_dict.items()}

    except Exception as e:
        print(f"[Translator] Error API: {e}")
        return {k: v for k, v in batch_dict.items()}
