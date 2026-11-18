import dataclasses
import json
import logging
import tempfile
import threading
from pathlib import Path

from backend.agents.tech_debt_agent.findings import Family, FamilyResult, Finding, Severity
from backend.agents.tech_debt_agent.repo_fetcher import EXCLUDED_DIRS, MAX_FILE_BYTES
from backend.agents.tech_debt_agent.tools import ToolTimeout, ToolUnavailable, run_tool

logger = logging.getLogger(__name__)

# Versión fijada; el Dockerfile (Task 14) debe instalar esta misma.
SEMGREP_VERSION = "1.163.0"
TIMEOUT_SECONDS = 300
RULE_TIMEOUT_SECONDS = 20
RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
FAMILIES = (Family.SAST, Family.ERRORS, Family.DEBUG, Family.AI_TELLS)
SEVERITY = {"ERROR": Severity.HIGH, "WARNING": Severity.MEDIUM, "INFO": Severity.LOW}


def _not_analyzed(reason: str) -> list[FamilyResult]:
    return [FamilyResult(f, "not_analyzed", reason) for f in FAMILIES]


def _finding(item: dict) -> Finding | None:
    meta = item["extra"]["metadata"]
    family = Family(int(meta["family"]))
    if family not in FAMILIES:
        return None
    if meta.get("critical") is True:
        severity = Severity.CRITICAL
    else:
        severity = SEVERITY.get(item["extra"]["severity"], Severity.LOW)
    return Finding(
        family=family,
        severity=severity,
        file=Path(str(item["path"])).as_posix(),
        line_start=int(item["start"]["line"]),
        line_end=int(item["end"]["line"]),
        title=str(item["extra"]["message"]),
        why=str(meta["why"]),
        fix=str(meta["fix"]),
        source="semgrep",
        rule=str(item["check_id"]).rsplit(".", 1)[-1],
    )


def _parse(repo_root: Path, data: object) -> list[Finding]:
    if not isinstance(data, dict):
        raise ValueError("forma inesperada")
    root = repo_root.resolve()
    findings: list[Finding] = []
    items = data.get("results") or []
    bad = 0
    for item in items:
        try:
            found = _finding(item)
            if found is not None and Path(found.file).is_absolute():
                rel = Path(found.file).resolve().relative_to(root).as_posix()
                found = dataclasses.replace(found, file=rel)
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            # Ruta fuera del repo o item ilegible: se descarta ese resultado.
            bad += 1
            continue
        if found is not None:
            findings.append(found)
    if bad:
        logger.warning("semgrep: %s resultados descartados por forma inesperada", bad)
        if not findings and bad == len(items):
            raise ValueError("todos los resultados de semgrep son ilegibles")
    return findings


def _failed_files(data: dict) -> int:
    # Errores de parseo o de tiempo por archivo (semgrep los marca "warn" o "error").
    paths = set()
    for err in data.get("errors") or []:
        if isinstance(err, dict) and err.get("path"):
            logger.warning("semgrep: %s", str(err.get("message", ""))[:300])
            paths.add(str(err["path"]))
    scanned = (data.get("paths") or {}).get("scanned") or []
    if paths and len(paths) >= len(scanned):
        raise ValueError("semgrep no pudo analizar ningún archivo")
    return len(paths)


def scan_sast(repo_root: Path, files: list[Path], cancel: threading.Event) -> list[FamilyResult]:
    # `files` se ignora: semgrep recorre repo_root con las mismas carpetas excluidas y el mismo
    # tope de tamaño que list_source_files; a propósito sí analiza .min.js.
    with tempfile.TemporaryDirectory() as tmp_name:
        report = Path(tmp_name) / "semgrep.json"
        args = [
            "semgrep",
            "scan",
            # Solo reglas vendorizadas: nunca el registro (--config auto / p/...).
            "--config",
            str(RULES_DIR),
            "--json",
            "--output",
            str(report),
            "--metrics=off",
            "--disable-version-check",
            # Un .semgrepignore del repo analizado no puede ocultar hallazgos.
            "--x-ignore-semgrepignore-files",
            "--timeout",
            str(RULE_TIMEOUT_SECONDS),
            "--max-target-bytes",
            str(MAX_FILE_BYTES),
        ]
        for name in sorted(EXCLUDED_DIRS):
            args += ["--exclude", name]
        try:
            run_tool(
                [*args, str(repo_root)],
                cwd=repo_root,
                timeout=TIMEOUT_SECONDS,
                cancel=cancel,
                ok_codes={0, 1},
            )
            data = json.loads(report.read_text(encoding="utf-8"))
            findings = _parse(repo_root, data)
            failed = _failed_files(data)
        except ToolUnavailable:
            return _not_analyzed("Escáner SAST no disponible")
        except ToolTimeout:
            return _not_analyzed("El escáner SAST agotó el tiempo")
        except (RuntimeError, OSError):
            logger.exception("semgrep falló")
            return _not_analyzed("El escáner SAST falló")
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            logger.exception("salida de semgrep inesperada")
            return _not_analyzed("El escáner SAST falló")
    reason = f"análisis parcial: {failed} archivos no se pudieron analizar" if failed else None
    return [FamilyResult(f, "ok", reason, [x for x in findings if x.family == f]) for f in FAMILIES]
