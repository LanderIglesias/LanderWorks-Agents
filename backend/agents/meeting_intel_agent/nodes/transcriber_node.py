"""
transcriber_node.py — Nodo 1 del Meeting Intelligence Agent

Responsabilidad: recibir audio o texto y devolver la transcripción completa.

Dos caminos posibles:
- Si hay audio_path → transcribe con faster-whisper
- Si hay raw_text → lo usa directamente sin transcribir

Esto permite que el agente funcione tanto con grabaciones de audio
como con transcripciones ya existentes (Otter.ai, Teams, Zoom, etc.)
"""

from __future__ import annotations

from ..state import MeetingState
from ..transcription.whisper_transcriber import get_transcriber


def transcriber_node(state: MeetingState) -> dict:
    """
    Nodo 1: transcribe el audio o valida el texto directo.

    Args:
        state: estado actual del grafo

    Returns:
        dict con los campos actualizados del estado:
        - transcription: texto completo
        - transcription_language: idioma detectado
        - audio_duration_seconds: duración del audio (None si es texto)
    """
    print("[TranscriberNode] Iniciando...")

    # Si ya hay un error previo, saltamos este nodo
    if state.get("error"):
        return {}

    audio_path = state.get("audio_path")
    raw_text = state.get("raw_text")

    # ── Camino 1: texto directo ───────────────────────────────────────────────
    if raw_text:
        print(f"[TranscriberNode] Usando texto directo ({len(raw_text)} caracteres)")
        return {
            "transcription": raw_text.strip(),
            "transcription_language": state.get("language", "es"),
            "audio_duration_seconds": None,
        }

    # ── Camino 2: audio ───────────────────────────────────────────────────────
    if audio_path:
        print(f"[TranscriberNode] Transcribiendo audio: {audio_path}")
        try:
            transcriber = get_transcriber()
            result = transcriber.transcribe(
                audio_path=audio_path,
                language=state.get("language", "auto"),
            )

            print(
                f"[TranscriberNode] Transcripción completada. "
                f"Idioma: {result['language']}, "
                f"Duración: {result['duration_seconds']:.1f}s, "
                f"Caracteres: {len(result['text'])}"
            )

            return {
                "transcription": result["text"],
                "transcription_language": result["language"],
                "audio_duration_seconds": result["duration_seconds"],
            }

        except FileNotFoundError as e:
            return {"error": f"Audio file not found: {e}"}
        except ValueError as e:
            return {"error": f"Invalid audio format: {e}"}
        except Exception as e:
            return {"error": f"Transcription failed: {e}"}

    # ── Ninguna entrada ───────────────────────────────────────────────────────
    return {"error": "No audio file or text provided. Please provide audio_path or raw_text."}
