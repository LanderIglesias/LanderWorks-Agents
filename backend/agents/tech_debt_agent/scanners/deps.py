import json
import logging
import tempfile
import threading
from pathlib import Path

from backend.agents.tech_debt_agent.findings import Family, FamilyResult, Finding, Severity
from backend.agents.tech_debt_agent.tools import ToolTimeout, ToolUnavailable, run_tool

logger = logging.getLogger(__name__)

# Versión fijada (CLI v2: `scan source -r`); el Dockerfile (Task 14) debe instalar esta misma.
OSV_SCANNER_VERSION = "2.7.1"
TIMEOUT_SECONDS = 180
DEFAULT_SCORE = 5.0
NO_PACKAGES_EXIT = 128


def _not_analyzed(reason: str) -> list[FamilyResult]:
    return [FamilyResult(Family.CVE, "not_analyzed", reason)]


def _severity(score: float) -> Severity:
    if score >= 9:
        return Severity.CRITICAL
    if score >= 7:
        return Severity.HIGH
    if score >= 4:
        return Severity.MEDIUM
    return Severity.LOW


def _score(group: dict) -> float:
    try:
        return float(group["max_severity"])
    except (KeyError, TypeError, ValueError):
        return DEFAULT_SCORE


def _line_of(manifest: Path, name: str) -> int | None:
    # Es un grep barato: en lockfiles puede apuntar a otra aparición del nombre.
    needle = name.lower()
    try:
        for n, line in enumerate(
            manifest.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if needle in line.lower():
                return n
    except OSError:
        pass
    return None


def scan_deps(repo_root: Path, files: list[Path], cancel: threading.Event) -> list[FamilyResult]:
    # osv-scanner consulta osv.dev: sin red falla y la familia queda not_analyzed.
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "osv-scanner.toml"
        config.write_text("", encoding="utf-8")
        try:
            out = run_tool(
                [
                    "osv-scanner",
                    "scan",
                    "source",
                    "--format",
                    "json",
                    # Config propia: un osv-scanner.toml del repo analizado no puede ignorar CVEs.
                    "--config",
                    str(config),
                    "-r",
                    str(repo_root),
                ],
                cwd=repo_root,
                timeout=TIMEOUT_SECONDS,
                cancel=cancel,
                ok_codes={0, 1, NO_PACKAGES_EXIT},
            )
        except ToolUnavailable:
            return _not_analyzed("Escáner de dependencias no disponible")
        except ToolTimeout:
            return _not_analyzed("El escáner de dependencias agotó el tiempo")
        except RuntimeError:
            logger.exception("osv-scanner falló")
            return _not_analyzed("El escáner de dependencias falló")
    if not out.strip():
        return [FamilyResult(Family.CVE, "ok", "sin manifiestos de dependencias", [])]
    try:
        findings = _parse(repo_root, json.loads(out))
    except (ValueError, TypeError, AttributeError):
        logger.exception("salida de osv-scanner inesperada")
        return _not_analyzed("El escáner de dependencias falló")
    return [FamilyResult(Family.CVE, "ok", None, findings)]


def _parse(repo_root: Path, data: object) -> list[Finding]:
    if not isinstance(data, dict):
        raise ValueError("forma inesperada")
    root = repo_root.resolve()
    findings: list[Finding] = []
    for result in data.get("results") or []:
        src = result["source"]["path"]
        if not src:
            continue
        manifest = Path(src).resolve()
        if not manifest.is_relative_to(root):
            continue
        rel = manifest.relative_to(root).as_posix()
        for pkg in result.get("packages") or []:
            groups = pkg.get("groups") or []
            if not groups:
                continue
            info = pkg["package"]
            name, version = info.get("name", "?"), info.get("version", "?")
            score = max(_score(g) for g in groups)
            ids = sorted({a for g in groups for a in g.get("aliases", []) if a.startswith("CVE-")})
            shown = ", ".join(ids[:3]) or groups[0].get("ids", ["?"])[0]
            line = _line_of(manifest, name)
            findings.append(
                Finding(
                    family=Family.CVE,
                    severity=_severity(score),
                    file=rel,
                    line_start=line,
                    line_end=line,
                    title=f"{name} {version}: {len(groups)} vulnerabilidades conocidas",
                    why=f"{name} {version} tiene {len(groups)} avisos (CVSS máx. {score}): {shown}.",
                    fix=f"Actualiza {name} a una versión corregida.",
                    source="osv-scanner",
                )
            )
    return findings
