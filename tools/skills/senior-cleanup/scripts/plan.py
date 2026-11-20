"""Plan determinista de la skill senior-cleanup. Solo stdlib; Python 3.10+.

Subcomandos (todos imprimen JSON en stdout; salida 2 con PlanError):
  check REPORT              valida informe, repo, SHA, árbol limpio y rama de trabajo.
  plan REPORT               clasifica hallazgos y forma lotes; guarda plan.json y progress.json.
  mark ID STATUS [--note]   actualiza el estado de un lote.
  revert                    deshace los cambios sin commitear del lote en curso.

El estado vive en <git-dir>/senior-cleanup/, nunca en el árbol de trabajo.
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
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60)
    except OSError as e:  # git no instalado o cwd inexistente: error JSON, no traceback
        raise PlanError("git_failed", f"No se pudo ejecutar git en {root}: {e}") from e


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


MAX_AUTO_BATCH = 15
_AUTO_FAMILY_ORDER = (6, 4, 7)
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
STATUSES = frozenset({"applied", "reverted", "skipped", "kept_red", "not_located", "pending"})


def _sorted_findings(findings: list[dict]) -> list[dict]:
    """Por archivo y, dentro de cada archivo, de la última línea a la primera (sin línea al final)."""
    return sorted(
        findings,
        key=lambda f: (f["file"], f.get("line_start") is None, -(f.get("line_start") or 0)),
    )


def make_batches(items: list[dict]) -> list[dict]:
    items = [i for i in items if i["kind"] != "history_only"]
    groups: list[tuple[str, int, list[dict]]] = []

    for family in _AUTO_FAMILY_ORDER:
        by_file: dict[str, list[dict]] = {}
        for i in items:
            if i["mode"] == "auto" and i["family"] == family:
                by_file.setdefault(i["file"], []).append(i)
        current: list[dict] = []
        for file in sorted(by_file):
            findings = _sorted_findings(by_file[file])
            if current and len(current) + len(findings) > MAX_AUTO_BATCH:
                groups.append(("auto", family, current))
                current = []
            while len(findings) > MAX_AUTO_BATCH:  # solo un archivo que pasa del tope se parte
                groups.append(("auto", family, findings[:MAX_AUTO_BATCH]))
                findings = findings[MAX_AUTO_BATCH:]
            current += findings
        if current:
            groups.append(("auto", family, current))

    confirm: dict[tuple, list[dict]] = {}
    for n, i in enumerate(items):
        if i["mode"] == "confirm":
            key = (5, i["file"]) if i["family"] == 5 else ("solo", n)
            confirm.setdefault(key, []).append(i)
    ordered = sorted(
        confirm.values(),
        key=lambda fs: (min(_SEVERITY_RANK.get(f.get("severity"), 4) for f in fs), fs[0]["family"]),
    )
    groups += [("confirm", fs[0]["family"], fs) for fs in ordered]

    return [
        {"id": n, "mode": mode, "family": family, "findings": _sorted_findings(fs)}
        for n, (mode, family, fs) in enumerate(groups, start=1)
    ]


def detect_test_commands(root: Path) -> list[list[str]]:
    commands = []
    pyproject = root / "pyproject.toml"
    if (
        (root / "pytest.ini").is_file()
        or (root / "conftest.py").is_file()
        or (
            pyproject.is_file()
            and "[tool.pytest" in pyproject.read_text(encoding="utf-8", errors="replace")
        )
        or any((root / "tests").glob("**/test_*.py"))
    ):
        commands.append(["python", "-m", "pytest"])
    scripts = (_load_json(root / "package.json") or {}).get("scripts")
    test = scripts.get("test") if isinstance(scripts, dict) else None
    if isinstance(test, str) and test.strip() and "no test specified" not in test:
        commands.append(["npm", "test"])
    return commands


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_plan(report_path: Path, cwd: Path) -> dict:
    info = check(report_path, cwd)
    root = Path(info["repo_root"])
    state = state_dir(root)
    if info["resume_available"]:
        existing = _load_json(state / "plan.json")
        if existing is not None:
            return existing  # retomar: el plan y el progreso guardados mandan

    report = load_report(report_path)
    files = head_files(root)
    items, history_only, rejected = [], [], []
    for family in report["families"]:
        for f in family["findings"]:
            kind, reason = classify_location(root, f, files)
            if kind == "rejected":
                rejected.append({"file": f.get("file"), "title": f.get("title"), "reason": reason})
            elif kind == "history_only":
                history_only.append(f)
            else:
                items.append(
                    {
                        **f,
                        "kind": kind,
                        "mode": mode_for(f, kind),
                        "snippet": capture_snippet(root, f),
                    }
                )

    batches = make_batches(items)
    plan = {
        "report_sha": info["head_sha"],
        "repo": report["repo"],
        "branch": info["branch"],
        "batches": batches,
        "history_only": history_only,
        "rejected": rejected,
        "not_analyzed": report.get("not_analyzed", []),
        "test_commands": detect_test_commands(root),
    }
    state.mkdir(exist_ok=True)
    _write_json(state / "plan.json", plan)
    _write_json(
        state / "progress.json",
        {"batches": {str(b["id"]): {"status": "pending", "note": ""} for b in batches}},
    )
    return plan


def mark(cwd: Path, batch_id: int, status: str, note: str = "") -> dict:
    if status not in STATUSES:
        raise PlanError(
            "bad_status", f"Estado desconocido: {status}. Válidos: {', '.join(sorted(STATUSES))}."
        )
    path = state_dir(cwd) / "progress.json"
    progress = _load_json(path)
    if progress is None or not isinstance(progress.get("batches"), dict):
        raise PlanError("no_plan", "No hay progreso guardado. Ejecuta antes plan.py plan.")
    if str(batch_id) not in progress["batches"]:
        raise PlanError("bad_batch", f"El lote {batch_id} no está en el plan.")
    progress["batches"][str(batch_id)] = {"status": status, "note": note}
    _write_json(path, progress)
    return progress


def revert(cwd: Path) -> list[str]:
    """Deshace el lote en curso: restaura lo seguido y borra lo nuevo sin seguimiento (no lo ignorado)."""
    root = Path(git(cwd, "rev-parse", "--show-toplevel"))
    # git restore borra él mismo los archivos nuevos que estaban en el índice; se anotan antes.
    staged_new = [
        p
        for p in git(root, "diff", "--cached", "--name-only", "--diff-filter=A", "-z").split("\0")
        if p
    ]
    git(root, "restore", "--staged", "--worktree", "--", ".")
    removed = [p for p in staged_new if not (root / p).exists()]
    status = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    for entry in status.split("\0"):
        if not entry.startswith("?? "):
            continue
        rel = entry[3:]
        path = root / rel
        if path.is_dir() and not path.is_symlink():
            continue  # repo anidado: no se toca
        path.unlink()
        removed.append(rel)
        for parent in path.parents:
            if parent == root or any(parent.iterdir()):
                break
            parent.rmdir()
    return sorted(removed)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(
        encoding="utf-8"
    )  # en Windows la tubería usa cp1252 y no cabe el código del repo
    parser = argparse.ArgumentParser(prog="plan.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check", help="valida informe, repo y árbol de trabajo")
    p_check.add_argument("report", type=Path)
    p_plan = sub.add_parser("plan", help="valida, clasifica y forma los lotes; guarda plan.json")
    p_plan.add_argument("report", type=Path)
    p_mark = sub.add_parser("mark", help="actualiza el estado de un lote en progress.json")
    p_mark.add_argument("batch_id", type=int)
    p_mark.add_argument("status", choices=sorted(STATUSES))
    p_mark.add_argument("--note", default="")
    sub.add_parser("revert", help="deshace los cambios sin commitear del lote en curso")
    args = parser.parse_args(argv)
    cwd = Path.cwd()
    try:
        if args.command == "check":
            out = check(args.report, cwd)
        elif args.command == "plan":
            out = build_plan(args.report, cwd)
        elif args.command == "mark":
            out = mark(cwd, args.batch_id, args.status, args.note)
        else:
            out = {"ok": True, "removed": revert(cwd)}
    except PlanError as e:
        print(json.dumps(e.to_dict(), ensure_ascii=False))
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
