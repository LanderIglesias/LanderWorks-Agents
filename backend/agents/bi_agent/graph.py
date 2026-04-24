"""
graph.py — Construye el grafo LangGraph del BI Agent (Fase 3).

Cambio respecto a Fase 2: insertamos el nodo anomaly_detector entre
executor y validator. Queda así:

  START → planner → [pandas_specialist | sql_specialist]
                           ↓
                       executor
                           ↓
                   anomaly_detector   ← NUEVO Fase 3
                           ↓
                       validator
                           ↓
              (retry | next subtask | synthesizer)
                           ↓
                         END

El anomaly_detector nunca bloquea el flujo. Solo inspecciona y añade
contexto al estado. El Validator sigue siendo el único que decide
retry/fail.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes.anomaly_node import anomaly_node
from .nodes.executor import executor_node
from .nodes.pandas_specialist import pandas_specialist_node
from .nodes.planner import planner_node
from .nodes.router import post_validation_router, specialist_router
from .nodes.sql_specialist import sql_specialist_node
from .nodes.synthesizer import synthesizer_node
from .nodes.validator import validator_node
from .state import AgentState


def build_graph():
    """Construye y compila el grafo LangGraph del BI Agent."""
    graph = StateGraph(AgentState)

    # ── Nodos ──────────────────────────────────────────────────────────
    graph.add_node("planner", planner_node)
    graph.add_node("pandas_specialist", pandas_specialist_node)
    graph.add_node("sql_specialist", sql_specialist_node)
    graph.add_node("executor", executor_node)
    graph.add_node("anomaly_detector", anomaly_node)  # Fase 3
    graph.add_node("validator", validator_node)
    graph.add_node("synthesizer", synthesizer_node)

    # ── Edges ──────────────────────────────────────────────────────────

    graph.add_edge(START, "planner")

    # Planner → especialista (routing condicional)
    graph.add_conditional_edges(
        "planner",
        specialist_router,
        {
            "pandas_specialist": "pandas_specialist",
            "sql_specialist": "sql_specialist",
            "synthesizer": "synthesizer",
        },
    )

    # Especialistas → executor
    graph.add_edge("pandas_specialist", "executor")
    graph.add_edge("sql_specialist", "executor")

    # Executor → anomaly_detector (nuevo en Fase 3)
    graph.add_edge("executor", "anomaly_detector")

    # Anomaly_detector → validator
    graph.add_edge("anomaly_detector", "validator")

    # Validator → siguiente paso (condicional)
    graph.add_conditional_edges(
        "validator",
        post_validation_router,
        {
            "pandas_specialist": "pandas_specialist",
            "sql_specialist": "sql_specialist",
            "synthesizer": "synthesizer",
        },
    )

    # Synthesizer → END
    graph.add_edge("synthesizer", END)

    return graph.compile()


compiled_graph = build_graph()
