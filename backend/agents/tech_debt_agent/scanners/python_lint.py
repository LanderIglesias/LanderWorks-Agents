import json
import logging
import threading
from pathlib import Path

from backend.agents.tech_debt_agent.findings import Family, FamilyResult, Finding, Severity
from backend.agents.tech_debt_agent.tools import (
    ToolTimeout,
    ToolUnavailable,
    chunk_args,
    find_executable,
    run_tool,
)

logger = logging.getLogger(__name__)

# Versión fijada; el Dockerfile (Task 14) debe instalar esta misma.
RUFF_VERSION = "0.17.4"
TIMEOUT_SECONDS = 120
FAMILIES = (Family.SAST, Family.ERRORS, Family.DEBUG)
SELECT = "S,BLE,T20,E722,ERA001"
CRITICAL = {"S307", "S602", "S608"}
HIGH = {
    "S102", "S105", "S106", "S107", "S301", "S302", "S306", "S324", "S501", "S506", "S507",
    "S604", "S605", "S701",
}  # fmt: skip
# S101 (assert) es ruido: los tests lo usan por diseño.
SKIPPED = {"S101"}
ERROR_CODES = {"E722", "S110", "S112"}

_WHY = {
    Family.SAST: "Patrón inseguro detectado por análisis estático que puede ser explotable.",
    Family.ERRORS: "Captura de excepciones demasiado amplia o silenciada: oculta fallos reales.",
    Family.DEBUG: "Residuo de depuración o código comentado que no debería llegar a producción.",
}
_FIX = {
    Family.SAST: "Sustituye la construcción insegura por una alternativa segura (consultas parametrizadas, sin eval/shell).",
    Family.ERRORS: "Captura excepciones concretas y registra o propaga el error.",
    Family.DEBUG: "Elimina la traza o el código comentado; usa logging si hace falta.",
}


def _not_analyzed(reason: str) -> list[FamilyResult]:
    return [FamilyResult(f, "not_analyzed", reason) for f in FAMILIES]


def _classify(code: str) -> tuple[Family, Severity]:
    if code in ERROR_CODES or code.startswith("BLE"):
        return Family.ERRORS, Severity.MEDIUM
    if code.startswith("T20") or code == "ERA001":
        return Family.DEBUG, Severity.LOW
    if code in CRITICAL:
        return Family.SAST, Severity.CRITICAL
    return Family.SAST, Severity.HIGH if code in HIGH else Severity.MEDIUM


def _relative(root: Path, name: str) -> str | None:
    path = Path(name)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


def _parse(root: Path, data: object) -> list[Finding]:
    if not isinstance(data, list):
        raise ValueError("forma inesperada")
    findings: list[Finding] = []
    for item in data:
        code = item["code"]
        if code is None or code in SKIPPED:
            continue
        code = str(code)
        rel = _relative(root, str(item["filename"]))
        if rel is None:
            continue
        family, severity = _classify(code)
        start = int(item["location"]["row"])
        end = int(item["end_location"]["row"])
        findings.append(
            Finding(
                family=family,
                severity=severity,
                file=rel,
                line_start=start,
                line_end=max(start, end),
                title=f"{code}: {item['message']}",
                why=_WHY[family],
                fix=_FIX[family],
                source="ruff",
            )
        )
    return findings


def _python_files(root: Path, files: list[Path]) -> list[str]:
    out: list[str] = []
    for f in files:
        if f.suffix != ".py":
            continue
        rel = _relative(root, str(f))
        if rel is not None:
            # "./" evita que un nombre que empiece por "-" se lea como opción.
            out.append(f"./{rel}")
    return out


def scan_python_lint(
    repo_root: Path, files: list[Path], cancel: threading.Event
) -> list[FamilyResult]:
    root = repo_root.resolve()
    targets = _python_files(root, files)
    if not targets:
        return _not_analyzed("sin archivos Python")
    exe = find_executable("ruff")
    if exe is None:
        return _not_analyzed("Escáner Python no disponible")
    findings: list[Finding] = []
    try:
        for chunk in chunk_args(targets):
            out = run_tool(
                [
                    exe,
                    "check",
                    "--no-cache",
                    # Ignora la config del repo analizado y sus comentarios de supresión: un repo hostil
                    # no debe poder apagar reglas.
                    "--isolated",
                    "--ignore-noqa",
                    "--output-format",
                    "json",
                    "--select",
                    SELECT,
                    *chunk,
                ],
                cwd=root,
                timeout=TIMEOUT_SECONDS,
                cancel=cancel,
                ok_codes={0, 1},
            )
            findings += _parse(root, json.loads(out))
    except ToolUnavailable:
        return _not_analyzed("Escáner Python no disponible")
    except ToolTimeout:
        return _not_analyzed("El escáner Python agotó el tiempo")
    except (RuntimeError, OSError):
        logger.exception("ruff falló")
        return _not_analyzed("El escáner Python falló")
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        logger.exception("salida de ruff inesperada")
        return _not_analyzed("El escáner Python falló")
    return [FamilyResult(f, "ok", None, [x for x in findings if x.family == f]) for f in FAMILIES]
