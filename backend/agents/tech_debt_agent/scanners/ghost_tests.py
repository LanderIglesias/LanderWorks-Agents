import ast
import logging
import re
import threading
from pathlib import Path

from backend.agents.tech_debt_agent.findings import Family, FamilyResult, Finding, Severity
from backend.agents.tech_debt_agent.tools import Cancelled

logger = logging.getLogger(__name__)

SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
MAX_BYTES = 1_000_000
MAX_JS_BLOCK_LINES = 200
# Sin ruta ni línea: el informe lo renderiza como "." sin ":línea".
NO_TESTS_FILE = "."

_PY_TEST = re.compile(r"(?:^|/)(?:test_[^/]*|[^/]*_test)\.py$")
_JS_TEST = re.compile(r"\.(?:test|spec)\.[jt]sx?$")
_JS_START = re.compile(r"^\s*(?:it|test)(?:\.(?:only|concurrent|each|failing))*\s*[(`]")
_JS_ASSERT = re.compile(r"\bexpect\s*[(.]|\bassert\w*\b|\.should\b")
_STRING = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`")
_MOCK_FACTORIES = {"Mock", "MagicMock", "AsyncMock", "NonCallableMock", "create_autospec", "patch"}
_MOCK_ASSERT_PREFIXES = (
    "assert_called",
    "assert_any_call",
    "assert_has_calls",
    "assert_not_called",
    "assert_awaited",
    "assert_not_awaited",
    "assert_any_await",
    "assert_has_awaits",
)

_WHY = {
    "none": "Un test sin comprobaciones pasa siempre: da falsa sensación de cobertura y no detecta regresiones.",
    "trivial": "Un assert constante nunca falla: el test no verifica ningún comportamiento.",
    "mock": "Comprobar solo el mock verifica la propia simulación, no el código real bajo prueba.",
    "js": "Un test sin expect ni assert pasa siempre: no detecta regresiones.",
    "missing": "Sin tests no hay red de seguridad: cualquier cambio puede romper el código sin que nadie se entere.",
}
_FIX = {
    "none": "Añade asserts sobre el resultado o el efecto observable (assert, pytest.raises).",
    "trivial": "Sustituye el assert constante por una comprobación del resultado real.",
    "mock": "Comprueba el valor devuelto o el estado resultante, no solo las llamadas al mock.",
    "js": "Añade expect(...) sobre el resultado o el efecto observable.",
    "missing": "Añade tests automáticos para la lógica principal (pytest, vitest o jest).",
}
_PY_TITLES = {
    "none": ("test sin asserts", Severity.HIGH),
    "trivial": ("assert trivial", Severity.HIGH),
    "mock": ("test que solo comprueba mocks", Severity.MEDIUM),
}


def _finding(kind: str, severity: Severity, file: str, line: int | None, title: str) -> Finding:
    return Finding(
        family=Family.GHOST_TESTS,
        severity=severity,
        file=file,
        line_start=line,
        line_end=line,
        title=title,
        why=_WHY[kind],
        fix=_FIX[kind],
        source="ghost_tests",
    )


def _relative(root: Path, path: Path) -> str | None:
    try:
        full = path if path.is_absolute() else root / path
        return full.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _mock_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = {a.arg for a in fn.args.args if a.arg.startswith("mock")}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if _call_name(node.value) in _MOCK_FACTORIES:
                names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.withitem):
            ctx = node.context_expr
            if isinstance(ctx, ast.Call) and _call_name(ctx) in _MOCK_FACTORIES:
                if isinstance(node.optional_vars, ast.Name):
                    names.add(node.optional_vars.id)
    return names


def _classify_call(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name):
        return "real" if f.id.lower().startswith(("assert", "expect")) else None
    if not isinstance(f, ast.Attribute):
        return None
    attr = f.attr
    if attr.startswith(_MOCK_ASSERT_PREFIXES):
        return "mock"
    recv = f.value
    is_name = isinstance(recv, ast.Name)
    if is_name and recv.id == "pytest" and attr in {"raises", "warns", "fail"}:
        return "real"
    if is_name and recv.id == "self" and attr == "fail":
        return "real"
    return "real" if attr.startswith(("assert", "expect")) else None


def _verdict(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """'none', 'trivial' o 'mock'; None si el test tiene alguna comprobación real."""
    mocks = _mock_names(fn)
    trivial = mock = 0
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            t = node.test
            if isinstance(t, ast.Constant) and t.value:
                trivial += 1
                continue
            used = {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
            if used and used <= mocks:
                mock += 1
                continue
            return None
        if isinstance(node, ast.Call):
            kind = _classify_call(node)
            if kind == "real":
                return None
            if kind == "mock":
                mock += 1
    if trivial:
        return "trivial"
    return "mock" if mock else "none"


def _scan_python(rel: str, text: str) -> list[Finding]:
    # Heurística: es comprobación real un assert no constante que no verse solo sobre Mocks,
    # pytest.raises/warns/fail, self.assert*/self.fail y helpers assert*/expect*.
    # ponytail: un helper con otro nombre (check_x) no se reconoce; se marcaría como sin asserts.
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    out: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test_"
        ):
            kind = _verdict(node)
            if kind:
                title, sev = _PY_TITLES[kind]
                out.append(_finding(kind, sev, rel, node.lineno, f"{title}: {node.name}"))
    return out


def _strip_js(line: str) -> str:
    return _STRING.sub('""', line).split("//", 1)[0]


def _scan_js(rel: str, text: str) -> list[Finding]:
    # ponytail: strings y comentarios de una línea se ignoran al contar delimitadores; un template
    # literal o un /* */ multilínea con llaves puede desajustar el bloque (tope de 200 líneas).
    lines = [_strip_js(x) for x in text.splitlines()]
    out: list[Finding] = []
    for i, line in enumerate(lines):
        if not _JS_START.match(line):
            continue
        depth = 0
        started = False
        end = i
        for j in range(i, min(i + MAX_JS_BLOCK_LINES, len(lines))):
            end = j
            for ch in lines[j]:
                if ch in "({[":
                    depth += 1
                    started = True
                elif ch in ")}]":
                    depth -= 1
            if started and depth <= 0:
                break
        if not _JS_ASSERT.search("\n".join(lines[i : end + 1])):
            out.append(_finding("js", Severity.HIGH, rel, i + 1, "test sin expect ni assert"))
    return out


def scan_ghost_tests(
    repo_root: Path, files: list[Path], cancel: threading.Event
) -> list[FamilyResult]:
    root = repo_root.resolve()
    tests: list[tuple[str, Path]] = []
    has_source = False
    for f in files:
        rel = _relative(root, f)
        if rel is None or f.suffix not in SOURCE_SUFFIXES:
            continue
        if _PY_TEST.search(rel) or _JS_TEST.search(rel):
            tests.append((rel, root / rel))
        else:
            has_source = True
    if not tests and not has_source:
        return [FamilyResult(Family.GHOST_TESTS, "not_analyzed", "sin código fuente")]
    if not tests:
        missing = _finding(
            "missing", Severity.CRITICAL, NO_TESTS_FILE, None, "el proyecto no tiene tests"
        )
        return [FamilyResult(Family.GHOST_TESTS, "ok", None, [missing])]
    findings: list[Finding] = []
    for rel, path in tests:
        if cancel.is_set():
            raise Cancelled()
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.warning("no se pudo leer un archivo de test")
            continue
        findings += _scan_python(rel, text) if rel.endswith(".py") else _scan_js(rel, text)
    return [FamilyResult(Family.GHOST_TESTS, "ok", None, findings)]
