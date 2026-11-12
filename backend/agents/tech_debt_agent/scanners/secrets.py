import json
import logging
import tempfile
import threading
from pathlib import Path

from backend.agents.tech_debt_agent.findings import Family, FamilyResult, Finding, Severity
from backend.agents.tech_debt_agent.tools import ToolTimeout, ToolUnavailable, run_tool

logger = logging.getLogger(__name__)

# Versión fijada; el Dockerfile (Task 14) debe instalar esta misma.
GITLEAKS_VERSION = "8.18.4"
TIMEOUT_SECONDS = 120


def _not_analyzed(reason: str) -> list[FamilyResult]:
    return [FamilyResult(Family.SECRETS, "not_analyzed", reason)]


def scan_secrets(repo_root: Path, files: list[Path], cancel: threading.Event) -> list[FamilyResult]:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "gitleaks.json"
        try:
            run_tool(
                [
                    "gitleaks",
                    "detect",
                    "--source",
                    str(repo_root),
                    "--report-format",
                    "json",
                    "--report-path",
                    str(report),
                    "--redact",
                    "--no-banner",
                ],
                cwd=repo_root,
                timeout=TIMEOUT_SECONDS,
                cancel=cancel,
                ok_codes={0, 1},
            )
            leaks = json.loads(report.read_text(encoding="utf-8")) if report.exists() else []
        except ToolUnavailable:
            return _not_analyzed("Escáner de secretos no disponible")
        except ToolTimeout:
            return _not_analyzed("El escáner de secretos agotó el tiempo")
        except (RuntimeError, ValueError, OSError):
            logger.exception("gitleaks falló")
            return _not_analyzed("El escáner de secretos falló")

    findings: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()
    for leak in leaks:
        # Solo se leen campos no sensibles; Secret y Match nunca se copian.
        rel = str(leak.get("File", "")).replace("\\", "/")
        line = leak.get("StartLine")
        rule = str(leak.get("RuleID", ""))
        if not rel or (rel, line, rule) in seen:
            continue
        seen.add((rel, line, rule))
        in_head = (repo_root / rel).is_file()
        why = (
            "Hay una credencial en el historial de git."
            if in_head
            else "La credencial ya no está en el código actual pero sigue en el historial de git."
        )
        findings.append(
            Finding(
                family=Family.SECRETS,
                severity=Severity.CRITICAL,
                file=rel,
                line_start=line,
                line_end=leak.get("EndLine", line),
                title=f"Secreto expuesto ({rule})",
                why=f"{why} Cualquiera con acceso al repo puede leerla: hay que rotar la clave.",
                fix="Rota la clave en el proveedor, muévela a una variable de entorno y purga el historial si el repo es público.",
                source="gitleaks",
            )
        )
    return [FamilyResult(Family.SECRETS, "ok", None, findings)]
