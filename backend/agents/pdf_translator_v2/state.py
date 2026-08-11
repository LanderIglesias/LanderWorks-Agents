"""
state.py — Estado compartido del grafo LangGraph

En LangGraph, el 'State' es el objeto que viaja entre todos los nodos.
Cada nodo recibe el estado completo, hace su trabajo, y devuelve
los campos que modifica. LangGraph mergea esos cambios automáticamente.

¿Por qué TypedDict?
LangGraph requiere que el estado sea un TypedDict (no una dataclass ni
un Pydantic model) para poder gestionar el merge entre nodos correctamente.
Cada campo tiene un 'reducer' implícito — por defecto, el valor nuevo
reemplaza al anterior.

El estado representa el "conocimiento acumulado" del pipeline sobre el PDF:
empieza vacío y se va enriqueciendo nodo a nodo hasta que el PDF está listo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, TypedDict

# ── Enums de clasificación ─────────────────────────────────────────────────


class ElementType(str, Enum):
    NATIVE_TEXT = "native_text"
    IMAGE_TEXT = "image_text"
    IMAGE_ONLY = "image_only"


class QualityStatus(str, Enum):
    PENDING = "pending"
    OK = "ok"
    RETRY = "retry"
    ACCEPTED = "accepted"
    SKIPPED = "skipped"


class LanguageScript(str, Enum):
    LATIN = "latin"
    ASIAN = "asian"
    CYRILLIC = "cyrillic"
    ARABIC = "arabic"
    UNKNOWN = "unknown"


class ImageStrategy(str, Enum):
    FULL_STYLE = "full_style"  # mismo tamaño, mismo color
    REDUCED_SIZE = "reduced_size"  # font reducido pero mismo estilo
    BEST_EFFORT = "best_effort"  # lo mejor posible
    SKIP = "skip"  # no tocar


# ── Modelos de datos de elementos ─────────────────────────────────────────


@dataclass
class BBox:
    """Bounding box en puntos PDF (x0, y0, x1, y1)."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    def to_rect(self):
        """Convierte a fitz.Rect para PyMuPDF."""
        import fitz

        return fitz.Rect(self.x0, self.y0, self.x1, self.y1)


@dataclass
class PDFElement:
    """
    Representa un elemento del PDF — puede ser texto o imagen.

    Este es el objeto central del pipeline. El Analyzer crea un PDFElement
    por cada bloque de contenido relevante del PDF. Los nodos posteriores
    van rellenando los campos: original_text → translated_text → quality_status.

    Campos clave:
    - element_type: qué tipo de elemento es (lo decide el Analyzer)
    - original_text: el texto original (texto nativo o detectado por Vision)
    - translated_text: la traducción (la rellena el nodo traductor)
    - font_size: tamaño de fuente en puntos (lo calcula el Text Translator)
    - bg_color: color de fondo en hex (para elementos de imagen)
    - text_color: color del texto en hex
    - quality_status: si ha pasado el quality gate
    - retry_count: cuántas veces se ha reintentado
    - skip_reason: por qué se saltó (si se saltó)
    """

    # Identificación
    element_id: str  # único: "p{page}_b{block}" o "p{page}_img{idx}"
    page_num: int  # página (0-indexed)
    element_type: ElementType

    # Posición y geometría
    bbox: BBox
    page_width: float
    page_height: float

    # Contenido de texto
    original_text: str = ""
    translated_text: str = ""

    # Estilo
    font_size: float = 0.0
    font_flags: int = 0  # bold=16, italic=2 (flags de PyMuPDF)
    text_color: int = 0  # color empaquetado como int (formato PyMuPDF)
    bg_color: str = "#ffffff"
    is_bold: bool = False

    # Para imágenes (Vision agent)
    image_bytes: bytes | None = None
    image_xref: int = 0
    text_color_hex: str = "#000000"  # color hex detectado por Vision
    bg_color_hex: str = "#ffffff"  # alias para bg_color
    bg_is_solid: bool = True  # True si el fondo es color sólido

    # Clasificación y estrategia de imagen
    language_script: LanguageScript = LanguageScript.UNKNOWN
    image_strategy: ImageStrategy = ImageStrategy.SKIP

    # Estado del pipeline
    quality_status: QualityStatus = QualityStatus.PENDING
    retry_count: int = 0
    skip_reason: str = ""
    computed_font_size: float = 0.0

    @property
    def needs_translation(self) -> bool:
        return self.element_type != ElementType.IMAGE_ONLY and bool(self.original_text.strip())

    @property
    def is_translated(self) -> bool:
        return bool(self.translated_text.strip())


# ── Estado principal del grafo ─────────────────────────────────────────────


class TranslationState(TypedDict):
    """
    Estado compartido que fluye a través de todos los nodos del grafo.

    LangGraph gestiona este dict automáticamente:
    - Lo pasa completo a cada nodo
    - Mergea los cambios que devuelve cada nodo
    - Mantiene el historial si se configura checkpointing

    Campos:
    - input_pdf_path: ruta al PDF original
    - output_pdf_path: ruta donde guardar el resultado
    - target_language: idioma destino ("spanish", "french", etc.)
    - source_language: idioma origen ("auto" para detección automática)
    - elements: lista de todos los elementos del PDF (rellena el Analyzer)
    - pages_info: metadatos de cada página (dimensiones, etc.)
    - current_phase: qué fase del pipeline está activa (para logging/UI)
    - quality_iterations: cuántas veces ha pasado por el quality gate
    - max_quality_iterations: límite de reintentos del quality gate
    - errors: errores no fatales acumulados durante el pipeline
    - stats: estadísticas finales para mostrar en la UI
    """

    # Input
    input_pdf_path: str
    output_pdf_path: str
    target_language: str
    source_language: str

    # Elementos del PDF
    elements: list[PDFElement]
    pages_info: list[dict[str, Any]]
    page_images: dict[int, bytes]  # page_num → JPEG renderizado (para image patcher)

    # Control del flujo
    current_phase: str
    quality_iterations: int
    max_quality_iterations: int

    # Resultados
    errors: list[str]
    stats: dict[str, Any]
