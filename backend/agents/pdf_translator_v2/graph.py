"""
graph.py — Definición del grafo LangGraph

Aquí construimos el grafo que conecta todos los nodos.
LangGraph funciona como una máquina de estados donde:
- Los NODOS son funciones que reciben el estado y devuelven cambios
- Los EDGES son conexiones entre nodos (pueden ser condicionales)
- El ESTADO fluye de nodo en nodo acumulando cambios

Estructura del grafo:
  START → analyzer → translator → quality_gate → reconstructor → END
                          ↑              |
                          └──── retry ───┘ (edge condicional)

El edge condicional en quality_gate decide:
- Si hay elementos que necesitan reintento Y no se ha alcanzado el máximo:
  → vuelve a translator (con solo los elementos marcados RETRY)
- Si todo está bien o se alcanzó el máximo de iteraciones:
  → continúa a reconstructor

¿Por qué LangGraph y no un script secuencial?
1. El loop de calidad es natural en LangGraph — un script necesitaría
   lógica especial para volver atrás
2. El estado es inmutable entre nodos — no hay efectos secundarios ocultos
3. Fácil de extender — añadir un nodo nuevo es añadir una función y un edge
4. Visualizable — LangGraph puede generar un diagrama del grafo
5. Checkpointing opcional — podemos pausar y reanudar traducciones largas
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from .analyzer_node import analyzer_node
from .image_patcher_node import image_patcher_node
from .image_strategy_node import image_strategy_node
from .language_classifier_node import language_classifier_node
from .quality_gate_node import quality_gate_node, should_retry
from .reconstructor_node import reconstructor_node
from .state import TranslationState
from .translator_node import translator_node


def build_graph() -> StateGraph:
    graph = StateGraph(TranslationState)

    graph.add_node("analyze", analyzer_node)
    graph.add_node("translate", translator_node)
    graph.add_node("quality", quality_gate_node)
    graph.add_node("language_classifier", language_classifier_node)
    graph.add_node("image_strategy", image_strategy_node)
    graph.add_node("image_patcher", image_patcher_node)
    graph.add_node("reconstruct", reconstructor_node)

    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "translate")
    graph.add_edge("translate", "quality")

    # Quality gate: retry → translate, ok → language_classifier
    graph.add_conditional_edges(
        "quality",
        should_retry,
        {
            "translate": "translate",
            "language_classifier": "language_classifier",
        },
    )

    graph.add_edge("language_classifier", "image_strategy")
    graph.add_edge("image_strategy", "image_patcher")
    graph.add_edge("image_patcher", "reconstruct")
    graph.add_edge("reconstruct", END)

    return graph.compile()


def translate_pdf(
    input_pdf_path: str,
    target_language: str,
    output_dir: str = "outputs",
    source_language: str = "auto",
    max_quality_iterations: int = 2,
) -> dict[str, Any]:
    """
    Punto de entrada principal del PDF Translator v2.

    Inicializa el estado y ejecuta el grafo LangGraph completo.

    Args:
        input_pdf_path: ruta al PDF original
        target_language: idioma destino (ej: "spanish", "french")
        output_dir: carpeta donde guardar el resultado
        source_language: idioma origen ("auto" = detección automática)
        max_quality_iterations: máximo de reintentos del quality gate

    Returns:
        Dict con success, output_path, stats y errors
    """
    start_time = time.time()

    if not os.path.exists(input_pdf_path):
        return {"success": False, "error": f"Fichero no encontrado: {input_pdf_path}"}

    os.makedirs(output_dir, exist_ok=True)

    input_name = Path(input_pdf_path).stem
    output_filename = f"{input_name}_translated_{target_language}.pdf"
    output_pdf_path = os.path.join(output_dir, output_filename)

    print(f"\n{'='*55}")
    print("PDF Translator v2 — LangGraph Pipeline")
    print(f"  Entrada:  {input_pdf_path}")
    print(f"  Idioma:   {target_language}")
    print(f"  Max QA:   {max_quality_iterations} iteraciones")
    print(f"{'='*55}\n")

    # Estado inicial del grafo
    initial_state: TranslationState = {
        "input_pdf_path": input_pdf_path,
        "output_pdf_path": output_pdf_path,
        "target_language": target_language,
        "source_language": source_language,
        "elements": [],
        "pages_info": [],
        "page_images": {},
        "current_phase": "start",
        "quality_iterations": 0,
        "max_quality_iterations": max_quality_iterations,
        "errors": [],
        "stats": {},
    }

    try:
        # Compilamos y ejecutamos el grafo
        graph = build_graph()
        final_state = graph.invoke(initial_state)

        elapsed = round(time.time() - start_time, 2)

        print(f"\n{'='*55}")
        print(f"✓ Completado en {elapsed}s")
        print(f"  PDF: {output_pdf_path}")
        stats = final_state.get("stats", {})
        print(f"  Páginas: {stats.get('pages', 0)}")
        print(f"  Elementos: {stats.get('total_elements', 0)}")
        print(f"  Traducidos: {stats.get('translatable', 0)}")
        print(f"  Iteraciones QA: {final_state.get('quality_iterations', 0)}")
        print("='*55}\n")

        return {
            "success": True,
            "output_path": output_pdf_path,
            "output_filename": output_filename,
            "stats": {
                **stats,
                "time_seconds": elapsed,
                "quality_iterations": final_state.get("quality_iterations", 0),
            },
            "errors": final_state.get("errors", []),
        }

    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        print(f"\n[Graph] ERROR tras {elapsed}s: {e}")
        import traceback

        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "stats": {"time_seconds": elapsed},
        }
