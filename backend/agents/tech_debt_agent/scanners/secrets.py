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


def _leaks(repo_root: Path, tmp: Path, name: str, extra: list[str], cancel) -> list[dict]:
    report = tmp / f"{name}.json"
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
            "--exit-code",
            "2",
            # Config e ignore propios: un .gitleaks.toml o .gitleaksignore del repo analizado no puede silenciar hallazgos.
            "--config",
            str(tmp / "gitleaks.toml"),
            "--gitleaks-ignore-path",
            str(tmp / "sin-ignore"),
            "--ignore-gitleaks-allow",
            *extra,
        ],
        cwd=repo_root,
        timeout=TIMEOUT_SECONDS,
        cancel=cancel,
        ok_codes={0, 2},
    )
    leaks = json.loads(report.read_text(encoding="utf-8"))
    if not isinstance(leaks, list) or not all(isinstance(x, dict) for x in leaks):
        raise ValueError("informe de gitleaks inesperado")
    return leaks


def _key(leak: dict, root: Path) -> tuple[str, str]:
    path = Path(str(leak.get("File", "")))
    if path.is_absolute():
        # Con --no-git gitleaks informa rutas absolutas.
        try:
            path = path.resolve().relative_to(root.resolve())
        except ValueError:
            pass
    return path.as_posix(), str(leak.get("RuleID", ""))


def scan_secrets(repo_root: Path, files: list[Path], cancel: threading.Event) -> list[FamilyResult]:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        (tmp / "gitleaks.toml").write_text("[extend]\nuseDefault = true\n", encoding="utf-8")
        (tmp / "sin-ignore").mkdir()
        try:
            leaks = _leaks(repo_root, tmp, "history", [], cancel)
            current = {
                _key(x, repo_root) for x in _leaks(repo_root, tmp, "tree", ["--no-git"], cancel)
            }
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
        rel, rule = _key(leak, repo_root)
        line = leak.get("StartLine")
        if rel in ("", ".") or (rel, line, rule) in seen:
            continue
        seen.add((rel, line, rule))
        if (rel, rule) in current:
            why = "Hay una credencial en el código actual del repo. Cualquiera con acceso puede leerla: rótala."
        else:
            why = "La credencial ya no está en el código actual, solo en el historial de git; sigue expuesta, rótala."
        findings.append(
            Finding(
                family=Family.SECRETS,
                severity=Severity.CRITICAL,
                file=rel,
                line_start=line,
                line_end=leak.get("EndLine", line),
                title=f"Secreto expuesto ({rule})",
                why=why,
                fix="Rota la clave en el proveedor, muévela a una variable de entorno y purga el historial si el repo es público.",
                source="gitleaks",
            )
        )
    return [FamilyResult(Family.SECRETS, "ok", None, findings)]
