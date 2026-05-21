"""
api.py — Endpoints FastAPI del Technical Debt Analyzer

Endpoints:
- POST /tech-debt/analyze        → análisis completo síncrono
- POST /tech-debt/analyze/stream → análisis con progreso en tiempo real (SSE)
- GET  /tech-debt/demo           → sirve la UI
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from .code_analyzer import analyze_files
from .demo_template import demo_html
from .dependency_scanner import scan_dependencies
from .llm_interpreter import interpret_findings
from .repo_fetcher import cleanup_repo, fetch_repo
from .report_generator import calculate_health_score, generate_report
from .test_analyzer import analyze_tests

router = APIRouter(prefix="/tech-debt", tags=["tech-debt"])


class AnalyzeRequest(BaseModel):
    github_url: str


class AnalyzeResponse(BaseModel):
    health_score: int
    score_label: str
    markdown: str
    summary: dict


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest):
    """Analiza un repositorio GitHub y devuelve el informe completo."""
    from .engine import analyze_repository

    result = analyze_repository(payload.github_url)

    if "error" in result:
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail=result["error"])

    return AnalyzeResponse(**result)


@router.post("/analyze/stream")
async def analyze_stream(payload: AnalyzeRequest):
    """
    Analiza un repositorio GitHub enviando progreso en tiempo real via SSE.
    Cada evento tiene: step, message, progress (0-100).
    El último evento tiene step='done' y el report completo.
    """

    def event_stream():
        def send(step: str, message: str, progress: int, **kwargs) -> str:
            data = {"step": step, "message": message, "progress": progress, **kwargs}
            return f"data: {json.dumps(data)}\n\n"

        repo_path = None

        try:
            # Nodo 1 — Clonar repo
            yield send("cloning", f"Cloning {payload.github_url}...", 10)
            repo_info = fetch_repo(payload.github_url)
            repo_path = repo_info["repo_path"]
            yield send("cloned", f"Cloned: {repo_info['python_file_count']} Python files found", 20)

            # Nodo 2 — Analizar código
            yield send(
                "analyzing_code",
                f"Analyzing {repo_info['python_file_count']} Python files with AST...",
                35,
            )
            code_analysis = analyze_files(repo_info["python_files"])
            total_issues = code_analysis.get("summary", {}).get("total", 0)
            yield send("code_analyzed", f"Code analysis done: {total_issues} issues found", 50)

            # Nodo 3 — Dependencias
            yield send("scanning_deps", "Checking dependencies against PyPI...", 60)
            dependency_analysis = scan_dependencies(
                repo_info["repo_path"], repo_info["python_files"]
            )
            outdated = len(dependency_analysis.get("outdated", []))
            yield send("deps_scanned", f"Dependencies done: {outdated} outdated packages", 68)

            # Nodo 4 — Tests
            yield send("analyzing_tests", "Analyzing test coverage...", 75)
            test_analysis = analyze_tests(repo_info["repo_path"], repo_info["python_files"])
            has_tests = test_analysis.get("has_tests", False)
            yield send(
                "tests_analyzed", f"Tests done: {'found' if has_tests else 'no tests found'}", 82
            )

            # Health score antes de Claude
            health_score = calculate_health_score(
                code_analysis=code_analysis,
                test_analysis=test_analysis,
                dependency_analysis=dependency_analysis,
            )

            # Nodo 5 — Claude
            yield send(
                "interpreting", f"Claude interpreting findings (score: {health_score}/100)...", 88
            )
            llm_interpretation = interpret_findings(
                repo_name=repo_info["repo_name"],
                code_analysis=code_analysis,
                dependency_analysis=dependency_analysis,
                test_analysis=test_analysis,
                health_score=health_score,
            )
            yield send("interpreted", "Claude interpretation complete", 94)

            # Nodo 6 — Informe final
            yield send("generating", "Generating final report...", 97)
            report = generate_report(
                repo_name=repo_info["repo_name"],
                github_url=payload.github_url,
                health_score=health_score,
                code_analysis=code_analysis,
                dependency_analysis=dependency_analysis,
                test_analysis=test_analysis,
                llm_interpretation=llm_interpretation,
            )

            yield send("done", "Analysis complete!", 100, report=report)

        except Exception as e:
            yield send("error", str(e), 0, error=True)

        finally:
            if repo_path:
                cleanup_repo(repo_path)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@router.get("/demo", response_class=HTMLResponse)
def serve_demo():
    return HTMLResponse(content=demo_html())
