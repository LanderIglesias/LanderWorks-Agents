"""
fix_imports.py
Arregla los imports que quedaron sin actualizar tras la reorganizacion.
Ejecutar desde la raiz del proyecto: python scripts/fix_imports.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REPLACEMENTS = [
    # scaffold: apps -> agents (imports normales Y strings de monkeypatch)
    ("backend.apps.scaffold_web_agent.", "backend.agents.scaffold_web_agent."),
    # dental: imports absolutos que quedaron sin actualizar
    ("from backend.twilio_worker import", "from backend.agents.dental_agent.twilio_worker import"),
    ("import backend.twilio_worker", "import backend.agents.dental_agent.twilio_worker"),
    ("from backend.agent import", "from backend.agents.dental_agent.agent import"),
    ("from backend.store import", "from backend.agents.dental_agent.store import"),
    ("import backend.store as store", "import backend.agents.dental_agent.store as store"),
    ("from backend.notify import", "from backend.agents.dental_agent.notify import"),
    ("import backend.notify as notify", "import backend.agents.dental_agent.notify as notify"),
    ("from backend.config import", "from backend.agents.dental_agent.config import"),
    ("from backend import tools", "from backend.agents.dental_agent import tools"),
    ("from backend.tools import", "from backend.agents.dental_agent.tools import"),
]

# Archivos a procesar
TARGET_DIRS = [
    ROOT / "tests",
    ROOT / "backend",
]

EXTENSIONS = {".py"}


def fix_file(path: Path) -> bool:
    """Aplica los reemplazos a un fichero. Devuelve True si cambió algo."""
    original = path.read_text(encoding="utf-8")
    content = original

    for old, new in REPLACEMENTS:
        content = content.replace(old, new)

    if content != original:
        path.write_text(content, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed = []
    skipped = []

    for target_dir in TARGET_DIRS:
        for path in sorted(target_dir.rglob("*.py")):
            # No tocar __pycache__
            if "__pycache__" in path.parts:
                continue
            try:
                if fix_file(path):
                    changed.append(path.relative_to(ROOT))
                else:
                    skipped.append(path.relative_to(ROOT))
            except Exception as e:
                print(f"  ERROR en {path}: {e}")

    print(f"\nArchivos modificados ({len(changed)}):")
    for p in changed:
        print(f"  ✓ {p}")

    print(f"\nArchivos sin cambios: {len(skipped)}")
    print("\nListo. Ahora ejecuta: pytest tests/ -v")


if __name__ == "__main__":
    main()
