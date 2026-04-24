"""
engine.py — Orquestador del BI Agent (Fase 3 con visualizaciones).

Cambio: después de invocar el grafo, si el resultado es visualizable
generamos una gráfica matplotlib y la añadimos al resultado como base64.
"""

from __future__ import annotations

import logging

from .data_loader import get_session
from .graph import compiled_graph
from .sqlite_store import create_sqlite_from_dataframe
from .state import create_initial_state
from .visualizer import generate_chart, should_visualize

logger = logging.getLogger(__name__)

_SQLITE_CACHE: dict[str, str] = {}


def answer_question(session_id: str, question: str) -> dict:
    """
    Responde una pregunta usando el grafo LangGraph.
    Añade una gráfica al resultado si el tipo de datos lo permite.
    """
    session = get_session(session_id)
    df = session["df"]
    schema = session["schema"]

    sqlite_path = _ensure_sqlite(session_id, df)

    initial_state = create_initial_state(
        session_id=session_id,
        question=question,
        schema=schema,
        sqlite_path=sqlite_path,
        table_name="data",
        max_retries=2,
    )

    logger.info(f"[Engine] Invoking graph for: {question[:80]}...")

    try:
        final_state = compiled_graph.invoke(initial_state)
    except Exception as e:
        logger.exception("[Engine] Graph execution failed")
        return {
            "success": False,
            "answer": f"The agent failed to process your question: {e}",
            "code": None,
            "result": None,
            "result_type": None,
            "error": str(e),
            "chart": None,
            "trace": [],
            "subtasks": [],
            "anomalies": [],
        }

    logger.info(f"[Engine] Graph trace: {final_state.get('trace', [])}")

    # Extraemos código y tipo de la última subtarea exitosa
    last_code = None
    last_result_type = None
    if final_state.get("subtasks"):
        for st in reversed(final_state["subtasks"]):
            if not st["error"] and st["code"]:
                last_code = st["code"]
                last_result_type = st["result_type"]
                break
        if last_code is None and final_state["subtasks"]:
            last_code = final_state["subtasks"][-1]["code"]

    any_success = any(not st["error"] for st in final_state.get("subtasks", []))
    success = final_state.get("final_answer") is not None and any_success

    final_result = final_state.get("final_result")

    # Generamos la gráfica si el resultado lo merece
    chart_b64 = None
    if success and final_result is not None and should_visualize(final_result, question):
        try:
            chart_b64 = generate_chart(final_result, question)
        except Exception as e:
            logger.warning(f"[Engine] Chart generation failed: {e}")
            chart_b64 = None

    return {
        "success": success,
        "answer": final_state.get("final_answer") or "No answer produced.",
        "code": last_code,
        "result": final_result,
        "result_type": last_result_type,
        "error": "; ".join(final_state.get("errors", [])) or None,
        "chart": chart_b64,
        "trace": final_state.get("trace", []),
        "subtasks": [
            {
                "id": st["id"],
                "description": st["description"],
                "specialist": st["specialist"],
                "code": st["code"],
                "retry_count": st["retry_count"],
                "error": st["error"],
            }
            for st in final_state.get("subtasks", [])
        ],
        "anomalies": final_state.get("anomalies", []),
    }


def _ensure_sqlite(session_id: str, df) -> str:
    if session_id in _SQLITE_CACHE:
        return _SQLITE_CACHE[session_id]
    logger.info(f"[Engine] Creating SQLite for session {session_id}...")
    path = create_sqlite_from_dataframe(df, session_id, table_name="data")
    _SQLITE_CACHE[session_id] = path
    logger.info(f"[Engine] SQLite created at {path}")
    return path


def clear_session_sqlite(session_id: str) -> None:
    from .sqlite_store import delete_sqlite

    _SQLITE_CACHE.pop(session_id, None)
    delete_sqlite(session_id)
