"""
validator.py — Nodo Validator (Quality Gate) del grafo.

Rol: después de ejecutar el código del especialista, decide si el resultado
es válido o si hay que reintentar.

Estrategia:
1. Si hubo error de ejecución → retry (hasta max_retries)
2. Si el resultado está vacío cuando no debería → retry con feedback
3. Si todo ok → pass, avanzamos a la siguiente subtarea

Este nodo NO llama al LLM — la validación es heurística, rápida y
determinista. Esto evita coste innecesario y hace el grafo más predecible.

Cómo incrementa current_subtask_idx:
- Si pass: idx += 1 (pasamos a la siguiente subtarea)
- Si fail después de retries: idx += 1 (nos rendimos con esta, vamos a la siguiente)
- Si retry: no cambia idx (volvemos al mismo specialist con feedback)
"""

from __future__ import annotations

from ..state import AgentState


def validator_node(state: AgentState) -> dict:
    """
    Valida el resultado de la subtarea actual y decide el siguiente paso.

    Returns: dict con:
        - subtasks: actualizado con feedback si retry
        - current_subtask_idx: incrementado si avanzamos
        - validation_status: "pass" | "retry" | "fail"
        - errors: añade mensaje si fail
        - trace: log del validador
    """
    idx = state["current_subtask_idx"]
    subtasks = list(state["subtasks"])
    subtask = subtasks[idx]
    max_retries = state["max_retries"]

    # ── Caso 1: el código falló al ejecutar ─────────────────────────────
    if subtask["error"]:
        if subtask["retry_count"] < max_retries:
            # Podemos reintentar — pasamos el feedback al especialista
            subtask["validation_feedback"] = (
                f"The code failed with this error: {subtask['error']}. "
                f"Please generate a different approach that avoids this error."
            )
            subtask["retry_count"] += 1
            subtasks[idx] = subtask

            return {
                "subtasks": subtasks,
                "validation_status": "retry",
                "trace": [
                    f"validator (task {idx + 1}: retry {subtask['retry_count']}/{max_retries})"
                ],
            }
        else:
            # Agotamos los reintentos — nos rendimos con esta subtarea
            subtasks[idx] = subtask
            return {
                "subtasks": subtasks,
                "current_subtask_idx": idx + 1,
                "validation_status": "fail",
                "errors": [
                    f"Task {idx + 1} failed after {max_retries} retries: {subtask['error']}"
                ],
                "trace": [f"validator (task {idx + 1}: FAIL after {max_retries} retries)"],
            }

    # ── Caso 2: resultado vacío ─────────────────────────────────────────
    if _is_empty_result(subtask["result"]):
        if subtask["retry_count"] < max_retries:
            subtask["validation_feedback"] = (
                "The query returned an empty result. "
                "Check your filter conditions and column values — they may not match the actual data."
            )
            subtask["retry_count"] += 1
            subtasks[idx] = subtask

            return {
                "subtasks": subtasks,
                "validation_status": "retry",
                "trace": [
                    f"validator (task {idx + 1}: empty result, retry {subtask['retry_count']})"
                ],
            }
        # Si seguimos obteniendo vacío tras retries, lo aceptamos — puede ser legítimo
        # (ej: "how many users churned in 2030" → legítimamente 0)

    # ── Caso 3: todo ok ─────────────────────────────────────────────────
    subtasks[idx] = subtask
    return {
        "subtasks": subtasks,
        "current_subtask_idx": idx + 1,
        "validation_status": "pass",
        "trace": [f"validator (task {idx + 1}: PASS)"],
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _is_empty_result(result) -> bool:
    """
    Heurística para detectar resultados vacíos que probablemente no deberían serlo.

    Casos:
    - None
    - DataFrame con 0 filas
    - Series con 0 items
    - Lista vacía
    - Dict vacío
    """
    if result is None:
        return True

    if isinstance(result, dict):
        if result.get("type") == "dataframe":
            return result.get("total_rows", 0) == 0
        if result.get("type") == "series":
            return result.get("total_items", 0) == 0
        # dict genérico
        return len(result) == 0

    if isinstance(result, (list, tuple)):
        return len(result) == 0

    # Scalars no se consideran vacíos (0, False, "" son respuestas válidas)
    return False
