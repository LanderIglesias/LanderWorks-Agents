import csv
import io
import logging
import re
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
LIZARD_VERSION = "1.26.0"
TIMEOUT_SECONDS = 120
SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
CCN_HIGH = 15
CCN_MEDIUM = 10
FILE_LINES_LIMIT = 400
DUP_UNAVAILABLE = "duplicación no disponible"
_LOCATION = re.compile(r"^(.+):(\d+) ~ (\d+)$")


class _Unparseable(Exception):
    pass


def _relative(root: Path, name: str) -> str | None:
    path = Path(name)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


def _complexity(root: Path, out: str) -> list[Finding]:
    findings: list[Finding] = []
    for row in csv.reader(io.StringIO(out)):
        if not row:
            continue
        ccn = int(row[1])
        rel = _relative(root, row[6])
        if rel is None or ccn <= CCN_MEDIUM:
            continue
        severity = Severity.HIGH if ccn > CCN_HIGH else Severity.MEDIUM
        findings.append(
            Finding(
                family=Family.MONOLITH,
                severity=severity,
                file=rel,
                line_start=int(row[9]),
                line_end=int(row[10]),
                title=f"Función {row[7]} con complejidad ciclomática {ccn}",
                why="Demasiadas ramas en una sola función: difícil de entender, probar y modificar.",
                fix="Divide la función en piezas más pequeñas con una responsabilidad cada una.",
                source="lizard",
            )
        )
    return findings


def _line_count(path: Path) -> int:
    with path.open("rb") as fh:
        return sum(1 for _ in fh)


def _big_files(root: Path, rels: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for rel in rels:
        # Líneas físicas, no NLOC de lizard: el CSV solo da NLOC por función y el fixture
        # (441 líneas, 314 NLOC) debe contar como archivo largo.
        total = _line_count(root / rel)
        if total > FILE_LINES_LIMIT:
            findings.append(
                Finding(
                    family=Family.MONOLITH,
                    severity=Severity.MEDIUM,
                    file=rel,
                    line_start=1,
                    line_end=total,
                    title=f"Archivo de {total} líneas",
                    why="Archivo enorme que mezcla responsabilidades.",
                    fix="Reparte el contenido en módulos cohesivos por responsabilidad.",
                    source="lizard",
                )
            )
    return findings


def _duplicates(root: Path, out: str) -> list[Finding]:
    if "Duplicates" not in out:
        raise _Unparseable
    blocks: list[list[tuple[str, int, int]]] = []
    current: list[tuple[str, int, int]] | None = None
    for raw in out.splitlines():
        line = raw.strip()
        if line == "Duplicate block:":
            current = []
            blocks.append(current)
        elif current is not None:
            m = _LOCATION.match(line)
            if m:
                rel = _relative(root, m.group(1))
                if rel is not None:
                    current.append((rel, int(m.group(2)), int(m.group(3))))
    findings: list[Finding] = []
    for block in blocks:
        for i, (rel, start, end) in enumerate(block):
            others = ", ".join(f"{f}:{s}" for j, (f, s, _e) in enumerate(block) if j != i)
            findings.append(
                Finding(
                    family=Family.MONOLITH,
                    severity=Severity.MEDIUM,
                    file=rel,
                    line_start=start,
                    line_end=max(start, end),
                    title=f"Bloque duplicado (también en {others})",
                    why="Código copiado y pegado: cada corrección hay que repetirla en todas las copias.",
                    fix="Extrae el bloque común a una función compartida.",
                    source="lizard",
                )
            )
    return findings


def _run(exe: str, extra: list[str], chunk: list[str], root: Path, cancel) -> str:
    return run_tool(
        [exe, *extra, *chunk],
        cwd=root,
        timeout=TIMEOUT_SECONDS,
        cancel=cancel,
        ok_codes={0, 1},  # lizard sale con 1 si alguna función supera su umbral por defecto
    )


def scan_complexity(
    repo_root: Path, files: list[Path], cancel: threading.Event
) -> list[FamilyResult]:
    def not_analyzed(reason: str) -> list[FamilyResult]:
        return [FamilyResult(Family.MONOLITH, "not_analyzed", reason)]

    root = repo_root.resolve()
    rels = [r for f in files if f.suffix in SUFFIXES and (r := _relative(root, str(f)))]
    if not rels:
        return not_analyzed("sin archivos de código fuente")
    exe = find_executable("lizard")
    if exe is None:
        return not_analyzed("Escáner de complejidad no disponible")
    # "./" evita que un nombre que empiece por "-" se lea como opción.
    chunks = chunk_args([f"./{r}" for r in rels])
    try:
        findings = _big_files(root, rels)
        for chunk in chunks:
            findings += _complexity(root, _run(exe, ["--csv"], chunk, root, cancel))
    except ToolUnavailable:
        return not_analyzed("Escáner de complejidad no disponible")
    except ToolTimeout:
        return not_analyzed("El escáner de complejidad agotó el tiempo")
    except (RuntimeError, OSError):
        logger.exception("lizard falló")
        return not_analyzed("El escáner de complejidad falló")
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        logger.exception("salida de lizard inesperada")
        return not_analyzed("El escáner de complejidad falló")

    reason = None
    try:
        dups: list[Finding] = []
        # ponytail: la duplicación solo se detecta dentro de cada lote de archivos
        # (límite de la línea de comandos en Windows); repos enormes pierden duplicados entre lotes.
        for chunk in chunks:
            dups += _duplicates(root, _run(exe, ["-Eduplicate"], chunk, root, cancel))
        findings += dups
    except (ToolUnavailable, ToolTimeout, RuntimeError, OSError, _Unparseable):
        logger.exception("lizard -Eduplicate falló")
        reason = f"{DUP_UNAVAILABLE.capitalize()}: solo se midió la complejidad"
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        logger.exception("salida de duplicación inesperada")
        reason = f"{DUP_UNAVAILABLE.capitalize()}: solo se midió la complejidad"
    return [FamilyResult(Family.MONOLITH, "ok", reason, findings)]
