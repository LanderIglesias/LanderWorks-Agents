"""
engine.py — Orquestador LangGraph del Technical Debt Analyzer

Pipeline:
repo_fetcher → code_analyzer → dependency_scanner → test_analyzer
            → llm_interpreter → report_generator → END
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from .code_analyzer import analyze_files
from .dependency_scanner import scan_dependencies
from .llm_interpreter import interpret_findings
from .repo_fetcher import cleanup_repo, fetch_repo
from .report_generator import calculate_health_score, generate_report
from .test_analyzer import analyze_tests


class TechDebtState(TypedDict):
    github_url: str
    repo_name: str
    repo_path: str
    python_files: list[str]
    total_files: int
    python_file_count: int
    languages: list[str]
    code_analysis: dict
    dependency_analysis: dict
    test_analysis: dict
    health_score: int
    llm_interpretation: dict
    report: dict
    error: str | None


def node_fetch_repo(state: TechDebtState) -> dict:
    print(f"[Engine] Nodo 1: Clonando repositorio {state['github_url']}...")
    try:
        result = fetch_repo(state["github_url"])
        return {
            "repo_name": result["repo_name"],
            "repo_path": result["repo_path"],
            "python_files": result["python_files"],
            "total_files": result["total_files"],
            "python_file_count": result["python_file_count"],
            "languages": result["languages"],
            "error": None,
        }
    except Exception as e:
        return {"error": str(e)}


def node_analyze_code(state: TechDebtState) -> dict:
    if state.get("error"):
        return {}
    print(f"[Engine] Nodo 2: Analizando {state['python_file_count']} archivos Python...")
    try:
        return {"code_analysis": analyze_files(state["python_files"])}
    except Exception as e:
        return {"error": str(e)}


def node_scan_dependencies(state: TechDebtState) -> dict:
    if state.get("error"):
        return {}
    print("[Engine] Nodo 3: Escaneando dependencias...")
    try:
        return {"dependency_analysis": scan_dependencies(state["repo_path"], state["python_files"])}
    except Exception as e:
        return {"error": str(e)}


def node_analyze_tests(state: TechDebtState) -> dict:
    if state.get("error"):
        return {}
    print("[Engine] Nodo 4: Analizando cobertura de tests...")
    try:
        return {"test_analysis": analyze_tests(state["repo_path"], state["python_files"])}
    except Exception as e:
        return {"error": str(e)}


def node_interpret(state: TechDebtState) -> dict:
    if state.get("error"):
        return {}
    print("[Engine] Nodo 5: Claude interpretando hallazgos...")
    try:
        health_score = calculate_health_score(
            code_analysis=state["code_analysis"],
            test_analysis=state["test_analysis"],
            dependency_analysis=state["dependency_analysis"],
        )
        result = interpret_findings(
            repo_name=state["repo_name"],
            code_analysis=state["code_analysis"],
            dependency_analysis=state["dependency_analysis"],
            test_analysis=state["test_analysis"],
            health_score=health_score,
        )
        return {"health_score": health_score, "llm_interpretation": result}
    except Exception as e:
        return {"error": str(e)}


def node_generate_report(state: TechDebtState) -> dict:
    if state.get("error"):
        return {}
    print("[Engine] Nodo 6: Generando informe final...")
    try:
        result = generate_report(
            repo_name=state["repo_name"],
            github_url=state["github_url"],
            health_score=state["health_score"],
            code_analysis=state["code_analysis"],
            dependency_analysis=state["dependency_analysis"],
            test_analysis=state["test_analysis"],
            llm_interpretation=state["llm_interpretation"],
        )
        return {"report": result}
    except Exception as e:
        return {"error": str(e)}


def build_graph():
    graph = StateGraph(TechDebtState)

    graph.add_node("fetch_repo", node_fetch_repo)
    graph.add_node("analyze_code", node_analyze_code)
    graph.add_node("scan_dependencies", node_scan_dependencies)
    graph.add_node("analyze_tests", node_analyze_tests)
    graph.add_node("interpret", node_interpret)
    graph.add_node("generate_report", node_generate_report)

    graph.set_entry_point("fetch_repo")
    graph.add_edge("fetch_repo", "analyze_code")
    graph.add_edge("analyze_code", "scan_dependencies")
    graph.add_edge("scan_dependencies", "analyze_tests")
    graph.add_edge("analyze_tests", "interpret")
    graph.add_edge("interpret", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


app_graph = build_graph()


def analyze_repository(github_url: str) -> dict:
    """Ejecuta el pipeline completo de análisis de deuda técnica."""
    initial_state: TechDebtState = {
        "github_url": github_url,
        "repo_name": "",
        "repo_path": "",
        "python_files": [],
        "total_files": 0,
        "python_file_count": 0,
        "languages": [],
        "code_analysis": {},
        "dependency_analysis": {},
        "test_analysis": {},
        "health_score": 0,
        "llm_interpretation": {},
        "report": {},
        "error": None,
    }

    try:
        final_state = app_graph.invoke(initial_state)

        if final_state.get("repo_path"):
            cleanup_repo(final_state["repo_path"])

        if final_state.get("error"):
            return {"error": final_state["error"]}

        return final_state.get("report", {"error": "No report generated"})

    except Exception as e:
        return {"error": str(e)}
