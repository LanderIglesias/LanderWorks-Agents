"""
whisper_transcriber.py — Transcripción de audio con faster-whisper

Responsabilidad: recibir un archivo de audio y devolver el texto
completo de la transcripción junto con el idioma detectado y la duración.

faster-whisper es una implementación optimizada del modelo Whisper de OpenAI.
Es 4x más rápido que openai-whisper y usa menos memoria porque usa
CTranslate2 como backend en vez de PyTorch directamente.

pydub se usa para preprocesar el audio antes de la transcripción:
- convertir formatos (MP3, M4A → WAV)
- detectar la duración del archivo
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from faster_whisper import WhisperModel
from pydub import AudioSegment

# ── Configuración del modelo ──────────────────────────────────────────────────
# "base" es el modelo más pequeño que da buena calidad para reuniones.
# Opciones por tamaño y calidad: tiny < base < small < medium < large-v3
# Para producción con recursos limitados: "base" o "small"
# Para máxima calidad: "large-v3"
MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")

# "cpu" para máquina sin GPU. "cuda" si tienes GPU NVIDIA.
# compute_type="int8" reduce el uso de memoria sin perder mucha calidad
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = "int8"

# Formatos de audio soportados
SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm"}


class WhisperTranscriber:
    """
    Transcriptor de audio usando faster-whisper.

    El modelo se carga una sola vez al instanciar la clase
    y se reutiliza en todas las transcripciones.
    Cargar el modelo es costoso (varios segundos) — no lo hagas en cada petición.
    """

    def __init__(self):
        print(f"[Whisper] Cargando modelo {MODEL_SIZE} en {DEVICE}...")
        self.model = WhisperModel(
            MODEL_SIZE,
            device=DEVICE,
            compute_type=COMPUTE_TYPE,
        )
        print("[Whisper] Modelo cargado.")

    def transcribe(self, audio_path: str, language: str = "auto") -> dict:
        """
        Transcribe un archivo de audio a texto.

        Args:
            audio_path: ruta al archivo de audio
            language: "auto" para detección automática, "es" para español,
                     "en" para inglés, etc.

        Returns:
            {
                "text": str,           # transcripción completa
                "language": str,       # idioma detectado ("es", "en", etc.)
                "duration_seconds": float,  # duración del audio
            }

        Raises:
            ValueError: si el formato de audio no es soportado
            FileNotFoundError: si el archivo no existe
        """
        path = Path(audio_path)

        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if path.suffix.lower() not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported audio format: {path.suffix}. Supported: {SUPPORTED_FORMATS}"
            )

        # Obtenemos la duración con pydub antes de transcribir
        duration = self._get_duration(audio_path)

        # Si el audio no es WAV, lo convertimos a WAV temporalmente
        # faster-whisper funciona mejor con WAV que con MP3
        if path.suffix.lower() != ".wav":
            audio_path = self._convert_to_wav(audio_path)
            converted = True
        else:
            converted = False

        try:
            # language=None hace detección automática
            lang_param = None if language == "auto" else language

            # segments es un generador — faster-whisper va procesando el audio
            # en bloques y devuelve segmentos de texto uno a uno
            segments, info = self.model.transcribe(
                audio_path,
                language=lang_param,
                beam_size=5,  # más alto = más preciso pero más lento
                vad_filter=True,  # Voice Activity Detection: ignora silencios
                vad_parameters=dict(min_silence_duration_ms=500),
            )

            # Concatenamos todos los segmentos en un texto completo
            # Cada segmento tiene .text con el texto transcrito
            full_text = " ".join(segment.text.strip() for segment in segments)

            return {
                "text": full_text.strip(),
                "language": info.language,
                "duration_seconds": duration,
            }

        finally:
            # Si convertimos el archivo, borramos el WAV temporal
            if converted and os.path.exists(audio_path):
                os.remove(audio_path)

    def _get_duration(self, audio_path: str) -> float:
        """Obtiene la duración del audio en segundos usando pydub."""
        try:
            audio = AudioSegment.from_file(audio_path)
            # pydub trabaja en milisegundos — convertimos a segundos
            return len(audio) / 1000.0
        except Exception:
            return 0.0

    def _convert_to_wav(self, audio_path: str) -> str:
        """
        Convierte el audio a WAV en una carpeta temporal.
        Devuelve la ruta del archivo WAV temporal.
        """
        audio = AudioSegment.from_file(audio_path)

        # Creamos un archivo temporal con extensión .wav
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="meeting_intel_")
        tmp.close()

        # Exportamos a WAV con configuración estándar para Whisper
        audio.export(tmp.name, format="wav", parameters=["-ar", "16000", "-ac", "1"])  # 16kHz mono

        return tmp.name


# ── Singleton — instancia compartida ─────────────────────────────────────────
# El modelo se carga una sola vez al importar el módulo
# No creamos una nueva instancia en cada petición
_transcriber: WhisperTranscriber | None = None


def get_transcriber() -> WhisperTranscriber:
    """
    Devuelve la instancia compartida del transcriber.
    La crea si no existe todavía (lazy initialization).
    """
    global _transcriber
    if _transcriber is None:
        _transcriber = WhisperTranscriber()
    return _transcriber
