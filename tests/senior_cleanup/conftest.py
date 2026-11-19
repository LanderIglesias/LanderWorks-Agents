import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "tools" / "skills" / "senior-cleanup" / "scripts"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=60
    ).stdout.strip()


@pytest.fixture
def make_repo(tmp_path: Path):
    """Factoría: repo git con app.py de 30 líneas y un commit."""
    if shutil.which("git") is None:
        pytest.skip("git no disponible")
    count = 0

    def _make() -> Path:
        nonlocal count
        count += 1
        repo = tmp_path / f"repo{count}"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "fixture")
        git(repo, "config", "user.email", "fixture@example.com")
        git(repo, "config", "commit.gpgsign", "false")
        git(repo, "config", "core.autocrlf", "false")
        (repo / "app.py").write_text("".join(f"x{i} = {i}\n" for i in range(1, 31)))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "initial")
        return repo

    return _make


@pytest.fixture
def write_report(tmp_path: Path):
    """Escribe un report.json válido fuera del repo; overrides sustituyen claves de primer nivel."""
    count = 0

    def _write(repo: Path, findings: list[dict], **overrides) -> Path:
        nonlocal count
        count += 1
        report = {
            "schema_version": 1,
            "repo": "o/r",
            "head_sha": git(repo, "rev-parse", "HEAD"),
            "families": [{"id": 6, "name": "Debug", "status": "ok", "findings": findings}],
            "not_analyzed": [],
        }
        report.update(overrides)
        path = tmp_path / f"report{count}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def load_script():
    def _load(name: str):
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load
