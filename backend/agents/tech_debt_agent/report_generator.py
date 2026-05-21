"""
report_generator.py — Nodo 6 del Technical Debt Analyzer

Responsabilidad: calcular el health score (0-100) con pesos por categoría
y generar el informe final en markdown combinando los hallazgos técnicos
con la interpretación de Claude.

El health score se calcula así:
- Calidad de código:   40 puntos máximo
- Tests:               30 puntos máximo
- Dependencias:        20 puntos máximo
- CI/CD:               10 puntos máximo

Cuantos más issues graves, menos puntos. Score final = suma de las 4 categorías.
"""

from __future__ import annotations

from datetime import datetime


def calculate_health_score(
    code_analysis: dict,
    test_analysis: dict,
    dependency_analysis: dict,
) -> int:
    """
    Calcula el health score del repositorio (0-100).
    Cada categoría tiene un peso diferente según su importancia.

    Args:
        code_analysis: resultado de code_analyzer
        test_analysis: resultado de test_analyzer
        dependency_analysis: resultado de dependency_scanner

    Returns:
        Score entre 0 y 100
    """
    score = 0

    # ── Calidad de código — 40 puntos máximo ─────────────────────────────────
    # Penalizamos según el número de issues críticos y altos
    summary = code_analysis.get("summary", {})
    by_severity = summary.get("by_severity", {})

    critical = by_severity.get("critical", 0)
    high = by_severity.get("high", 0)
    medium = by_severity.get("medium", 0)

    # Fórmula: empezamos con 40 puntos y restamos por cada issue
    # Los críticos pesan más que los altos que pesan más que los medios
    code_score = 40
    code_score -= critical * 10  # cada issue crítico quita 10 puntos
    code_score -= high * 3  # cada issue alto quita 3 puntos
    code_score -= medium * 1  # cada issue medio quita 1 punto
    code_score = max(0, code_score)  # nunca por debajo de 0

    score += code_score

    # ── Tests — 30 puntos máximo ──────────────────────────────────────────────
    test_score = 0

    if test_analysis.get("has_tests", False):
        test_score += 15  # tiene tests: 15 puntos base

        test_ratio = test_analysis.get("test_ratio", 0)
        if test_ratio >= 60:
            test_score += 10  # buena cobertura: 10 puntos más
        elif test_ratio >= 30:
            test_score += 5  # cobertura media: 5 puntos más

        if test_analysis.get("has_pytest_config", False):
            test_score += 5  # pytest configurado: 5 puntos más

    score += test_score

    # ── Dependencias — 20 puntos máximo ──────────────────────────────────────
    dep_score = 20

    unpinned = len(dependency_analysis.get("unpinned", []))
    outdated = len(dependency_analysis.get("outdated", []))

    dep_score -= unpinned * 2  # cada dependencia sin fijar quita 2 puntos
    dep_score -= outdated * 1  # cada dependencia desactualizada quita 1 punto

    if not dependency_analysis.get("has_requirements", True):
        dep_score = 0  # sin requirements.txt: 0 puntos en esta categoría

    dep_score = max(0, dep_score)
    score += dep_score

    # ── CI/CD — 10 puntos máximo ──────────────────────────────────────────────
    if test_analysis.get("has_ci_cd", False):
        score += 10

    return min(100, max(0, score))


def generate_report(
    repo_name: str,
    github_url: str,
    health_score: int,
    code_analysis: dict,
    dependency_analysis: dict,
    test_analysis: dict,
    llm_interpretation: dict,
) -> dict:
    """
    Genera el informe final combinando hallazgos técnicos e interpretación de Claude.

    Returns:
        {
            "health_score": int,
            "score_label": str,
            "markdown": str,         # informe completo en markdown
            "summary": dict,         # resumen para el frontend
        }
    """
    score_label = _score_label(health_score)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    markdown = _build_markdown(
        repo_name=repo_name,
        github_url=github_url,
        health_score=health_score,
        score_label=score_label,
        timestamp=timestamp,
        code_analysis=code_analysis,
        dependency_analysis=dependency_analysis,
        test_analysis=test_analysis,
        llm_interpretation=llm_interpretation,
    )

    return {
        "health_score": health_score,
        "score_label": score_label,
        "markdown": markdown,
        "summary": {
            "repo_name": repo_name,
            "github_url": github_url,
            "timestamp": timestamp,
            "files_analyzed": code_analysis.get("files_analyzed", 0),
            "total_issues": code_analysis.get("summary", {}).get("total", 0),
            "has_tests": test_analysis.get("has_tests", False),
            "test_ratio": test_analysis.get("test_ratio", 0),
            "has_ci_cd": test_analysis.get("has_ci_cd", False),
            "outdated_deps": len(dependency_analysis.get("outdated", [])),
            "risk_level": llm_interpretation.get("risk_level", "unknown"),
        },
    }


def _build_markdown(
    repo_name: str,
    github_url: str,
    health_score: int,
    score_label: str,
    timestamp: str,
    code_analysis: dict,
    dependency_analysis: dict,
    test_analysis: dict,
    llm_interpretation: dict,
) -> str:
    """Construye el informe completo en markdown."""

    summary = code_analysis.get("summary", {})
    by_severity = summary.get("by_severity", {})
    by_type = summary.get("by_type", {})  # noqa: F841

    # Hallazgos críticos de Claude
    critical_findings = llm_interpretation.get("critical_findings", [])
    findings_text = (
        "\n".join([f"- {f}" for f in critical_findings]) or "- No critical findings identified."
    )

    # Recomendaciones de Claude
    recommendations = llm_interpretation.get("recommendations", [])
    recs_text = (
        "\n".join([f"{i+1}. {r}" for i, r in enumerate(recommendations)])
        or "No recommendations generated."
    )

    # Top issues técnicos
    top_issues = sorted(
        code_analysis.get("issues", []),
        key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
            x.get("severity", "low"), 3
        ),
    )[:15]

    issues_rows = (
        "\n".join(
            [
                f"| {i.get('severity', '?').upper()} | {i.get('type', '?')} | {i.get('file', '?')} | {i.get('message', '?')} |"
                for i in top_issues
            ]
        )
        or "| - | - | - | No issues found |"
    )

    # Dependencias desactualizadas
    outdated = dependency_analysis.get("outdated", [])
    outdated_text = (
        "\n".join([f"- `{d['name']}`: {d['current']} → {d['latest']}" for d in outdated[:10]])
        or "All dependencies are up to date. ✅"
    )

    # Peores archivos por mantenibilidad
    worst_files = code_analysis.get("maintainability_scores", [])[:5]
    worst_text = (
        "\n".join([f"- `{f['file']}` — {f['rating']} (score: {f['score']})" for f in worst_files])
        or "No data available."
    )

    return f"""# Technical Debt Report — {repo_name}

> Generated by Technical Debt Analyzer | {timestamp}
> Repository: [{github_url}]({github_url})

---

## 🏥 Health Score: {health_score}/100 — {score_label}

| Category | Status |
|---|---|
| Code Quality | {by_severity.get('critical', 0)} critical, {by_severity.get('high', 0)} high, {by_severity.get('medium', 0)} medium issues |
| Test Coverage | {"✅ Tests found" if test_analysis.get("has_tests") else "❌ No tests"} — {test_analysis.get("test_ratio", 0):.0f}% file coverage |
| Dependencies | {len(dependency_analysis.get("outdated", []))} outdated, {len(dependency_analysis.get("unpinned", []))} unpinned |
| CI/CD | {"✅ Configured" if test_analysis.get("has_ci_cd") else "❌ Not found"} |

---

## 📋 Executive Summary

{llm_interpretation.get("executive_summary", "Analysis not available.")}

**Risk Level:** {llm_interpretation.get("risk_level", "unknown").upper()}
**Estimated effort to address critical issues:** {llm_interpretation.get("estimated_debt_hours", "unknown")}

---

## 🚨 Critical Findings

{findings_text}

---

## 💡 Recommendations

{recs_text}

---

## 🔍 Top Technical Issues

| Severity | Type | File | Message |
|---|---|---|---|
{issues_rows}

---

## 📦 Outdated Dependencies

{outdated_text}

---

## 📊 Worst Maintainability Files

{worst_text}

---

## 🧪 Test Coverage

- **Has tests:** {"Yes" if test_analysis.get("has_tests") else "No"}
- **Test files found:** {len(test_analysis.get("test_files", []))}
- **File coverage ratio:** {test_analysis.get("test_ratio", 0):.0f}%
- **pytest configured:** {"Yes" if test_analysis.get("has_pytest_config") else "No"}
- **CI/CD runs tests automatically:** {"Yes" if test_analysis.get("has_ci_cd") else "No"}
- **Untested public functions:** {len(test_analysis.get("untested_functions", []))}

---

*Report generated by Technical Debt Analyzer — github.com/LanderIglesias/LanderWorks-Agents*
"""


def _score_label(score: int) -> str:
    """Convierte el score numérico en una etiqueta descriptiva."""
    if score >= 80:
        return "🟢 Healthy"
    elif score >= 60:
        return "🟡 Moderate"
    elif score >= 40:
        return "🟠 Needs Attention"
    elif score >= 20:
        return "🔴 Critical"
    else:
        return "⚫ Severely Degraded"
