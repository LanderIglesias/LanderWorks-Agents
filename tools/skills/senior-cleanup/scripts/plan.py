"""Plan determinista de la skill senior-cleanup. Solo stdlib; Python 3.10+.

Subcomandos (todos imprimen JSON en stdout; salida 2 con PlanError):
  check REPORT   valida informe, repo, SHA, árbol limpio y rama de trabajo.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = 1
_SHA = re.compile(r"^[0-9a-f]{40}$")


class PlanError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"ok": False, "code": self.code, "message": self.message, "details": self.details}


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60)


def git(root: Path, *args: str) -> str:
    res = _run_git(root, *args)
    if res.returncode != 0:
        raise PlanError(
            "git_failed",
            f"git {' '.join(args)} falló: {res.stderr.strip()}",
            {"args": list(args), "stderr": res.stderr.strip()},
        )
    return res.stdout.rstrip()


def state_dir(root: Path) -> Path:
    return Path(git(root, "rev-parse", "--absolute-git-dir")) / "senior-cleanup"


def load_report(path: Path) -> dict:
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PlanError("bad_json", f"No se puede leer {path} como JSON: {e}") from e
    if not isinstance(report, dict) or report.get("schema_version") != SCHEMA_VERSION:
        raise PlanError(
            "bad_schema",
            f"El informe no tiene schema_version {SCHEMA_VERSION}. Descárgalo de nuevo desde la demo.",
        )
    sha = report.get("head_sha")
    if not isinstance(sha, str) or not _SHA.match(sha):
        raise PlanError(
            "bad_schema", "head_sha no es un SHA completo de 40 caracteres hex en minúscula."
        )
    families = report.get("families")
    if (
        not isinstance(report.get("repo"), str)
        or not isinstance(families, list)
        or not all(isinstance(f, dict) and isinstance(f.get("findings"), list) for f in families)
    ):
        raise PlanError("bad_schema", "Faltan repo o families[].findings[] en el informe.")
    return report


def _commit_date(root: Path, sha: str) -> str | None:
    res = _run_git(root, "show", "-s", "--format=%cs", sha, "--")
    if res.returncode != 0:
        return None  # el commit del informe no está en local
    return res.stdout.strip() or None


def _dirty_files(root: Path) -> list[str]:
    entries = iter(git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0"))
    files = []
    for entry in entries:
        if not entry:
            continue
        files.append(entry[3:])
        if entry[0] in "RC":  # con -z, la ruta origen del renombrado va en la entrada siguiente
            next(entries, None)
    return files


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def check(report_path: Path, cwd: Path) -> dict:
    report = load_report(report_path)
    if _run_git(cwd, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        raise PlanError("not_git", f"{cwd} no es un repositorio git.")
    root = Path(git(cwd, "rev-parse", "--show-toplevel"))
    head = git(root, "rev-parse", "HEAD")
    report_sha = report["head_sha"]
    branch = f"senior-cleanup/{report_sha[:7]}"
    state = state_dir(root)
    plan = _load_json(state / "plan.json")
    progress = _load_json(state / "progress.json")

    current = _run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if current == branch and plan is not None:
        # Retomar: HEAD ya avanzó con commits de lotes; el informe debe ser el del plan
        # y su commit, ancestro de HEAD.
        sha_ok = plan.get("report_sha") == report_sha and (
            _run_git(root, "merge-base", "--is-ancestor", report_sha, head).returncode == 0
        )
    else:
        sha_ok = report_sha == head
    if not sha_ok:
        raise PlanError(
            "sha_mismatch",
            "El informe se generó sobre otro commit. Vuelve a analizar el repo o haz checkout de ese commit.",
            {
                "report_sha": report_sha,
                "head_sha": head,
                "report_date": _commit_date(root, report_sha),
                "head_date": _commit_date(root, head),
            },
        )

    dirty = _dirty_files(root)
    if dirty:
        raise PlanError(
            "dirty_tree",
            "Hay cambios sin commitear. Haz commit o stash antes de empezar.",
            {"files": dirty},
        )

    branch_exists = (
        _run_git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
    )
    resume = branch_exists and progress is not None and isinstance(progress.get("batches"), dict)
    if branch_exists and not resume:
        raise PlanError(
            "branch_exists",
            f"La rama {branch} ya existe y no hay progreso guardado. Bórrala o renómbrala para empezar de cero.",
            {"branch": branch},
        )
    return {
        "ok": True,
        "repo_root": str(root),
        "head_sha": report_sha,
        "branch": branch,
        "resume_available": resume,
    }


AUTO_RULES_FAMILY4 = frozenset(
    {
        "except-pass-tragado",
        "except-print-tragado",
        "catch-vacio",
        "promise-catch-vacio",
        "error-expuesto-en-respuesta",
        "traceback-en-respuesta",
        "E722",
        "S110",
        "S112",
    }
)
_GHOST_FUNCTION_RULES = frozenset({"ghost-none", "ghost-trivial", "ghost-mock"})
_MAX_SNIPPET_LINES = 20


def head_files(root: Path) -> set[str]:
    return {p for p in git(root, "ls-files", "-z").split("\0") if p}


def _is_history(f: dict) -> bool:
    return str(f.get("rule") or "").startswith("history:")


def classify_location(root: Path, f: dict, files: set[str]) -> tuple[str, str | None]:
    path = f.get("file")
    if _is_history(f) or (f.get("family") == 1 and path not in files):
        return "history_only", None
    if path == ".":
        return "repo", None
    if not isinstance(path, str) or not path:
        return "rejected", "ruta vacía"
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return "rejected", "ruta absoluta"
    if "\\" in path:
        return "rejected", "ruta no normalizada (barra invertida)"
    if ".." in path.split("/"):
        return "rejected", "ruta con '..'"
    if path not in files:
        return "rejected", "el archivo no está en el commit analizado"
    if (root / path).is_symlink():
        return "rejected", "el archivo es un enlace simbólico"
    return ("line" if f.get("line_start") else "file"), None


def _function_lines(source: str, line: int) -> tuple[int, int] | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.lineno == line:
            return node.lineno, node.end_lineno
    return None


def capture_snippet(root: Path, f: dict) -> str | None:
    """Fragmento del código señalado; None para hallazgos sin línea, de repo o de historial."""
    start = f.get("line_start")
    path = f.get("file")
    if not start or path == "." or _is_history(f) or not (root / path).is_file():
        return None
    source = (root / path).read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines(keepends=True)
    if f.get("family") == 7 and path.endswith(".py") and f.get("rule") in _GHOST_FUNCTION_RULES:
        span = _function_lines(source, start)
        if span:
            return "".join(lines[span[0] - 1 : span[1]])
    end = min(f.get("line_end") or start, start + _MAX_SNIPPET_LINES - 1)
    return "".join(lines[start - 1 : end])


def mode_for(f: dict, kind: str) -> str:
    rule = f.get("rule")
    family = f.get("family")
    if rule is None:
        return "confirm"
    if family == 6:
        return "confirm" if rule == "debug-true" else "auto"
    if family == 7:
        return "confirm" if rule == "ghost-missing" or kind == "repo" else "auto"
    if family == 4 and (rule in AUTO_RULES_FAMILY4 or rule.startswith(("BLE", "express-"))):
        return "auto"
    return "confirm"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plan.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check", help="valida informe, repo y árbol de trabajo")
    p_check.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    try:
        out = check(args.report, Path.cwd())
    except PlanError as e:
        print(json.dumps(e.to_dict(), ensure_ascii=False))
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
