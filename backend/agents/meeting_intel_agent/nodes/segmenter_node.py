"""
segmenter_node.py — Nodo 2 del Meeting Intelligence Agent

Responsabilidad: dividir la transcripción en segmentos temáticos.

Por qué segmentamos:
1. Context window — 15.000 palabras no caben bien en una sola llamada a Claude
2. Precisión — Claude es más preciso con textos cortos y focalizados
3. RAG — los segmentos son los chunks que indexamos en pgvector

El segmentador usa dos estrategias:
- Segmentación por tamaño: chunks de ~600 palabras con overlap de 50 palabras
- Segmentación semántica simple: detecta cambios de tema por pausas largas y palabras clave

Para reuniones cortas (<1000 palabras) devuelve un solo segmento.
"""

from __future__ import annotations

from ..state import MeetingState

# Tamaño objetivo de cada segmento en palabras
SEGMENT_TARGET_WORDS = 600
SEGMENT_OVERLAP_WORDS = 50
MIN_SEGMENT_WORDS = 100  # segmentos más cortos se fusionan con el anterior


def segmenter_node(state: MeetingState) -> dict:
    """
    Nodo 2: divide la transcripción en segmentos temáticos.

    Returns:
        dict con:
        - segments: lista de segmentos con texto y metadata
    """
    print("[SegmenterNode] Iniciando...")

    if state.get("error"):
        return {}

    transcription = state.get("transcription")
    if not transcription:
        return {"error": "No transcription available for segmentation"}

    # Reuniones muy cortas — un solo segmento
    words = transcription.split()
    if len(words) <= SEGMENT_TARGET_WORDS:
        print(f"[SegmenterNode] Transcripción corta ({len(words)} palabras) — 1 segmento")
        return {
            "segments": [
                {
                    "index": 0,
                    "text": transcription,
                    "word_count": len(words),
                    "start_word": 0,
                    "end_word": len(words),
                }
            ]
        }

    # Segmentación por tamaño con overlap
    segments = _segment_by_size(words)
    print(f"[SegmenterNode] {len(words)} palabras divididas en {len(segments)} segmentos")

    return {"segments": segments}


def _segment_by_size(words: list[str]) -> list[dict]:
    """
    Divide la lista de palabras en segmentos de tamaño fijo con overlap.

    El overlap garantiza que las frases que caen en el borde entre
    dos segmentos estén completas en al menos uno de los dos.
    Mismo principio que el chunking del Document Intelligence Agent.
    """
    segments = []
    start = 0
    index = 0

    while start < len(words):
        end = min(start + SEGMENT_TARGET_WORDS, len(words))
        segment_words = words[start:end]

        # Si el segmento es demasiado corto, lo fusionamos con el anterior
        if len(segment_words) < MIN_SEGMENT_WORDS and segments:
            prev = segments[-1]
            prev["text"] = prev["text"] + " " + " ".join(segment_words)
            prev["end_word"] = end
            prev["word_count"] = prev["end_word"] - prev["start_word"]
            break

        segments.append(
            {
                "index": index,
                "text": " ".join(segment_words),
                "word_count": len(segment_words),
                "start_word": start,
                "end_word": end,
            }
        )

        # El siguiente segmento empieza SEGMENT_OVERLAP_WORDS antes del final
        # del segmento actual — así hay overlap entre segmentos
        start = end - SEGMENT_OVERLAP_WORDS
        index += 1

    return segments
