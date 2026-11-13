import json
import logging
import os
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
# ponytail: lista parcial de manifiestos (Python/JS); si falta uno, un 128 se reporta como fallo (lado seguro).
MANIFESTS = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "uv.lock",
    "pdm.lock",
}
# Sin lockfile no hay versiones fijadas: osv-scanner no los extrae y sale con 128.
UNLOCKED = {"package.json", "pyproject.toml"}
NO_LOCKFILE_MSG = "Sin lockfile ni requirements con versiones fijadas: no se pueden comprobar CVEs"


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
    # Grep barato; en package-lock.json la entrada "node_modules/<name>" va antes que las menciones sueltas.
    needles = (f'node_modules/{name.lower()}"', name.lower())
    try:
        lines = manifest.read_text(encoding="utf-8", errors="replace").lower().splitlines()
    except OSError:
        return None
    for needle in needles:
        for n, line in enumerate(lines, 1):
            if needle in line:
                return n
    return None


def _manifest_kind(repo_root: Path) -> str | None:
    """'locked' si hay algo que osv-scanner sabe leer, 'unlocked' si solo hay manifiestos sin versiones."""
    kind = None
    for _dir, dirs, names in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
        if any(n in MANIFESTS or n.startswith("requirements") for n in names):
            return "locked"
        if any(n in UNLOCKED for n in names):
            kind = "unlocked"
    return kind


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
        # 128 = "No package sources found"; run_tool no devuelve stderr, así que se confirma buscando manifiestos conocidos.
        kind = _manifest_kind(repo_root)
        if kind == "locked":
            logger.error("osv-scanner sin salida pese a haber manifiestos")
            return _not_analyzed("El escáner de dependencias falló")
        if kind == "unlocked":
            return _not_analyzed(NO_LOCKFILE_MSG)
        return [FamilyResult(Family.CVE, "ok", "sin manifiestos de dependencias", [])]
    try:
        findings = _parse(repo_root, json.loads(out))
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
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
