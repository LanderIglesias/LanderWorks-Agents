"""
llm_interpreter.py — Nodo 5 del Technical Debt Analyzer

Responsabilidad: recibir todos los hallazgos técnicos de los nodos anteriores
y pedirle a Claude que los interprete en lenguaje de negocio.

Claude NO analiza el código directamente — recibe los hallazgos estructurados
y los convierte en:
- Un veredicto ejecutivo del estado del repositorio
- Hallazgos priorizados por impacto en negocio (no solo técnico)
- Recomendaciones concretas y accionables
- Una estimación del riesgo para el negocio

Usa:
- anthropic → Claude Haiku para la interpretación
"""

from __future__ import annotations

import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv(override=False)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 2048

SYSTEM_PROMPT = """You are a senior software engineering consultant specializing in technical debt assessment.

You receive structured data from automated code analysis tools and your job is to:
1. Interpret the technical findings in business terms
2. Prioritize issues by their real-world impact on the business (not just technical severity)
3. Generate actionable recommendations that a development team can actually implement
4. Communicate clearly to both technical and non-technical stakeholders

IMPORTANT RULES:
- Always connect technical issues to business impact (cost, risk, speed of delivery, onboarding)
- Prioritize by business impact, not just technical severity
- Be specific — avoid generic advice like "write more tests". Say which modules need tests first and why
- Be honest about the overall health of the codebase
- Keep your response structured and scannable
- Respond in the same language as the repository name suggests (if Spanish repo → Spanish response, if English → English)
"""


def interpret_findings(
    repo_name: str,
    code_analysis: dict,
    dependency_analysis: dict,
    test_analysis: dict,
    health_score: int,
) -> dict:
    """
    Pide a Claude que interprete los hallazgos técnicos en lenguaje de negocio.

    Args:
        repo_name: nombre del repositorio analizado
        code_analysis: resultado de code_analyzer.analyze_files()
        dependency_analysis: resultado de dependency_scanner.scan_dependencies()
        test_analysis: resultado de test_analyzer.analyze_tests()
        health_score: score de salud calculado por report_generator (0-100)

    Returns:
        {
            "executive_summary": str,      # resumen ejecutivo para el CTO
            "critical_findings": list[str], # hallazgos críticos en lenguaje de negocio
            "recommendations": list[str],   # recomendaciones priorizadas
            "risk_level": str,             # "low" / "medium" / "high" / "critical"
            "estimated_debt_hours": str,   # estimación de horas para saldar la deuda
        }
    """

    # Preparamos el contexto para Claude
    # Resumimos los hallazgos para no saturar el contexto window
    context = _build_context(
        repo_name, code_analysis, dependency_analysis, test_analysis, health_score
    )

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = f"""Analyze the following technical debt assessment for the repository "{repo_name}" and provide a business-focused interpretation.

AUTOMATED ANALYSIS RESULTS:
{context}

HEALTH SCORE: {health_score}/100

Please provide your analysis in the following JSON format (respond ONLY with valid JSON, no markdown):
{{
    "executive_summary": "2-3 sentences summarizing the overall state of the codebase for a CTO or engineering manager",
    "critical_findings": [
        "Finding 1 with business impact explained",
        "Finding 2 with business impact explained"
    ],
    "recommendations": [
        "Specific actionable recommendation 1 (which files/modules, what to do, why it matters)",
        "Specific actionable recommendation 2",
        "Specific actionable recommendation 3"
    ],
    "risk_level": "low|medium|high|critical",
    "estimated_debt_hours": "X-Y hours (rough estimate to address the most critical issues)"
}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # Parseamos el JSON que devuelve Claude
    # Limpiamos por si Claude añade markdown alrededor del JSON
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
    except json.JSONDecodeError:
        # Si Claude no devuelve JSON válido, devolvemos un resultado de fallback
        result = {
            "executive_summary": raw[:500],
            "critical_findings": [],
            "recommendations": [],
            "risk_level": "unknown",
            "estimated_debt_hours": "unknown",
        }

    return result


def _build_context(
    repo_name: str,
    code_analysis: dict,
    dependency_analysis: dict,
    test_analysis: dict,
    health_score: int,
) -> str:
    """
    Construye el contexto que le pasamos a Claude.
    Resumimos los datos para no saturar el context window.
    """

    # Resumimos los issues de código — los 10 más graves
    top_issues = sorted(
        code_analysis.get("issues", []),
        key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
            x.get("severity", "low"), 3
        ),
    )[:10]

    issues_text = (
        "\n".join(
            [
                f"- [{i.get('severity', '?').upper()}] {i.get('message', '')} ({i.get('file', '')})"
                for i in top_issues
            ]
        )
        or "No issues found"
    )

    # Resumen del análisis de código
    summary = code_analysis.get("summary", {})
    by_severity = summary.get("by_severity", {})
    by_type = summary.get("by_type", {})

    # Resumen de dependencias
    dep_issues = dependency_analysis.get("issues", [])  # noqa: F841
    outdated = dependency_analysis.get("outdated", [])
    unpinned = dependency_analysis.get("unpinned", [])

    # Resumen de tests
    has_tests = test_analysis.get("has_tests", False)
    test_ratio = test_analysis.get("test_ratio", 0)
    has_ci = test_analysis.get("has_ci_cd", False)
    coverage = test_analysis.get("coverage_estimate", "unknown")

    # Scores de mantenibilidad — los 5 peores archivos
    worst_files = code_analysis.get("maintainability_scores", [])[:5]
    worst_text = (
        "\n".join([f"- {f['file']}: {f['rating']} (score: {f['score']})" for f in worst_files])
        or "No data"
    )

    return f"""
REPOSITORY: {repo_name}
HEALTH SCORE: {health_score}/100

CODE QUALITY:
- Files analyzed: {code_analysis.get('files_analyzed', 0)}
- Total issues: {summary.get('total', 0)}
- By severity: Critical={by_severity.get('critical', 0)}, High={by_severity.get('high', 0)}, Medium={by_severity.get('medium', 0)}
- By type: {json.dumps(by_type)}

TOP ISSUES:
{issues_text}

WORST MAINTAINABILITY FILES:
{worst_text}

DEPENDENCIES:
- Total declared: {len(dependency_analysis.get('dependencies_found', []))}
- Unpinned (no fixed version): {len(unpinned)}
- Outdated: {len(outdated)}
- Possibly unused: {len(dependency_analysis.get('unused', []))}

TESTING:
- Has tests: {has_tests}
- Test coverage ratio: {test_ratio}%
- Has CI/CD: {has_ci}
- Coverage estimate: {coverage}
- Untested public functions: {len(test_analysis.get('untested_functions', []))}
""".strip()
