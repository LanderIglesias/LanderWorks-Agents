import shutil
import subprocess
from pathlib import Path

import pytest

from backend.agents.tech_debt_agent.findings import Family

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "vibe_repo"

# Rutas relativas a la raíz del fixture, con "/". app/config.py solo existe en el repo
# generado por vibe_repo (historial git), no en el directorio de fixtures.
PLANTED: dict[Family, list[tuple[str, int]]] = {
    Family.SECRETS: [("app/config.py", 2)],
    Family.SAST: [
        ("app/main.py", 9),
        ("app/main.py", 17),
        ("app/utils.py", 8),
        ("app/utils.py", 13),
        ("app/utils.py", 18),
        ("web/src/App.tsx", 20),
    ],
    Family.CVE: [
        ("requirements.txt", 1),
        ("requirements.txt", 2),
        ("requirements.txt", 3),
        ("web/package-lock.json", 14),
    ],
    Family.ERRORS: [
        ("app/main.py", 19),
        ("app/utils.py", 24),
        ("web/src/App.tsx", 15),
    ],
    Family.MONOLITH: [
        ("app/god_module.py", 1),
        ("app/god_module.py", 30),
        ("app/god_module.py", 4),
        ("app/god_module.py", 58),
    ],
    Family.DEBUG: [
        ("app/main.py", 6),
        ("app/main.py", 14),
        ("web/src/App.tsx", 18),
    ],
    Family.GHOST_TESTS: [
        ("tests/test_ghost.py", 6),
        ("tests/test_ghost.py", 10),
        ("tests/test_ghost.py", 14),
        ("web/src/App.test.tsx", 4),
    ],
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def vibe_repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git no disponible")
    repo = tmp_path / "vibe_repo"
    shutil.copytree(FIXTURE_DIR, repo)
    # El literal nunca vive en el repo: se construye en tiempo de test.
    key = "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc"
    config = repo / "app" / "config.py"
    config.write_text(f'"""Configuracion."""\nSTRIPE_KEY = "{key}"\n', encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    config.unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "remove key")
    return repo
