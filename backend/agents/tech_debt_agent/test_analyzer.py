"""
test_analyzer.py — Nodo 4 del Technical Debt Analyzer

Responsabilidad: analizar la cobertura de tests del proyecto.
No ejecuta los tests — analiza la estructura del código para estimar
qué porcentaje del código tiene tests asociados.

Detecta:
- Si el proyecto tiene tests en absoluto
- Ratio de archivos con tests vs archivos sin tests
- Si está configurado pytest
- Si hay CI/CD configurado que corra los tests automáticamente
- Funciones públicas sin test correspondiente (estimación)

Usa:
- pathlib → navegar la estructura de carpetas
- ast     → detectar funciones en archivos de test y de código
"""

from __future__ import annotations

import ast
from pathlib import Path


def analyze_tests(repo_path: str, python_files: list[str]) -> dict:
    """
    Analiza la cobertura de tests del proyecto.

    Args:
        repo_path: ruta raíz del repositorio clonado
        python_files: lista de archivos .py del repo

    Returns:
        {
            "issues": list[dict],
            "has_tests": bool,
            "test_files": list[str],
            "source_files": list[str],
            "test_ratio": float,          # porcentaje de archivos con tests
            "has_pytest_config": bool,
            "has_ci_cd": bool,
            "tested_functions": list[str],
            "untested_functions": list[str],
            "coverage_estimate": str,     # "low" / "medium" / "high"
        }
    """
    root = Path(repo_path)
    issues = []

    # ── 1. Separamos archivos de test de archivos de código ───────────────────
    # Los archivos de test siguen la convención: test_*.py o *_test.py
    test_files = [
        f
        for f in python_files
        if Path(f).name.startswith("test_") or Path(f).name.endswith("_test.py")
    ]

    source_files = [
        f
        for f in python_files
        if f not in test_files
        and not any(skip in f for skip in ["setup.py", "conftest.py", "manage.py"])
    ]

    # ── 2. Comprobamos si hay tests ───────────────────────────────────────────
    has_tests = len(test_files) > 0

    if not has_tests:
        issues.append(
            {
                "type": "no_tests",
                "severity": "critical",
                "message": "No test files found. The codebase has no automated tests.",
                "file": None,
            }
        )

    # ── 3. Ratio de cobertura por archivo ─────────────────────────────────────
    # Calculamos qué porcentaje de archivos de código tienen un test correspondiente
    if source_files:
        # Para cada archivo de código buscamos si existe un test_<nombre>.py
        covered_files = []
        for src in source_files:
            src_name = Path(src).stem  # "engine" de "engine.py"
            has_test = any(
                Path(test).stem in (f"test_{src_name}", f"{src_name}_test") for test in test_files
            )
            if has_test:
                covered_files.append(src)

        test_ratio = len(covered_files) / len(source_files) * 100
    else:
        test_ratio = 0.0

    if has_tests and test_ratio < 30:
        issues.append(
            {
                "type": "low_test_coverage",
                "severity": "high",
                "message": f"Only {test_ratio:.0f}% of source files have corresponding test files.",
                "file": None,
            }
        )
    elif has_tests and test_ratio < 60:
        issues.append(
            {
                "type": "medium_test_coverage",
                "severity": "medium",
                "message": f"{test_ratio:.0f}% of source files have tests. Consider increasing coverage.",
                "file": None,
            }
        )

    # ── 4. Comprobamos si pytest está configurado ─────────────────────────────
    has_pytest_config = any(
        [
            (root / "pytest.ini").exists(),
            (root / "pyproject.toml").exists()
            and "pytest" in (root / "pyproject.toml").read_text(errors="ignore"),
            (root / "setup.cfg").exists()
            and "pytest" in (root / "setup.cfg").read_text(errors="ignore"),
            (root / "conftest.py").exists(),
        ]
    )

    if not has_pytest_config and has_tests:
        issues.append(
            {
                "type": "no_pytest_config",
                "severity": "low",
                "message": "No pytest configuration found (pytest.ini, conftest.py, or pyproject.toml).",
                "file": None,
            }
        )

    # ── 5. Comprobamos si hay CI/CD que corra los tests ───────────────────────
    # Buscamos archivos de configuración de GitHub Actions o GitLab CI
    github_actions = (
        list((root / ".github" / "workflows").glob("*.yml"))
        if (root / ".github" / "workflows").exists()
        else []
    )
    gitlab_ci = (root / ".gitlab-ci.yml").exists()
    has_ci_cd = len(github_actions) > 0 or gitlab_ci

    if not has_ci_cd:
        issues.append(
            {
                "type": "no_ci_cd",
                "severity": "medium",
                "message": "No CI/CD configuration found. Tests are not run automatically on each commit.",
                "file": None,
            }
        )

    # ── 6. Detectamos funciones públicas sin test ─────────────────────────────
    # Extraemos funciones públicas del código fuente
    # (las que no empiezan por _ que son privadas por convención)
    public_functions = _extract_public_functions(source_files)

    # Extraemos funciones testeadas de los archivos de test
    # Buscamos funciones que empiecen por test_ y contengan el nombre de otra función
    tested_functions = _extract_tested_functions(test_files)

    # Comparamos — funciones públicas que no tienen test
    untested = [
        f for f in public_functions if not any(f.lower() in t.lower() for t in tested_functions)
    ]

    if len(untested) > 10:
        issues.append(
            {
                "type": "untested_functions",
                "severity": "medium",
                "message": f"{len(untested)} public functions have no corresponding test.",
                "file": None,
            }
        )

    # ── 7. Estimamos el nivel de cobertura general ────────────────────────────
    if not has_tests:
        coverage_estimate = "none"
    elif test_ratio >= 60 and has_pytest_config and has_ci_cd:
        coverage_estimate = "high"
    elif test_ratio >= 30:
        coverage_estimate = "medium"
    else:
        coverage_estimate = "low"

    return {
        "issues": issues,
        "has_tests": has_tests,
        "test_files": [Path(f).name for f in test_files],
        "source_files": [Path(f).name for f in source_files],
        "test_ratio": round(test_ratio, 1),
        "has_pytest_config": has_pytest_config,
        "has_ci_cd": has_ci_cd,
        "tested_functions": tested_functions,
        "untested_functions": untested[:20],  # limitamos a 20 para no saturar el informe
        "coverage_estimate": coverage_estimate,
    }


def _extract_public_functions(source_files: list[str]) -> list[str]:
    """
    Extrae los nombres de todas las funciones públicas de los archivos de código.
    Las funciones privadas empiezan por _ y las excluimos.
    """
    functions = []
    for file_path in source_files:
        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    # Excluimos funciones privadas (_ prefix) y dunder (__init__, etc.)
                    if not node.name.startswith("_"):
                        functions.append(node.name)
        except Exception:
            continue
    return functions


def _extract_tested_functions(test_files: list[str]) -> list[str]:
    """
    Extrae los nombres de las funciones de test.
    Convención pytest: las funciones de test empiezan por test_
    Ejemplo: test_analyze_files → está testeando analyze_files
    """
    tested = []
    for file_path in test_files:
        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    if node.name.startswith("test_"):
                        # Extraemos el nombre de la función testeada
                        # test_analyze_files → analyze_files
                        tested.append(node.name[5:])
        except Exception:
            continue
    return tested
