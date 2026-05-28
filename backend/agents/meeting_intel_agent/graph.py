"""
graph.py — Orquestador LangGraph del Meeting Intelligence Agent

Pipeline:
transcriber → segmenter → extractor → indexer → synthesizer → report_generator → END
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes.extractor_node import extractor_node
from .nodes.indexer_node import indexer_node
from .nodes.report_generator_node import report_generator_node
from .nodes.segmenter_node import segmenter_node
from .nodes.synthesizer_node import synthesizer_node
from .nodes.transcriber_node import transcriber_node
from .state import MeetingState


def build_graph():
    """Construye y compila el grafo LangGraph."""
    graph = StateGraph(MeetingState)

    graph.add_node("transcriber", transcriber_node)
    graph.add_node("segmenter", segmenter_node)
    graph.add_node("extractor", extractor_node)
    graph.add_node("indexer", indexer_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("report_generator", report_generator_node)

    graph.set_entry_point("transcriber")
    graph.add_edge("transcriber", "segmenter")
    graph.add_edge("segmenter", "extractor")
    graph.add_edge("extractor", "indexer")
    graph.add_edge("indexer", "synthesizer")
    graph.add_edge("synthesizer", "report_generator")
    graph.add_edge("report_generator", END)

    return graph.compile()


# Compilamos una sola vez al importar el módulo
app_graph = build_graph()


def analyze_meeting(
    audio_path: str | None = None,
    raw_text: str | None = None,
    meeting_title: str = "Untitled Meeting",
    language: str = "auto",
) -> dict:
    """
    Función principal — ejecuta el pipeline completo de análisis.

    Args:
        audio_path: ruta al archivo de audio (MP3, WAV, etc.)
        raw_text: texto directo si no hay audio
        meeting_title: título de la reunión
        language: idioma del audio ("auto", "es", "en", etc.)

    Returns:
        El report_json completo o {"error": "mensaje"} si algo falla
    """
    if not audio_path and not raw_text:
        return {"error": "Provide audio_path or raw_text"}

    initial_state: MeetingState = {
        "audio_path": audio_path,
        "raw_text": raw_text,
        "meeting_title": meeting_title,
        "language": language,
        "transcription": None,
        "transcription_language": None,
        "audio_duration_seconds": None,
        "segments": None,
        "decisions": None,
        "action_items": None,
        "open_questions": None,
        "pending_topics": None,
        "meeting_id": None,
        "chunks_indexed": None,
        "executive_summary": None,
        "key_topics": None,
        "report_markdown": None,
        "report_json": None,
        "error": None,
    }

    try:
        final_state = app_graph.invoke(initial_state)

        if final_state.get("error"):
            return {"error": final_state["error"]}

        return final_state.get("report_json", {"error": "No report generated"})

    except Exception as e:
        return {"error": str(e)}
