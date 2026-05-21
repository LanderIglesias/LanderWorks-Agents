"""
code_analyzer.py — Nodo 2 del Technical Debt Analyzer

Responsabilidad: analizar cada archivo .py del repo usando AST y radon
para detectar problemas reales de calidad de código.

Detecta:
- Funciones demasiado largas (> 50 líneas)
- Funciones con demasiados parámetros (> 5)
- Clases demasiado grandes (> 10 métodos)
- Archivos demasiado largos (> 300 líneas)
- Complejidad ciclomática alta (> 10) usando radon

Usa:
- ast      → analizar la estructura del código sin ejecutarlo
- radon    → calcular complejidad ciclomática de cada función
- pathlib  → leer archivos de forma limpia
"""

from __future__ import annotations

import ast
from pathlib import Path

from radon.complexity import cc_visit
from radon.metrics import mi_visit

# ── Umbrales de calidad ───────────────────────────────────────────────────────
MAX_FUNCTION_LINES = 50
MAX_FUNCTION_PARAMS = 5
MAX_CLASS_METHODS = 10
MAX_FILE_LINES = 300
MAX_CYCLOMATIC_COMPLEXITY = 10


def analyze_files(python_files: list[str]) -> dict:
    """
    Analiza todos los archivos Python del repo y devuelve
    un resumen de los problemas encontrados.
    """
    all_issues = []
    maintainability_scores = []
    files_analyzed = 0
    files_with_errors = 0

    for file_path in python_files:
        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)

            file_issues = _analyze_file(file_path, source, tree)
            all_issues.extend(file_issues)

            # Score de mantenibilidad con radon (0-100)
            mi_score = mi_visit(source, multi=True)
            maintainability_scores.append(
                {
                    "file": _short_path(file_path),
                    "score": round(mi_score, 1),
                    "rating": _mi_rating(mi_score),
                }
            )

            files_analyzed += 1

        except SyntaxError:
            all_issues.append(
                {
                    "file": _short_path(file_path),
                    "type": "syntax_error",
                    "severity": "critical",
                    "message": "File has syntax errors and cannot be parsed",
                    "line": None,
                    "name": None,
                }
            )
            files_with_errors += 1

        except Exception:
            files_with_errors += 1

    summary = _build_summary(all_issues)

    return {
        "issues": all_issues,
        "summary": summary,
        "files_analyzed": files_analyzed,
        "files_with_errors": files_with_errors,
        "maintainability_scores": sorted(maintainability_scores, key=lambda x: x["score"]),
    }


def _analyze_file(file_path: str, source: str, tree: ast.AST) -> list[dict]:
    """Analiza un único archivo y devuelve la lista de issues encontrados."""
    issues = []
    short = _short_path(file_path)

    # 1. Archivo demasiado largo
    lines = source.splitlines()
    if len(lines) > MAX_FILE_LINES:
        issues.append(
            {
                "file": short,
                "type": "long_file",
                "severity": "medium",
                "message": f"File has {len(lines)} lines (max recommended: {MAX_FILE_LINES})",
                "line": None,
                "name": short,
            }
        )

    # 2. Análisis de funciones y clases con AST
    for node in ast.walk(tree):

        # Funciones demasiado largas o con demasiados parámetros
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):

            if hasattr(node, "end_lineno"):
                func_lines = node.end_lineno - node.lineno
                if func_lines > MAX_FUNCTION_LINES:
                    issues.append(
                        {
                            "file": short,
                            "type": "long_function",
                            "severity": "high",
                            "message": f"Function '{node.name}' has {func_lines} lines (max: {MAX_FUNCTION_LINES})",
                            "line": node.lineno,
                            "name": node.name,
                        }
                    )

            params = [a for a in node.args.args if a.arg not in ("self", "cls")]
            if len(params) > MAX_FUNCTION_PARAMS:
                issues.append(
                    {
                        "file": short,
                        "type": "too_many_params",
                        "severity": "medium",
                        "message": f"Function '{node.name}' has {len(params)} parameters (max: {MAX_FUNCTION_PARAMS})",
                        "line": node.lineno,
                        "name": node.name,
                    }
                )

        # Clases con demasiados métodos
        if isinstance(node, ast.ClassDef):
            methods = [
                n for n in ast.walk(node) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            if len(methods) > MAX_CLASS_METHODS:
                issues.append(
                    {
                        "file": short,
                        "type": "large_class",
                        "severity": "medium",
                        "message": f"Class '{node.name}' has {len(methods)} methods (max: {MAX_CLASS_METHODS})",
                        "line": node.lineno,
                        "name": node.name,
                    }
                )

    # 3. Complejidad ciclomática con radon
    try:
        complexity_results = cc_visit(source)
        for result in complexity_results:
            if result.complexity > MAX_CYCLOMATIC_COMPLEXITY:
                issues.append(
                    {
                        "file": short,
                        "type": "high_complexity",
                        "severity": "high" if result.complexity > 15 else "medium",
                        "message": f"'{result.name}' has cyclomatic complexity {result.complexity} (max: {MAX_CYCLOMATIC_COMPLEXITY})",
                        "line": result.lineno,
                        "name": result.name,
                    }
                )
    except Exception:
        pass

    return issues


def _build_summary(issues: list[dict]) -> dict:
    """Conteo de issues por tipo y severidad."""
    summary = {
        "total": len(issues),
        "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "by_type": {},
    }
    for issue in issues:
        severity = issue.get("severity", "low")
        issue_type = issue.get("type", "unknown")
        summary["by_severity"][severity] = summary["by_severity"].get(severity, 0) + 1
        summary["by_type"][issue_type] = summary["by_type"].get(issue_type, 0) + 1
    return summary


def _short_path(file_path: str) -> str:
    """Acorta la ruta temporal para que sea legible en los informes."""
    parts = Path(file_path).parts
    for i, part in enumerate(parts):
        if part.startswith("tech_debt_"):
            return str(Path(*parts[i + 1 :]))
    return file_path


def _mi_rating(score: float) -> str:
    """Convierte el score de mantenibilidad en etiqueta legible."""
    if score >= 20:
        return "A - Maintainable"
    elif score >= 10:
        return "B - Moderate"
    else:
        return "C - Hard to maintain"
