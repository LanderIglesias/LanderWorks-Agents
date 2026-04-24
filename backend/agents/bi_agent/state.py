"""
state.py — Estado compartido del grafo LangGraph del BI Agent.

Cambio Fase 3: añadido campo `anomalies` que acumula las anomalías
detectadas por el AnomalyDetector node a lo largo de las subtareas.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

SpecialistType = Literal["pandas", "sql"]
ValidationStatus = Literal["pass", "fail", "retry"]


class Subtask(TypedDict):
    """Una subtarea individual del plan."""

    id: str
    description: str
    specialist: SpecialistType
    code: str | None
    result: Any
    result_type: str | None
    error: str | None
    retry_count: int
    validation_feedback: str | None


class AgentState(TypedDict):
    """Estado que fluye por todo el grafo."""

    # ── Input del usuario ──
    session_id: str
    question: str

    # ── Contexto de datos ──
    schema: dict
    sqlite_path: str | None
    table_name: str

    # ── Plan ──
    subtasks: list[Subtask]
    current_subtask_idx: int

    # ── Salida ──
    final_answer: str | None
    final_result: Any

    # ── Control de flujo ──
    validation_status: ValidationStatus | None
    max_retries: int
    errors: Annotated[list[str], operator.add]
    trace: Annotated[list[str], operator.add]

    # ── Fase 3: anomalías detectadas ──
    # Cada anomalía es un dict con severity, title, message, metric
    # Se acumula a lo largo del grafo (concat con operator.add)
    anomalies: Annotated[list[dict], operator.add]


def create_initial_state(
    session_id: str,
    question: str,
    schema: dict,
    sqlite_path: str | None = None,
    table_name: str = "data",
    max_retries: int = 2,
) -> AgentState:
    """Crea el estado inicial del grafo."""
    return AgentState(
        session_id=session_id,
        question=question,
        schema=schema,
        sqlite_path=sqlite_path,
        table_name=table_name,
        subtasks=[],
        current_subtask_idx=0,
        final_answer=None,
        final_result=None,
        validation_status=None,
        max_retries=max_retries,
        errors=[],
        trace=[],
        anomalies=[],
    )


def create_subtask(
    task_id: str,
    description: str,
    specialist: SpecialistType,
) -> Subtask:
    """Crea una subtarea vacía lista para ser ejecutada."""
    return Subtask(
        id=task_id,
        description=description,
        specialist=specialist,
        code=None,
        result=None,
        result_type=None,
        error=None,
        retry_count=0,
        validation_feedback=None,
    )
