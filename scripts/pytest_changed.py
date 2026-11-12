"""Hook de pre-commit: ejecuta solo los tests afectados por los archivos staged.

La suite completa tarda ~25 min (tests de integración de todos los agentes),
así que en local se acota por agente; la CI sigue ejecutando la suite entera
en cada PR. Un cambio en código compartido (backend fuera de un agente con
carpeta de tests, conftest, config de pytest, dependencias) ejecuta la suite
completa: preferimos lento a dejar pasar una rotura.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FULL_SUITE = "FULL"
SHARED_FILES = {
    "pytest.ini",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "tests/conftest.py",
}


def select_targets(changed: list[str], root: Path) -> list[str] | str:
    """Devuelve las rutas de tests a ejecutar, o FULL_SUITE."""
    targets: set[str] = set()
    for raw in changed:
        path = raw.replace("\\", "/")
        parts = path.split("/")
        if path in SHARED_FILES:
            return FULL_SUITE
        if path == "scripts/pytest_changed.py":
            targets.add("tests/test_pytest_changed.py")
            continue
        if parts[0] == "tests" and len(parts) > 1:
            if len(parts) > 2:
                targets.add("/".join(parts[:2]))
            elif path.endswith(".py"):
                targets.add(path)
            continue
        if parts[:2] == ["backend", "agents"] and len(parts) > 3:
            agent_tests = f"tests/{parts[2]}"
            if (root / agent_tests).is_dir():
                targets.add(agent_tests)
                continue
            return FULL_SUITE
        if parts[0] == "backend" and path.endswith(".py"):
            return FULL_SUITE
    return sorted(targets)


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    targets = select_targets(argv, root)
    if targets == []:
        print("pytest_changed: ningún test afectado")
        return 0
    args = [] if targets == FULL_SUITE else list(targets)
    print(f"pytest_changed: {' '.join(args) or 'suite completa'}")
    return subprocess.call([sys.executable, "-m", "pytest", "-q", *args], cwd=root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
