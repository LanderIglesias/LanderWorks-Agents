"""
dependency_scanner.py — Nodo 3 del Technical Debt Analyzer

Responsabilidad: analizar las dependencias del proyecto para detectar:
- Dependencias sin versión fijada (riesgo de deploys no reproducibles)
- Dependencias desactualizadas (comparando con PyPI)
- Dependencias declaradas pero no usadas en el código
- Ausencia de archivo de dependencias

Usa:
- pathlib    → leer requirements.txt y pyproject.toml
- ast        → detectar imports en el código para cruzar con requirements
- httpx      → consultar la API de PyPI para ver versiones actuales
- packaging  → parsear y comparar versiones de paquetes
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import httpx
from packaging.version import InvalidVersion, Version


def scan_dependencies(repo_path: str, python_files: list[str]) -> dict:
    """
    Analiza las dependencias del proyecto y devuelve los problemas encontrados.

    Args:
        repo_path: ruta raíz del repositorio clonado
        python_files: lista de archivos .py para detectar imports usados

    Returns:
        {
            "issues": list[dict],           # problemas encontrados
            "dependencies_found": list[str], # dependencias declaradas
            "unpinned": list[str],          # dependencias sin versión fija
            "outdated": list[dict],         # dependencias desactualizadas
            "unused": list[str],            # dependencias no usadas en el código
            "has_requirements": bool,       # si existe requirements.txt
        }
    """
    root = Path(repo_path)
    issues = []

    # ── 1. Buscamos el archivo de dependencias ────────────────────────────────
    requirements_path = root / "requirements.txt"
    pyproject_path = root / "pyproject.toml"

    if not requirements_path.exists() and not pyproject_path.exists():
        return {
            "issues": [
                {
                    "type": "no_requirements",
                    "severity": "high",
                    "message": "No requirements.txt or pyproject.toml found. Dependencies are not documented.",
                    "file": None,
                }
            ],
            "dependencies_found": [],
            "unpinned": [],
            "outdated": [],
            "unused": [],
            "has_requirements": False,
        }

    # ── 2. Parseamos las dependencias declaradas ──────────────────────────────
    dependencies = []
    if requirements_path.exists():
        dependencies = _parse_requirements(requirements_path)
    elif pyproject_path.exists():
        dependencies = _parse_pyproject(pyproject_path)

    # ── 3. Detectamos dependencias sin versión fija ───────────────────────────
    unpinned = []
    for dep in dependencies:
        # Una dependencia está fijada si tiene == en la versión
        # Ejemplo: fastapi==0.115.6 está fijada, fastapi o fastapi>=0.100 no lo está
        if "==" not in dep:
            unpinned.append(dep)
            issues.append(
                {
                    "type": "unpinned_dependency",
                    "severity": "medium",
                    "message": f"Dependency '{dep}' has no fixed version (==). Deploys may not be reproducible.",
                    "file": "requirements.txt",
                }
            )

    # ── 4. Detectamos dependencias desactualizadas consultando PyPI ───────────
    outdated = _check_outdated(dependencies)
    for dep in outdated:
        issues.append(
            {
                "type": "outdated_dependency",
                "severity": "medium",
                "message": f"'{dep['name']}' is outdated: installed {dep['current']}, latest {dep['latest']}",
                "file": "requirements.txt",
            }
        )

    # ── 5. Detectamos dependencias no usadas en el código ────────────────────
    used_imports = _extract_imports(python_files)
    unused = _find_unused(dependencies, used_imports)
    for dep in unused:
        issues.append(
            {
                "type": "unused_dependency",
                "severity": "low",
                "message": f"'{dep}' is declared but no import found in the codebase. May be unused.",
                "file": "requirements.txt",
            }
        )

    return {
        "issues": issues,
        "dependencies_found": dependencies,
        "unpinned": unpinned,
        "outdated": outdated,
        "unused": unused,
        "has_requirements": True,
    }


def _parse_requirements(path: Path) -> list[str]:
    """
    Lee requirements.txt y devuelve la lista de dependencias.
    Ignora comentarios (#) y líneas vacías.
    """
    deps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("-"):
            deps.append(line)
    return deps


def _parse_pyproject(path: Path) -> list[str]:
    """
    Lee pyproject.toml y extrae las dependencias de la sección
    [tool.poetry.dependencies] o [project].
    Parsing básico sin librerías externas de TOML.
    """
    deps = []
    content = path.read_text(encoding="utf-8")
    # Buscamos líneas que parecen dependencias (nombre = "versión")
    pattern = re.compile(r'^(\w[\w\-]*)\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
    for match in pattern.finditer(content):
        name, version = match.group(1), match.group(2)
        if name not in ("name", "version", "python", "description"):
            deps.append(f"{name}=={version}" if version != "*" else name)
    return deps


def _check_outdated(dependencies: list[str]) -> list[dict]:
    """
    Consulta la API de PyPI para ver si hay versiones más nuevas.
    Solo comprueba dependencias con versión fija (==).
    """
    outdated = []

    for dep in dependencies:
        if "==" not in dep:
            continue

        # Separamos nombre y versión: "fastapi==0.115.6" → ("fastapi", "0.115.6")
        parts = dep.split("==")
        if len(parts) != 2:
            continue

        name, current_version = parts[0].strip(), parts[1].strip()

        try:
            # Consultamos la API pública de PyPI
            response = httpx.get(
                f"https://pypi.org/pypi/{name}/json",
                timeout=5.0,
            )
            if response.status_code != 200:
                continue

            latest_version = response.json()["info"]["version"]

            # Comparamos versiones con packaging.version
            try:
                if Version(latest_version) > Version(current_version):
                    outdated.append(
                        {
                            "name": name,
                            "current": current_version,
                            "latest": latest_version,
                        }
                    )
            except InvalidVersion:
                continue

        except Exception:
            # Si falla la consulta (sin internet, timeout, etc.) seguimos
            continue

    return outdated


def _extract_imports(python_files: list[str]) -> set[str]:
    """
    Extrae todos los nombres de módulos importados en el código.
    Ejemplo: "import fastapi" → {"fastapi"}
             "from langchain import X" → {"langchain"}
    """
    imports = set()

    for file_path in python_files:
        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)

            for node in ast.walk(tree):
                # import fastapi → node.names[0].name = "fastapi"
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        # Tomamos solo el módulo raíz: "langchain.chat_models" → "langchain"
                        imports.add(alias.name.split(".")[0])

                # from fastapi import FastAPI → node.module = "fastapi"
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split(".")[0])

        except Exception:
            continue

    return imports


def _find_unused(dependencies: list[str], used_imports: set[str]) -> list[str]:
    """
    Compara las dependencias declaradas con los imports encontrados en el código.
    Devuelve las dependencias que no aparecen en ningún import.

    Nota: es una detección aproximada. Algunos paquetes tienen nombres distintos
    en PyPI y en el import (ejemplo: Pillow se importa como PIL).
    """
    # Mapa de paquetes PyPI → nombre de import real
    # Algunos paquetes tienen nombres distintos en PyPI y en el import
    KNOWN_ALIASES = {
        "pillow": "PIL",
        "opencv-python": "cv2",
        "scikit-learn": "sklearn",
        "python-dotenv": "dotenv",
        "pyyaml": "yaml",
        "beautifulsoup4": "bs4",
        "psycopg2-binary": "psycopg2",
        "langchain-community": "langchain_community",
        "langchain-openai": "langchain_openai",
        "langchain-anthropic": "langchain_anthropic",
    }

    unused = []
    for dep in dependencies:
        # Extraemos el nombre del paquete sin versión
        name = re.split(r"[=><!\[]", dep)[0].strip().lower()

        # Buscamos el nombre de import real
        import_name = KNOWN_ALIASES.get(name, name.replace("-", "_"))

        # Si no encontramos el import en el código, es posiblemente no usado
        if import_name not in {i.lower() for i in used_imports}:
            unused.append(name)

    return unused
