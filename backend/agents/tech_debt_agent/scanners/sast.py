import dataclasses
import json
import logging
import tempfile
import threading
from pathlib import Path

from backend.agents.tech_debt_agent.findings import Family, FamilyResult, Finding, Severity
from backend.agents.tech_debt_agent.tools import ToolTimeout, ToolUnavailable, run_tool

logger = logging.getLogger(__name__)

# Versión fijada; el Dockerfile (Task 14) debe instalar esta misma.
SEMGREP_VERSION = "1.163.0"
TIMEOUT_SECONDS = 300
RULE_TIMEOUT_SECONDS = 20
RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
FAMILIES = (Family.SAST, Family.ERRORS, Family.DEBUG, Family.AI_TELLS)
EXCLUDED = ("node_modules", "dist", "build", ".venv", "venv", "vendor", ".git")
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
        severity = SEVERITY[item["extra"]["severity"]]
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
    )


def _parse(repo_root: Path, data: object) -> list[Finding]:
    if not isinstance(data, dict):
        raise ValueError("forma inesperada")
    root = repo_root.resolve()
    findings: list[Finding] = []
    for item in data.get("results") or []:
        found = _finding(item)
        if found is None:
            continue
        path = Path(found.file)
        if path.is_absolute():
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            found = dataclasses.replace(found, file=rel)
        findings.append(found)
    return findings


def scan_sast(repo_root: Path, files: list[Path], cancel: threading.Event) -> list[FamilyResult]:
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
            "--timeout",
            str(RULE_TIMEOUT_SECONDS),
        ]
        for name in EXCLUDED:
            args += ["--exclude", name]
        try:
            run_tool(
                [*args, str(repo_root)],
                cwd=repo_root,
                timeout=TIMEOUT_SECONDS,
                cancel=cancel,
                ok_codes={0, 1},
            )
            findings = _parse(repo_root, json.loads(report.read_text(encoding="utf-8")))
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
    return [FamilyResult(f, "ok", None, [x for x in findings if x.family == f]) for f in FAMILIES]
