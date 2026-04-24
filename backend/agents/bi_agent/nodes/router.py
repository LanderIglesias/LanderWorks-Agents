"""
router.py — Nodos de routing del grafo LangGraph.

En LangGraph, un "router" es una función que devuelve el nombre del siguiente
nodo a ejecutar. Se usa con conditional_edges para bifurcar el grafo.

Tenemos DOS routers:

1. specialist_router(state)
   Decide qué especialista ejecutar para la subtarea actual.
   Returns: "pandas_specialist" | "sql_specialist"

2. post_validation_router(state)
   Después del validator decide qué hacer:
   - Si pass → siguiente subtarea o synthesizer
   - Si retry → volver al especialista
   - Si fail → ir directamente al synthesizer (con el error registrado)

Nota sobre conditional_edges:
LangGraph llama al router con el estado, lee el string devuelto, y salta
al nodo con ese nombre. No modifica el estado — solo decide rutas.
"""

from __future__ import annotations

from ..state import AgentState

# ── Router 1: decidir qué especialista usar ─────────────────────────────


def specialist_router(state: AgentState) -> str:
    """
    Mira la subtarea actual y devuelve el especialista asignado.

    El Planner ya decidió qué especialista usar para cada subtarea,
    así que aquí solo leemos de state y devolvemos el nombre del nodo.
    """
    idx = state["current_subtask_idx"]
    subtasks = state["subtasks"]

    # Safety check: si por alguna razón no hay subtareas, vamos al final
    if idx >= len(subtasks):
        return "synthesizer"

    specialist = subtasks[idx]["specialist"]

    if specialist == "sql":
        return "sql_specialist"
    return "pandas_specialist"  # default


# ── Router 2: decidir qué hacer tras validar ────────────────────────────


def post_validation_router(state: AgentState) -> str:
    """
    Tras el validator, decidir siguiente paso:

    - validation_status == "pass" → siguiente subtarea o synthesizer si ya
      hemos hecho todas
    - validation_status == "retry" → volver al especialista para reintentar
    - validation_status == "fail" → ir al synthesizer directamente (el error
      queda registrado y el synthesizer lo comunicará al usuario)
    """
    status = state["validation_status"]
    idx = state["current_subtask_idx"]
    subtasks = state["subtasks"]

    if status == "retry":
        # Reintentamos con el mismo especialista de la subtarea actual
        specialist = subtasks[idx]["specialist"]
        if specialist == "sql":
            return "sql_specialist"
        return "pandas_specialist"

    # Si pass o fail, pasamos a la siguiente subtarea (si hay) o al final
    # El current_subtask_idx se incrementa en el validator, no aquí
    if idx >= len(subtasks):
        return "synthesizer"

    # Aún quedan subtareas: volvemos a evaluar el especialista para la nueva subtarea
    specialist = subtasks[idx]["specialist"]
    if specialist == "sql":
        return "sql_specialist"
    return "pandas_specialist"
