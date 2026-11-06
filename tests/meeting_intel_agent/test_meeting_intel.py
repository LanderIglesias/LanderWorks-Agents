import pytest

from backend.agents.meeting_intel_agent.nodes.extractor_node import _deduplicate
from backend.agents.meeting_intel_agent.nodes.report_generator_node import (
    _build_markdown,
    _format_duration,
)
from backend.agents.meeting_intel_agent.nodes.segmenter_node import (
    MIN_SEGMENT_WORDS,
    SEGMENT_OVERLAP_WORDS,
    SEGMENT_TARGET_WORDS,
    _segment_by_size,
)

PALABRAS = [f"w{i}" for i in range(SEGMENT_TARGET_WORDS * 3)]


# ── Segmentacion ─────────────────────────────────────────────────────────────


def test_segmentos_consecutivos_se_solapan():
    primero, segundo = _segment_by_size(PALABRAS)[:2]
    assert (
        primero["text"].split()[-SEGMENT_OVERLAP_WORDS:]
        == segundo["text"].split()[:SEGMENT_OVERLAP_WORDS]
    )


def test_cubre_toda_la_transcripcion_hasta_el_final():
    segmentos = _segment_by_size(PALABRAS)
    assert segmentos[0]["start_word"] == 0
    assert segmentos[-1]["end_word"] == len(PALABRAS)


@pytest.mark.parametrize(
    "extra", [-49, -10, 0, 1, 40, MIN_SEGMENT_WORDS - 1, MIN_SEGMENT_WORDS + 50]
)
def test_ninguna_palabra_se_repite_dentro_de_un_segmento(extra):
    """Solo se solapan segmentos distintos: dentro de uno, cada palabra sale una vez."""
    palabras = [f"w{i}" for i in range(SEGMENT_TARGET_WORDS * 2 + extra)]
    segmentos = _segment_by_size(palabras)
    assert segmentos[-1]["end_word"] == len(palabras)
    for segmento in segmentos:
        texto = segmento["text"].split()
        assert len(texto) == len(set(texto))
        assert segmento["word_count"] == len(texto)


# ── Deduplicacion ────────────────────────────────────────────────────────────


def test_deduplicate_ignora_mayusculas_y_espacios():
    items = [{"text": "Lanzar el lunes"}, {"text": "  lanzar EL lunes "}, {"text": "Otra"}]
    assert _deduplicate(items, "text") == [items[0], items[2]]


def test_deduplicate_descarta_vacios():
    assert _deduplicate([{"text": "   "}, {}], "text") == []


def test_deduplicate_tolera_null_del_llm():
    """El LLM puede devolver null en un campo: se descarta sin romper el pipeline."""
    assert _deduplicate([{"task": None}, {"task": "Enviar acta"}], "task") == [
        {"task": "Enviar acta"}
    ]


# ── Informe ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("segundos", "esperado"),
    [(0, "0s"), (59.9, "59s"), (60, "1m 0s"), (3599, "59m 59s"), (5025, "1h 23m 45s")],
)
def test_format_duration(segundos, esperado):
    assert _format_duration(segundos) == esperado


def _informe(**campos) -> str:
    base = {
        "title": "Reunion",
        "timestamp": "2026-01-01",
        "duration_str": "1m 0s",
        "language": "es",
        "executive_summary": "Resumen",
        "key_topics": [],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
        "pending_topics": [],
        "meeting_id": "abc",
        "chunks_indexed": 0,
    }
    return _build_markdown(**(base | campos))


def test_informe_tolera_prioridad_null_del_llm():
    informe = _informe(action_items=[{"task": "Enviar acta", "owner": "Ana", "priority": None}])
    assert "⚪" in informe


def test_informe_sin_decisiones_lo_indica():
    assert "_No decisions recorded._" in _informe()


def test_informe_incluye_decision_y_prioridad_del_action_item():
    informe = _informe(
        decisions=[{"text": "Lanzar el lunes", "context": "Acordado"}],
        action_items=[{"task": "Enviar acta", "owner": "Ana", "priority": "high"}],
    )
    assert "**Lanzar el lunes**" in informe
    assert "Enviar acta" in informe
    assert "🔴" in informe
